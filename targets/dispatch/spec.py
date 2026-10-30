"""What makes the test dispatch centre a dispatch centre: its components, its journey and how the six
actions apply (docs/DISPATCH.md).

The control plane in ic/kit/supervisor.py is generic. This file tells it:
- which components exist, how they depend on each other and what each one may have done to it;
- how to set up the CAD database and start the callers and crews;
- what the test call checks (the agent's probe);
- what CAD's own monitors show to the agent;
- how each generic action is carried out here.
"""

import json
import math
import os
import sqlite3
import time

from ic.contract import CONTRACT_VERSION
from ic.kit import net, proc
from ic.kit.store import ConfigStore, Routing, read_json, write_json
from targets.dispatch import area, cadstore, fieldmsg

JOURNEY = "emergency_call"
SLO = {"success_rate": 0.99, "p95_ms": 1000}
EMERGENCY_CALL = {
    "name": JOURNEY, "default": True, "entry": "call-handling", "slo": SLO, "side_effects": "test_data",
    "description": "a 9-1-1 caller is answered, gives the location and the emergency, is told help is on the way, "
                   "and a crew is en route soon after"}

COMPONENTS = [
    {"name": "call-handling", "kind": "service", "port_offset": 0, "version": "5.2", "image": "call_handling",
     "config": {"positions": 14, "rollover_s": 2.5, "ali_timeout_s": 0.5, "cad_timeout_s": 1.0},
     "depends_on": ["call-network", "cad"], "impact_weight": 1.0, "actions": ["restart", "rollback", "revert_config"],
     "description": "9-1-1 call handling: queues each 9-1-1 call for the call-taker positions, gets the caller's "
                    "location from the call network, and enters the incident in CAD"},
    {"name": "cad", "kind": "service", "port_offset": 1, "version": "3.4", "image": "cad",
     "config": {"repeat_match": "ani_open", "write_timeout_ms": 1000},
     "depends_on": ["cad-db"], "impact_weight": 1.0, "actions": ["restart", "rollback", "revert_config"],
     "description": "computer-aided dispatch server: creates incidents from calls, links a repeat call from the "
                    "same number to its open incident, and takes in status reports from unit terminals"},
    {"name": "dispatcher", "kind": "worker", "port_offset": 2, "version": "2.1", "image": "dispatcher",
     "config": {"poll_interval_s": 0.2, "batch_size": 20, "ack_timeout_s": 2.0, "alert_timeout_s": 1.0,
                "recommend_by": "closest"},
     "depends_on": ["cad-db", "alerting"], "impact_weight": 1.0, "actions": ["restart", "rollback", "revert_config"],
     "description": "automated dispatch: takes pending incidents in priority order, recommends the closest free "
                    "unit, commits it and sends the station alert"},
    {"name": "alerting", "kind": "dependency", "port_offset": 3, "version": "1.6", "image": "alerting", "config": {},
     "standby": "alerting-backup", "depends_on": [], "impact_weight": 1.0, "actions": ["restart", "failover"],
     "description": "station alerting controller: alerts the unit's station over the county network"},
    {"name": "alerting-backup", "kind": "dependency", "port_offset": 4, "version": "1.6", "image": "alerting",
     "config": {}, "depends_on": [], "impact_weight": 0.0, "actions": ["restart"],
     "description": "backup station alerting over the radio tone path; carries alerts only after a failover"},
    {"name": "unit-sync", "kind": "worker", "port_offset": 5, "version": "4.0", "image": "unit_sync",
     "config": {"poll_interval_s": 0.2, "batch_size": 200, "max_message_age_s": 10.0},
     "depends_on": ["cad-db"], "impact_weight": 0.6, "actions": ["restart", "rollback", "revert_config", "quarantine"],
     "description": "unit status interface: applies status reports from unit terminals to CAD's unit records"},
    {"name": "call-network", "kind": "external", "port_offset": 6, "version": "1.0", "image": "call_network",
     "config": {}, "depends_on": [], "impact_weight": 0.5, "actions": [],
     "description": "the 9-1-1 call network provider's location service (ALI), run by another organisation; "
                    "we cannot change it"},
    {"name": "cad-db", "kind": "datastore", "port_offset": None, "version": None, "config": None,
     "depends_on": [], "impact_weight": 1.0, "actions": ["release_lock"],
     "description": "the CAD database (SQLite): incidents, calls, units, assignments and the queue of reports "
                    "from unit terminals"},
    {"name": "incident-archive", "kind": "job", "port_offset": None, "version": None, "config": None,
     "depends_on": ["cad-db"], "impact_weight": 0.0, "actions": [],
     "description": "export of closed incidents to the records system; normal when not running"},
]

