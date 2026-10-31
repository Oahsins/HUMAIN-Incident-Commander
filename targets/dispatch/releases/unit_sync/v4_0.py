"""Unit-sync release 4.0: the unit status interface, which applies reports from unit terminals to CAD.

cad takes each terminal's report in as it arrives (table field_queue). Each cycle this worker takes the oldest
pending reports and reads them all before it writes anything:
- a report it can read (targets/dispatch/fieldmsg.py) is applied, or skipped when it is too old
  (max_message_age_s), when a newer report of the same unit is waiting (the newest carries the unit's whole
  state, so catching up never writes an old one), or when it is not newer than the last report applied for its
  unit (the ordering memory, held in this process only: a restart forgets it);
- the reports before the first one it cannot read are applied in one transaction. That report's attempts are
  then raised and the process stops, as an interface with no dead-letter queue does. It stops again on the
  same report after each restart, until operations set the report aside (quarantine).

Applying a report writes the unit's record and keeps CAD's assignments in step with the state the report
carries, never moving an assignment or an incident backwards. En route or on scene acknowledges the unit's
assignment to that incident (or records one, when the crew took the incident on without an open one), moves the
incident on, and clears the unit's other work. Available clears the work the crew had taken on and closes each
incident left with no unit. An assignment the crew has not yet acknowledged is left to the dispatcher's
acknowledgement timer: a new dispatch may be on its way to the crew.
"""

import math
import time

from targets.dispatch import cadstore, fieldmsg
from targets.dispatch.worker import Worker

ASSIGNMENT_RANK = {"assigned": 0, "alerted": 1, "acked": 2, "onscene": 3}   # an assignment never moves down
INCIDENT_RANK = {"pending": 0, "dispatched": 1, "enroute": 2, "onscene": 3}  # nor does an open incident
OPEN_ASSIGNMENT = ", ".join(f"'{status}'" for status in cadstore.OPEN_ASSIGNMENT)
OPEN_INCIDENT = ", ".join(f"'{status}'" for status in cadstore.OPEN_INCIDENT)


