"""Dispatcher release 2.1: the automated dispatch positions.

Each cycle, in this order:
1. station alerts that did not go through are sent again every 0.3 s, until one is delivered or the
   acknowledgement timer gives up on the unit. When an alert gets no answer (or a server error), the station
   alerting path is down, not that alert: the other alerts wait their turn for 0.3 s instead of each waiting out
   alert_timeout_s, so a path that does not answer costs a cycle at most one timeout, and the timer and new
   commits keep their pace;
2. the acknowledgement timer: an assignment still assigned or alerted after ack_timeout_s becomes no_ack, and
   an incident left with no other unit goes back to pending, never to be offered that unit again;
3. pending incidents are taken in priority order, oldest first within a priority. Each gets a free unit of its
   preferred type, or of any type when none of that type is free: the closest by station (or the first in
   roster order), committed in one short transaction. The station is alerted right after the commit, on the
   side routing says is active.

Test incidents are read in their own query and only ever get TEST-1, so a backlog of real calls never holds up
the test call. An incident with no free unit waits and does not count toward batch_size. Incidents are live
calls: one the dispatcher cannot read is skipped and logged, never set aside.

All state lives in cad-db, so a restart loses nothing. The dispatcher never writes unit records (only the
units' own reports do), and it never holds a cad-db transaction open while it calls alerting.
"""

import math
import time

from ic.kit import net
from targets.dispatch import area, cadstore
from targets.dispatch.worker import Worker

RETRY_S = 0.3   # an alert that was not delivered is sent again after this long
OPEN = ", ".join(f"'{status}'" for status in cadstore.OPEN_ASSIGNMENT)
ROSTER_ORDER = {unit: n for n, unit in enumerate(area.UNIT_IDS)}
ALERT = ("assignment_id", "incident_id", "unit", "station", "priority", "nature", "x", "y")

INCIDENT = "SELECT id, nature, priority, unit_type, x, y, test FROM incidents"
# A unit CAD can commit: shown available, and holding no open assignment (a record lags its crew: a unit alerted
# a moment ago still shows available). Parameters: the test flag, then the incident, which the unit must not
# already have failed to acknowledge.
FREE = (f"SELECT u.id, u.type, u.station FROM units u WHERE u.status = 'available' AND u.test = ? "
        f"AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.unit_id = u.id AND a.status IN ({OPEN})) "
        f"AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.unit_id = u.id AND a.incident_id = ? "
        f"AND a.status = 'no_ack')")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def unreadable_field(incident):
    """The first field of an incident row the dispatcher needs but cannot read, or None."""
    if not _number(incident["priority"]):
        return "priority"
    if not (_number(incident["x"]) and _number(incident["y"])):
        return "location"
    if incident["test"] not in (0, 1):
        return "test"
    for field in ("unit_type", "nature"):
        if not isinstance(incident[field], str):
            return field
    return None


def station_distance(station, place):
    """Straight-line km from a station to a place; a station not on the map is never the closest."""
    xy = area.TEST_XY if station == area.TEST_STATION else area.STATIONS.get(station)
    return area.distance(xy, place) if xy else math.inf