LINKS = {"dispatcher->alerting": {"listen_offset": 7, "upstream": "alerting"},
         "call-handling->call-network": {"listen_offset": 8, "upstream": "call-network"}}

START_ORDER = ["call-network", "alerting", "alerting-backup", "cad", "unit-sync", "dispatcher", "call-handling"]

ACTIONS = {
    "restart": {"est_seconds": 3, "undo": None, "params": {},
                "description": "restart the component's process; work in progress is dropped: on call-handling, "
                               "calls being answered are cut off and the callers must redial"},
    "rollback": {"est_seconds": 4, "undo": "deploy the newer release again", "params": {},
                 "description": "return the component to its previous release"},
    "revert_config": {"est_seconds": 1, "undo": "set the value again",
                      "params": {"key": {"optional": True, "description": "the setting to undo; default: the newest "
                                                                         "change not made by the incident commander"}},
                      "description": "undo one setting change on the component"},
    "release_lock": {"est_seconds": 1, "undo": None, "params": {},
                     "description": "end the session holding the datastore lock; its unfinished transaction rolls back"},
    "failover": {"est_seconds": 1, "undo": "fail over again with to=primary",
                 "params": {"to": {"enum": ["standby", "primary"]}},
                 "description": "switch the component's callers to its standby, or back to the primary"},
    "quarantine": {"est_seconds": 1, "undo": "operations can put the item back",
                   "params": {"item": {"from": "extra.head_item.id"}},
                   "description": "set one queued field report aside so unit-sync skips it; the unit's next report "
                                  "repeats its state"},
}

FORBIDDEN = ["close or cancel an incident", "change a call's priority",
             "stand down or reassign a unit committed to an incident", "contact a caller"]

CONTACTS = [{"role": "shift supervisor", "for": ["call-handling", "dispatcher"]},
            {"role": "CAD administrator", "for": ["cad", "cad-db", "unit-sync", "incident-archive"]},
            {"role": "radio and alerting technician", "for": ["alerting", "alerting-backup"]},
            {"role": "call network provider", "for": ["call-network"]}]

ALERT_INBOXES = {"alerting": "alerts-alerting.jsonl", "alerting-backup": "alerts-alerting-backup.jsonl"}
WRITERS = ("cad", "dispatcher", "unit-sync")   # the processes that write cad-db and count failed writes


def surge_registry_path(data_dir):
    return os.path.join(data_dir, "surge.json")


def live_entries(path, key):
    return [h for h in (read_json(path, {key: []}) or {}).get(key) or [] if proc.alive(h.get("pid"))]