class Release(Worker):
    SETTINGS = {"poll_interval_s": ("num", 0, 60), "batch_size": ("int", 1, 10000),
                "max_message_age_s": ("num", 0, 3600)}
    OPERATION = "apply"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.newest = {}     # the ordering memory: unit -> time of the newest report applied, this process only
        self.applying = {}   # the same for the transaction in progress; merged into newest once it commits

    def cycle(self, conn, settings):
        items, latest = self.take_batch(conn, settings)
        readable = []
        for item in items:
            try:
                readable.append((item, self.parse(item)))
            except Exception as exc:   # the first report it cannot read: keep the ones before it, then stop
                self.apply_reports(conn, readable, settings, latest)
                conn.execute("UPDATE field_queue SET attempts = attempts + 1, updated_t = ? WHERE id = ?",
                             (time.time(), item["id"]))
                self.crash(exc, item_id=item["id"])
                return len(readable)   # not reached: crash() ends the process
        return self.apply_reports(conn, readable, settings, latest)

    def take_batch(self, conn, settings):
        """The oldest batch_size pending reports, and latest: each unit's newest readable pending report (its
        id), taken from the reports themselves, since the queue's unit_id column is only what cad saw."""
        size = settings["batch_size"]
        items = [dict(row) for row in conn.execute(
            "SELECT id, payload_json, attempts FROM field_queue WHERE status = 'pending' ORDER BY id LIMIT ?",
            (size,))]
        rows = items
        if len(items) == size:   # more are waiting, and a newer report of a unit outdates this batch's
            rows = items + conn.execute("SELECT id, payload_json FROM field_queue WHERE status = 'pending' "
                                        "AND id > ? ORDER BY id", (items[-1]["id"],)).fetchall()
        latest = {}
        for row in rows:
            try:
                latest[self.parse(row).unit] = row["id"]
            except Exception:
                continue   # a report that cannot be read outdates nothing
        return items, latest

    def parse(self, item):
        """The report a queue row holds; ValueError naming the field, never its value, when it cannot be read."""
        return fieldmsg.parse(item["payload_json"])

    def in_order(self, msg):
        """Is the report newer than every report this process has applied for its unit?"""
        seen = max(self.newest.get(msg.unit, -math.inf), self.applying.get(msg.unit, -math.inf))
        return msg.t > seen

    def apply_reports(self, conn, readable, settings, latest):
        """Apply or skip each readable report, all in one transaction. The ordering memory takes the new times
        only once it has committed: a busy cad-db rolls the whole batch back, to be tried again."""
        if not readable:
            return 0
        self.applying = {}
        conn.execute("BEGIN IMMEDIATE")
        for item, msg in readable:
            self.apply(conn, item, msg, settings, latest)
        conn.execute("COMMIT")
        for unit, t in self.applying.items():
            self.newest[unit] = max(t, self.newest.get(unit, t))
        self.applying = {}
        return len(readable)

    def apply(self, conn, item, msg, settings, latest):
        """Apply one readable report, or skip it, and mark its row applied or skipped. Returns "applied", the
        reason it was skipped ("too old", "superseded", "out of order"), or None when the row was set aside
        meanwhile."""
        now = time.time()
        if msg.t < now - settings["max_message_age_s"]:
            outcome = "too old"
        elif item["id"] < latest.get(msg.unit, item["id"]):
            outcome = "superseded"   # a newer report of the unit is waiting and carries its whole state
        elif not self.in_order(msg):
            outcome = "out of order"
        else:
            outcome = "applied"
        status = "applied" if outcome == "applied" else "skipped"
        taken = conn.execute("UPDATE field_queue SET status = ?, updated_t = ? WHERE id = ? "
                             "AND status = 'pending'", (status, now, item["id"])).rowcount
        if not taken:
            return None
        if outcome == "applied":
            self.apply_unit(conn, msg)
            self.apply_assignment(conn, msg)
            self.applying[msg.unit] = max(msg.t, self.applying.get(msg.unit, msg.t))
        else:
            self.log_every(f"skipped:{outcome}", 2.0, "INFO" if outcome == "superseded" else "WARN", "skipped",
                           f"report {item['id']} from {msg.unit} skipped ({outcome})",
                           reason=outcome, item_id=item["id"], unit=msg.unit)
        return outcome

    def apply_unit(self, conn, msg):
        """Write the unit's record as the report gives it. status_since moves only when the status or the
        incident changes, as does the history trigger. Returns True on such a change."""
        now = time.time()
        row = conn.execute("SELECT status, incident_id FROM units WHERE id = ?", (msg.unit,)).fetchone()
        if row is None:
            return False
        changed = (row["status"], row["incident_id"]) != (msg.status, msg.incident_id)
        conn.execute("UPDATE units SET status = ?, incident_id = ?, status_t = ?, applied_t = ?, "
                     "source = 'field', status_since = CASE WHEN ? THEN ? ELSE status_since END WHERE id = ?",
                     (msg.status, msg.incident_id, float(msg.t), now, int(changed), now, msg.unit))
        if changed:
            self.log.info("status_applied", f"{msg.unit} is {msg.status}"
                          + (f" for incident {msg.incident_id}" if msg.incident_id is not None else ""),
                          unit=msg.unit, status=msg.status, incident_id=msg.incident_id)
        return changed

    def apply_assignment(self, conn, msg):
        """Keep the unit's assignments, and their incidents, in step with the state the report carries."""
        now = time.time()
        if msg.status == "available":
            self.clear(conn, msg.unit, None, now)
            return
        if msg.status not in ("enroute", "onscene"):
            return   # outofservice: the unit record only
        incident = conn.execute("SELECT status, test FROM incidents WHERE id = ?", (msg.incident_id,)).fetchone()
        if incident is None:
            self.log_every("unit_on_unknown_incident", 2.0, "WARN", "unit_on_unknown_incident",
                           f"{msg.unit} reports {msg.status} for incident {msg.incident_id}, which CAD does not "
                           f"hold; only the unit record was updated", unit=msg.unit, incident_id=msg.incident_id)
            return
        target = "acked" if msg.status == "enroute" else "onscene"
        rows = conn.execute(f"SELECT id, status FROM assignments WHERE incident_id = ? AND unit_id = ? "
                            f"AND status IN ({OPEN_ASSIGNMENT})", (msg.incident_id, msg.unit)).fetchall()
        for row in rows:
            if ASSIGNMENT_RANK[row["status"]] < ASSIGNMENT_RANK[target]:
                conn.execute("UPDATE assignments SET status = ?, acked_t = COALESCE(acked_t, ?) WHERE id = ?",
                             (target, now, row["id"]))
        if not rows:   # the crew is on an incident it holds no open assignment for: record what it is doing
            conn.execute("INSERT INTO assignments (incident_id, unit_id, status, source, test, assigned_t, "
                         "acked_t) VALUES (?, ?, ?, 'field', ?, ?, ?)",
                         (msg.incident_id, msg.unit, target, incident["test"], now, now))
        if incident["status"] in cadstore.CLOSED_INCIDENT:
            self.log_every("unit_on_closed_incident", 2.0, "WARN", "unit_on_closed_incident",
                           f"{msg.unit} reports {msg.status} for incident {msg.incident_id}, which is "
                           f"{incident['status']}; it stays {incident['status']}",
                           unit=msg.unit, incident_id=msg.incident_id, status=incident["status"])
        elif INCIDENT_RANK.get(incident["status"], len(INCIDENT_RANK)) < INCIDENT_RANK[msg.status]:
            conn.execute("UPDATE incidents SET status = ?, updated_t = ? WHERE id = ?",
                         (msg.status, now, msg.incident_id))
        self.clear(conn, msg.unit, msg.incident_id, now)

    def clear(self, conn, unit, keep, now):
        """Clear the unit's acked and onscene assignments, except those for incident `keep`, and close each of
        their incidents left with no open assignment: the crew has finished there."""
        rows = conn.execute("SELECT id, incident_id FROM assignments WHERE unit_id = ? "
                            "AND status IN ('acked', 'onscene') AND incident_id IS NOT ? ORDER BY id",
                            (unit, keep)).fetchall()   # keep None: every incident
        for row in rows:
            conn.execute("UPDATE assignments SET status = 'cleared', closed_t = ? WHERE id = ?", (now, row["id"]))
        for incident_id in dict.fromkeys(row["incident_id"] for row in rows):
            conn.execute(f"UPDATE incidents SET status = 'closed', close_reason = 'completed', closed_t = ?, "
                         f"updated_t = ? WHERE id = ? AND status IN ({OPEN_INCIDENT}) AND NOT EXISTS "
                         f"(SELECT 1 FROM assignments WHERE incident_id = ? AND status IN ({OPEN_ASSIGNMENT}))",
                         (now, now, incident_id, incident_id))