class Release(Worker):
    SETTINGS = {"poll_interval_s": ("num", 0, 60), "batch_size": ("int", 1, 10000),
                "ack_timeout_s": ("num", 0, 60), "alert_timeout_s": ("num", 0, 10),
                "recommend_by": ("enum", ("closest", "station_order"))}
    OPERATION = "dispatch"
    alerts_held_until = 0.0   # after the alerting path fails, the other alerts wait until then (send_alert)

    def cycle(self, conn, settings):
        self.retry_alerts(conn, settings)
        self.expire_unacknowledged(conn, settings)
        committed = 0
        for incident in self.pending_batch(conn, settings):
            units = self.free_units(conn, incident)
            unit = self.recommend(incident, units, settings) if units else None
            if unit is None:
                self.log_every("no_unit_free", 2.0, "INFO", "no_unit_free",
                               f"incident {incident['id']} waits: no unit is free for it",
                               incident_id=incident["id"])
                if not incident["test"] and not self.any_unit_free(conn):
                    break   # no real unit of any type is free: every other real incident waits too
                continue
            assignment = self.assign(conn, incident, unit)
            if assignment is None:
                continue
            if not self.alerts_held():   # else its alert is due at once, and the next retry sends it
                self.send_alert(conn, assignment, settings)
            if not incident["test"]:
                committed += 1
                if committed >= settings["batch_size"]:
                    break
        return committed

    def any_unit_free(self, conn):
        """Is any real unit free at all, whatever incident it would go to?"""
        return conn.execute(FREE + " LIMIT 1", (0, None)).fetchone() is not None   # no incident excludes a unit

    def alerts_held(self):
        """Did the station alerting path fail in the last 0.3 s? Then alerts wait for their next turn."""
        return time.time() < self.alerts_held_until

    def retry_alerts(self, conn, settings):
        """Send again each alert that is due: still assigned, with next_alert_t come. The rows are read first,
        then each alert goes out with no transaction open. Once the alerting path fails, the rest stay due."""
        rows = conn.execute(
            "SELECT a.id AS assignment_id, a.incident_id, a.unit_id AS unit, u.station, i.priority, i.nature, "
            "i.x, i.y, i.unit_type, i.test FROM assignments a JOIN incidents i ON i.id = a.incident_id "
            "LEFT JOIN units u ON u.id = a.unit_id WHERE a.status = 'assigned' AND a.next_alert_t <= ? "
            "ORDER BY a.id", (time.time(),)).fetchall()
        sent = 0
        for row in rows:
            if self.alerts_held():
                break   # the path did not answer: these go on their next turn, not each after a timeout
            assignment = dict(row)
            if self.unreadable(assignment, assignment["incident_id"]):
                continue   # the acknowledgement timer returns it to pending
            sent += bool(self.send_alert(conn, assignment, settings))
        return sent

    def expire_unacknowledged(self, conn, settings):
        """The acknowledgement timer, in one transaction: an assignment still assigned or alerted after
        ack_timeout_s becomes no_ack. Its incident, if dispatched with no other open assignment, goes back to
        pending; free_units never offers that unit for it again. An incident a crew has already reached (en route
        or on scene) and that is left with no open assignment closes as completed: every crew that took it on
        has cleared, and the unit sent as well never answered."""
        due = ("SELECT id, incident_id, unit_id FROM assignments WHERE status IN ('assigned', 'alerted') "
               "AND assigned_t < ? ORDER BY id")
        if conn.execute(due + " LIMIT 1", (time.time() - settings["ack_timeout_s"],)).fetchone() is None:
            return 0   # nothing due: no write lock taken
        conn.execute("BEGIN IMMEDIATE")
        now = time.time()
        rows = conn.execute(due, (now - settings["ack_timeout_s"],)).fetchall()
        no_unit_left = f"NOT EXISTS (SELECT 1 FROM assignments WHERE incident_id = ? AND status IN ({OPEN}))"
        for row in rows:
            incident_id = row["incident_id"]
            conn.execute("UPDATE assignments SET status = 'no_ack', closed_t = ? WHERE id = ?", (now, row["id"]))
            conn.execute(f"UPDATE incidents SET status = 'pending', attempts = attempts + 1, pending_since = ?, "
                         f"updated_t = ? WHERE id = ? AND status = 'dispatched' AND {no_unit_left}",
                         (now, now, incident_id, incident_id))
            conn.execute(f"UPDATE incidents SET status = 'closed', close_reason = 'completed', closed_t = ?, "
                         f"updated_t = ? WHERE id = ? AND status IN ('enroute', 'onscene') AND {no_unit_left}",
                         (now, now, incident_id, incident_id))
        conn.execute("COMMIT")
        for row in rows:
            self.log.warn("no_acknowledgement",
                          f"{row['unit_id']} did not acknowledge incident {row['incident_id']} in time",
                          assignment_id=row["id"], unit=row["unit_id"], incident_id=row["incident_id"])
        return len(rows)

    def pending_batch(self, conn, settings):
        """The incidents to dispatch now: every pending test incident (its own query), then every pending real
        incident by priority, then id. cycle() commits units to at most batch_size real incidents; one with no
        free unit does not count, so the scan goes on until batch_size are committed, the list ends, or no real
        unit is free."""
        rows = conn.execute(INCIDENT + " WHERE status = 'pending' AND test = 1 ORDER BY priority, id").fetchall()
        rows += conn.execute(INCIDENT + " WHERE status = 'pending' AND test = 0 ORDER BY priority, id").fetchall()
        return [dict(row) for row in rows if not self.unreadable(row, row["id"])]

    def unreadable(self, incident, incident_id):
        """Is a field the dispatcher needs unreadable? Logs which one, never its value."""
        field = unreadable_field(incident)
        if field:
            self.log_every(f"incident_unreadable:{incident_id}", 2.0, "ERROR", "incident_unreadable",
                           f"incident {incident_id} cannot be dispatched: its {field} cannot be read",
                           incident_id=incident_id, field=field)
        return field is not None

    def free_units(self, conn, incident):
        """Units CAD can commit to this incident: available, with its test flag, holding no open assignment, and
        never one that has already failed to acknowledge it."""
        return [dict(row) for row in conn.execute(FREE + " ORDER BY u.id", (incident["test"], incident["id"]))]

    def recommend(self, incident, units, settings):
        """The unit to send, or None. A test incident only ever gets TEST-1, and a real one never does. The
        preferred type when one is free, else any type; then the closest station (ties by unit id), or the first
        in roster order under station_order."""
        if incident["test"]:
            units = [u for u in units if u["id"] == area.TEST_UNIT]
        else:
            units = [u for u in units if u["id"] != area.TEST_UNIT]
        units = [u for u in units if u["type"] == incident["unit_type"]] or units
        if not units:
            return None
        if settings["recommend_by"] == "station_order":
            return min(units, key=lambda u: (ROSTER_ORDER.get(u["id"], len(ROSTER_ORDER)), u["id"]))
        place = (incident["x"], incident["y"])
        return min(units, key=lambda u: (station_distance(u["station"], place), u["id"]))

    def assign(self, conn, incident, unit):
        """Commit the unit in one transaction, re-checking inside it that the unit is still free and the incident
        still pending. Returns the alert to send, or None when either has changed."""
        conn.execute("BEGIN IMMEDIATE")
        now = time.time()
        pending = conn.execute("SELECT 1 FROM incidents WHERE id = ? AND status = 'pending'",
                               (incident["id"],)).fetchone()
        free = conn.execute(FREE + " AND u.id = ?", (incident["test"], incident["id"], unit["id"])).fetchone()
        if pending is None or free is None:
            conn.execute("ROLLBACK")
            return None
        assignment_id = conn.execute(
            "INSERT INTO assignments (incident_id, unit_id, status, source, test, assigned_t, next_alert_t) "
            "VALUES (?, ?, 'assigned', 'dispatcher', ?, ?, ?)",
            (incident["id"], unit["id"], incident["test"], now, now)).lastrowid
        conn.execute("UPDATE incidents SET status = 'dispatched', updated_t = ? WHERE id = ?",
                     (now, incident["id"]))
        conn.execute("COMMIT")
        self.log.info("unit_assigned", f"{unit['id']} committed to incident {incident['id']}",
                      incident_id=incident["id"], unit=unit["id"], assignment_id=assignment_id)
        return {"assignment_id": assignment_id, "incident_id": incident["id"], "unit": unit["id"],
                "station": free["station"], "priority": incident["priority"], "nature": incident["nature"],
                "x": incident["x"], "y": incident["y"]}

    def send_alert(self, conn, assignment, settings):
        """Alert the unit's station on the active side: the primary over the county network (the
        dispatcher->alerting link), or after a failover the backup radio tone path, directly. Delivered: the
        assignment becomes alerted. Not delivered: it is sent again in 0.3 s. Each update is its own short
        transaction, after the call."""
        if self.routing.active("alerting") == "standby":
            dep, url = "alerting-backup", self.url("alerting-backup", "/alert")
        else:
            dep, url = "alerting", self.url("dispatcher->alerting", "/alert")
        assignment_id = assignment["assignment_id"]
        body = {key: assignment[key] for key in ALERT}
        try:
            self.call(dep, "POST", url, body, timeout=settings["alert_timeout_s"])
        except net.CallError as exc:
            if exc.kind != "http" or (exc.status or 0) >= 500:   # the path failed, not this alert's content
                self.alerts_held_until = time.time() + RETRY_S
            conn.execute("UPDATE assignments SET next_alert_t = ? WHERE id = ? AND status = 'assigned'",
                         (time.time() + RETRY_S, assignment_id))
            self.log_every(f"alert_failed:{exc.kind}", 2.0, "WARN", "alert_failed",
                           f"station alert for assignment {assignment_id} not delivered via {dep} ({exc.kind}); "
                           f"sending again in {RETRY_S} s", assignment_id=assignment_id, kind=exc.kind, via=dep)
            return False
        conn.execute("UPDATE assignments SET status = 'alerted', alerted_t = ?, next_alert_t = NULL "
                     "WHERE id = ? AND status = 'assigned'", (time.time(), assignment_id))
        return True