class Spec:
    system = "dispatch"

    def components(self, condition="default"):
        return COMPONENTS

    def links(self):
        return LINKS

    def start_order(self, condition="default"):
        return START_ORDER

    def init_data(self, sup):
        d = sup.data_dir
        cadstore.create(d)
        write_json(cadstore.locks_path(d), {"holders": []})
        write_json(os.path.join(d, "probe.json"), {"seq": 0})
        write_json(surge_registry_path(d), {"helpers": []})
        os.makedirs(os.path.join(d, "surge-slots"), exist_ok=True)
        for name in (*ALERT_INBOXES.values(), "people.jsonl"):
            open(os.path.join(d, name), "a", encoding="utf-8").close()

    def traffic_argv(self, sup):
        return proc.python_argv("targets.dispatch.people", "--data", sup.data_dir, "--port", sup.ports["call-handling"],
                                "--mdt-port", sup.ports["cad"], "--seed", sup.seed)

    def cleanup(self, sup):
        for entry in (live_entries(cadstore.locks_path(sup.data_dir), "holders")
                      + live_entries(surge_registry_path(sup.data_dir), "helpers")):
            proc.kill(entry["pid"])

    # ----- what the agent sees -----

    def describe(self, sup):
        components = self.components(sup.condition)
        offered = {action for c in components for action in c["actions"]}
        return {
            "system": self.system, "contract_version": CONTRACT_VERSION,
            "capabilities": {"probe": True, "act": True, "changes": True, "baseline": "warmup",
                             "max_mode": "auto", "min_window_s": 2},
            "journeys": [EMERGENCY_CALL], "slo": SLO,
            "components": [{**{k: c[k] for k in ("name", "kind", "depends_on", "impact_weight", "actions",
                                                  "description")}, "standby": c.get("standby")}
                           for c in components],
            "actions": {name: spec for name, spec in ACTIONS.items() if name in offered},
            "forbidden": FORBIDDEN,
            "escalation_contacts": CONTACTS,
        }

    def observe_extra(self, sup, out, window_s):
        now = time.time()
        # Failed writes: each writer counts its own; they show as cad-db's write_errors, as a DBA's counter would.
        counts = [(out.get(name) or {}).get("extra", {}).pop("db_write_errors", None) for name in WRITERS]
        counts = [c for c in counts if isinstance(c, int)]
        store = out["cad-db"]
        store["extra"]["write_errors"] = sum(counts) if counts else None
        store["extra"]["lock_holders"] = [
            {"session": h.get("session"), "mode": h.get("mode"),
             "held_s": round(max(0.0, now - float(h.get("since_t") or now)), 1), "statement": h.get("statement", "")}
            for h in self._live_lock_holders(sup)]
        # CAD's monitors, read from cad-db itself, so they show while the dispatcher or unit-sync is down.
        try:
            conn = cadstore.connect(sup.data_dir, busy_timeout_ms=300, readonly=True)
            try:
                board = cadstore.pending_board(conn, now, window_s)
                queue = cadstore.field_queue_state(conn, now, window_s)
                unacknowledged = cadstore.units_not_acknowledging(conn, now)
                timers = cadstore.unit_status_timers_expired(conn, now)
                duplicates = cadstore.possible_duplicate_incidents(conn)
                overdue = cadstore.unit_reports_overdue(conn, now)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            store["up"] = False
            store["extra"]["error"] = f"cad-db cannot be read ({type(exc).__name__})"
        else:
            store["up"] = True
            out["dispatcher"]["extra"].update(board)
            out["dispatcher"]["extra"]["integrity"] = {"units_not_acknowledging": unacknowledged}
            out["cad"]["extra"]["integrity"] = {"unit_status_timers_expired": timers,
                                                "possible_duplicate_incidents": duplicates}
            out["unit-sync"]["extra"].update(queue)
            out["unit-sync"]["extra"]["integrity"] = {"unit_reports_overdue": overdue}
        # The export job: how hard it works while it runs.
        jobs = sup.jobs_named("incident-archive")
        archive = out["incident-archive"]
        archive["extra"]["runs"] = len(jobs)
        if jobs:
            usages = [proc.usage(job.pid) for job in jobs]
            archive["cpu_pct"] = round(sum(u["cpu_pct"] or 0 for u in usages), 1)
            archive["mem_mb"] = round(sum(u["mem_mb"] or 0 for u in usages), 1)

    def _live_lock_holders(self, sup):
        return live_entries(cadstore.locks_path(sup.data_dir), "holders")

    # ----- the test call (the agent's probe) -----

    def probe(self, sup, journey=None):
        journey = journey or JOURNEY
        if journey != JOURNEY:
            return {"journey": journey, "ok": False, "ms": 0,
                    "steps": [{"step": "journey", "component": None, "ok": False, "ms": 0.0,
                               "detail": "no journey named that"}]}
        started = time.perf_counter()
        steps = []
        try:
            self._test_call(sup, steps)
        except Exception as exc:   # the probe reports, it never raises
            steps.append({"step": "probe", "component": None, "ok": False, "ms": 0.0,
                          "detail": f"the test call could not finish ({type(exc).__name__})"})
        return {"journey": journey, "ok": bool(steps) and all(s["ok"] for s in steps),
                "ms": round((time.perf_counter() - started) * 1000, 1), "steps": steps}

    def _test_call(self, sup, steps):
        def step(name, ok, t0, detail, component=None):
            steps.append({"step": name, "component": component or name, "ok": bool(ok),
                          "ms": round((time.perf_counter() - t0) * 1000, 1), "detail": detail})
            return ok

        d = sup.data_dir
        self._clean_test_rows(d)
        doc = read_json(os.path.join(d, "probe.json"), {"seq": 0}) or {"seq": 0}
        seq = int(doc.get("seq") or 0) + 1
        write_json(os.path.join(d, "probe.json"), {"seq": seq})
        ani = area.test_number(seq)
        inbox_sizes = {name: _size(os.path.join(d, filename)) for name, filename in ALERT_INBOXES.items()}
        handling = f"http://127.0.0.1:{sup.ports['call-handling']}"
        cad = f"http://127.0.0.1:{sup.ports['cad']}"

        # call-handling answers the test call
        t0 = time.perf_counter()
        try:
            answer = net.post(f"{handling}/dial", {"ani": ani, "test": 1}, timeout=3.5)[1]
        except net.CallError as exc:
            return step("call-handling", False, t0, _error_detail(exc))
        call_id = answer.get("call_id") if isinstance(answer, dict) else None
        if not isinstance(call_id, str):
            return step("call-handling", False, t0, "answered without a call id")
        step("call-handling", True, t0, "answered")
        # call-network: the location service found the test caller (recorded; the call goes on either way)
        location = answer.get("location")
        located = _near(location, area.TEST_XY, 0.05)
        step("call-network", located, t0, "location verified" if located else
             "location not verified (unavailable)" if location is None else "location not verified (differs)")

        # cad: the call is entered and the caller is told help is on the way
        t1 = time.perf_counter()
        report = {"nature": "test", "narrative": ""}
        if not located:
            report["location"] = {"x": area.TEST_XY[0], "y": area.TEST_XY[1]}
        try:
            told = net.post(f"{handling}/calls/{call_id}/report", report, timeout=2.5)[1]
        except net.CallError as exc:
            at_cad = exc.kind == "http" and exc.status in (502, 504) and (exc.body or {}).get("at") == "cad"
            return step("cad" if at_cad else "call-handling", False, t1, _error_detail(exc))
        incident_id = told.get("incident_id") if isinstance(told, dict) else None
        if not (isinstance(told, dict) and told.get("told")) or not _whole(incident_id):
            return step("cad", False, t1, "the caller was not told help is on the way")
        step("cad", True, t1, f"told; incident {incident_id}")

        # cad-db: the incident is recorded as the call gave it
        t2 = time.perf_counter()
        ok, detail = _test_incident_recorded(d, incident_id, call_id)
        if not step("cad-db", ok, t2, detail):
            return False

        # dispatcher: TEST-1 is committed to the incident
        t3 = time.perf_counter()
        assignment_id = _poll(lambda: _test_assignment(d, incident_id), 2.5)
        if not step("dispatcher", assignment_id is not None, t3,
                    f"TEST-1 committed (assignment {assignment_id})" if assignment_id is not None
                    else "no unit committed within 2.5 s"):
            return False

        # alerting: the active side's station alert reached TEST's inbox
        t4 = time.perf_counter()
        side = Routing(d).active("alerting")
        component = "alerting" if side == "primary" else "alerting-backup"
        delivered = _poll(lambda: _alert_delivered(os.path.join(d, ALERT_INBOXES[component]),
                                                   inbox_sizes[component], assignment_id), 1.0)
        if not step(component, delivered, t4, f"alert delivered on {side}" if delivered
                    else f"alert not delivered on {side} within 1.0 s"):
            return False

        # unit-sync: the probe, as TEST-1's terminal, reports en route, and CAD's record follows
        t5 = time.perf_counter()
        try:
            net.post(f"{cad}/mdt", fieldmsg.build(area.TEST_UNIT, "status", "enroute", incident_id, time.time()),
                     timeout=1.0)
        except net.CallError as exc:
            return step("cad", False, t5, f"unit report not taken in: {_error_detail(exc)}")
        updated = _poll(lambda: _test_unit_shows(d, incident_id), 1.5)
        step("unit-sync", updated, t5, "unit record updated" if updated else "unit record not updated within 1.5 s")
        try:   # TEST-1 clears at once, which closes the test incident; nobody waits for it
            net.post(f"{cad}/mdt", fieldmsg.build(area.TEST_UNIT, "status", "available", None, time.time()),
                     timeout=1.0)
        except net.CallError:
            pass
        return updated

    def _clean_test_rows(self, data_dir):
        """Close test incidents left open by an earlier test call, and free TEST-1. Touches test rows only;
        skipped when cad-db is busy."""
        try:
            conn = cadstore.connect(data_dir, busy_timeout_ms=500)
        except sqlite3.Error:
            return
        try:
            now = time.time()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"UPDATE incidents SET status = 'closed', close_reason = 'test_cleanup', closed_t = ?, "
                         f"updated_t = ? WHERE test = 1 AND status IN ({cadstore.placeholders(cadstore.OPEN_INCIDENT)})",
                         (now, now, *cadstore.OPEN_INCIDENT))
            conn.execute(f"UPDATE assignments SET status = 'cleared', closed_t = ? WHERE unit_id = ? AND status IN "
                         f"({cadstore.placeholders(cadstore.OPEN_ASSIGNMENT)})",
                         (now, area.TEST_UNIT, *cadstore.OPEN_ASSIGNMENT))
            conn.execute("UPDATE units SET status = 'available', incident_id = NULL, status_since = ?, source = 'probe' "
                         "WHERE id = ? AND (status != 'available' OR incident_id IS NOT NULL)", (now, area.TEST_UNIT))
            conn.execute("COMMIT")
        except sqlite3.Error:
            try:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        finally:
            conn.close()

    # ----- how the generic actions are carried out here -----

    def act(self, sup, action, target, params, actor):
        params = params or {}
        try:
            if action == "restart":
                ok = sup.restart(target, actor)
                return ok, f"{target} restarted" + ("" if ok else ", but it is not answering health checks")
            if action == "rollback":
                return sup.rollback(target, actor)
            if action == "revert_config":
                return sup.revert_config(target, actor, key=params.get("key"))
            if action == "failover":
                return self._failover(sup, target, params, actor)
            if action == "release_lock":
                return self._release_lock(sup, actor)
            if action == "quarantine":
                return self._quarantine(sup, params, actor)
        except Exception as exc:   # act reports, it never raises
            return False, f"{action} on {target} failed ({type(exc).__name__})"
        return False, f"{action} is not carried out on {target}"

    def _failover(self, sup, target, params, actor):
        to = params.get("to") or "standby"
        if to not in ("standby", "primary"):
            return False, "failover needs params {\"to\": \"standby\" or \"primary\"}"
        routing = Routing(sup.data_dir)
        before = routing.active(target)
        if before == to:
            return False, f"{target} is already served by its {to}"
        routing.set(target, to)
        sup.changes.add(target, "failover", actor, **{"from": before, "to": to})
        return True, f"{target} now served by its {to}"

    def _release_lock(self, sup, actor):
        path = cadstore.locks_path(sup.data_dir)
        ended = []
        for holder in (read_json(path, {"holders": []}) or {}).get("holders") or []:
            if proc.alive(holder.get("pid")):
                proc.kill(holder["pid"])
                ended.append(holder.get("session"))
        write_json(path, {"holders": []})
        if not ended:
            return False, "no session was holding a cad-db lock"
        sup.changes.add("cad-db", "lock_release", actor, sessions=ended)
        return True, f"ended {len(ended)} session(s) holding cad-db: {', '.join(str(s) for s in ended)}"

    def _quarantine(self, sup, params, actor):
        item = _whole_param(params.get("item"))
        if item is None:
            return False, "item must be a whole number"
        conn = cadstore.connect(sup.data_dir, busy_timeout_ms=2000)
        try:
            changed = conn.execute("UPDATE field_queue SET status = 'quarantined', updated_t = ? "
                                   "WHERE id = ? AND status = 'pending'", (time.time(), item)).rowcount
        finally:
            conn.close()
        if not changed:
            return False, f"item {item} is not waiting in unit-sync's queue"
        sup.changes.add("unit-sync", "quarantine", actor, item=item)
        return True, f"field report {item} set aside; unit-sync will skip it"

    # ----- ground truth for the checker and the harness (privileged) -----

    def snapshot(self, sup):
        d = sup.data_dir
        out = {"t": time.time(), "processes": {name: sup.is_up(name) for name in sup.procs},
               "releases": sup.releases.load()["current"],
               "config": {c["name"]: ConfigStore(d, c["name"]).load()["values"]
                          for c in self.components(sup.condition) if c.get("config") is not None},
               "links": sup.links, "routing": Routing(d).load(),
               "lock_holders": (read_json(cadstore.locks_path(d), {"holders": []}) or {}).get("holders") or [],
               "surge_helpers": live_entries(surge_registry_path(d), "helpers"), "data_dir": d}
        try:
            conn = cadstore.connect(d, busy_timeout_ms=2000, readonly=True)
            try:
                def grouped(sql, *args):
                    return {row[0]: row[1] for row in conn.execute(sql, args)}
                out["incidents"] = grouped("SELECT status, COUNT(*) FROM incidents WHERE test = 0 GROUP BY status")
                out["open_test_incidents"] = conn.execute(
                    f"SELECT COUNT(*) FROM incidents WHERE test = 1 AND status IN "
                    f"({cadstore.placeholders(cadstore.OPEN_INCIDENT)})", cadstore.OPEN_INCIDENT).fetchone()[0]
                out["field_queue"] = grouped("SELECT status, COUNT(*) FROM field_queue GROUP BY status")
                out["units"] = grouped("SELECT status, COUNT(*) FROM units WHERE test = 0 GROUP BY status")
                out["open_assignments"] = grouped(
                    f"SELECT status, COUNT(*) FROM assignments WHERE status IN "
                    f"({cadstore.placeholders(cadstore.OPEN_ASSIGNMENT)}) GROUP BY status", *cadstore.OPEN_ASSIGNMENT)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            out["error"] = f"cad-db cannot be read ({type(exc).__name__})"
        return out


# ----- helpers for the probe -----

def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _whole_param(value):
    """A parameter as a whole number, or None. Accepts 17, 17.0 and "17"; refuses true, 17.5 and words."""
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, float) and value != number:
        return None
    return number


def _near(location, xy, tolerance_km):
    try:
        return math.hypot(float(location["x"]) - xy[0], float(location["y"]) - xy[1]) <= tolerance_km
    except (TypeError, KeyError, ValueError):
        return False


def _error_detail(exc):
    if exc.kind == "http":
        body = exc.body if isinstance(exc.body, dict) else {}
        return f"{exc.status} {body.get('error', '')}".strip()
    return exc.kind


def _poll(check, timeout_s, interval_s=0.1):
    deadline = time.time() + timeout_s
    while True:
        value = check()
        if value or time.time() >= deadline:
            return value or None
        time.sleep(interval_s)


def _read(data_dir, sql, args):
    try:
        conn = cadstore.connect(data_dir, busy_timeout_ms=500, readonly=True)
        try:
            return conn.execute(sql, args).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _test_incident_recorded(data_dir, incident_id, call_id):
    try:
        conn = cadstore.connect(data_dir, busy_timeout_ms=500, readonly=True)
        try:
            incident = conn.execute("SELECT status, test, priority, x, y FROM incidents WHERE id = ?",
                                    (incident_id,)).fetchone()
            call = conn.execute("SELECT incident_id FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, f"cad-db cannot be read ({type(exc).__name__})"
    if incident is None or call is None:
        return False, "incident not recorded"
    same = (incident["test"] == 1 and incident["status"] in cadstore.OPEN_INCIDENT
            and call["incident_id"] == incident_id and incident["priority"] == area.NATURES["test"]["priority"]
            and _near({"x": incident["x"], "y": incident["y"]}, area.TEST_XY, 0.05))
    return (True, "incident recorded") if same else (False, "incident differs from the call")


def _test_assignment(data_dir, incident_id):
    row = _read(data_dir, "SELECT id FROM assignments WHERE incident_id = ? AND unit_id = ? ORDER BY id DESC LIMIT 1",
                (incident_id, area.TEST_UNIT))
    return row[0] if row else None


def _alert_delivered(path, offset, assignment_id):
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        try:
            alert = json.loads(line)
        except ValueError:   # a line still being written
            continue
        if isinstance(alert, dict) and alert.get("assignment_id") == assignment_id:
            return True
    return False


def _test_unit_shows(data_dir, incident_id):
    row = _read(data_dir, "SELECT status, incident_id FROM units WHERE id = ?", (area.TEST_UNIT,))
    return bool(row) and row[0] == "enroute" and row[1] == incident_id
