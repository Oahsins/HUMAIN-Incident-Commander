"""The dispatcher (2.1) and unit-sync (4.0) workers, one cycle at a time against a fresh cad-db in a temporary
folder. No processes and no network: alerting is a stand-in that records each alert."""

import inspect
import itertools
import json
import os
import time

import pytest

from ic.kit import net
from ic.kit.store import ConfigStore, Routing
from targets.dispatch import area, cadstore, fieldmsg, spec, worker
from targets.dispatch.releases.dispatcher import v2_1 as dispatcher
from targets.dispatch.releases.dispatcher import v2_1_1 as dispatcher_label
from targets.dispatch.releases.unit_sync import v4_0 as unit_sync
from targets.dispatch.releases.unit_sync import v4_0_1 as unit_sync_label

PORTS = {"dispatcher->alerting": 9607, "alerting-backup": 9604, "alerting": 9603}
MEDICS = [u for u in area.UNIT_IDS if u.startswith("M")]
CLOCK = itertools.count(1)


def later():
    """A report time after every earlier one in this test run, as a crew's terminal stamps them."""
    return time.time() + next(CLOCK) * 0.001


@pytest.fixture()
def data_dir(tmp_path):
    d = str(tmp_path)
    cadstore.create(d)
    for c in spec.COMPONENTS:
        if c["config"] is not None:
            ConfigStore(d, c["name"]).init(c["config"])
    os.makedirs(os.path.join(d, "logs"), exist_ok=True)
    return d


class Alerting:
    """Stands in for both alerting sides: records each alert, and fails while `down`."""

    def __init__(self, release):
        self.release, self.sent, self.down = release, [], False

    def __call__(self, dep, method, url, payload=None, timeout=2.0):
        assert not self.release.db().in_transaction, "a cad-db transaction was open during a call to alerting"
        self.sent.append({"dep": dep, "method": method, "url": url, "body": payload, "timeout": timeout})
        if self.down:
            raise net.CallError("timeout", detail="no answer")
        return 200, {"delivered": True}


class Harness:
    """One worker release on the data folder, with its own cad-db connection and default settings."""

    def __init__(self, cls, data_dir, component, version):
        self.release = cls({"component": component, "version": version, "port": 0, "data_dir": data_dir,
                            "ports": dict(PORTS)})
        self.conn = self.release.db()
        self.settings, bad = self.release.settings()
        assert bad is None

    def cycle(self, **changes):
        return self.release.cycle(self.conn, dict(self.settings, **changes))

    def logs(self):
        path = os.path.join(self.release.data_dir, "logs", f"{self.release.component}.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


@pytest.fixture()
def dispatch(data_dir, monkeypatch):
    w = Harness(dispatcher.Release, data_dir, "dispatcher", "2.1")
    w.alerting = Alerting(w.release)
    monkeypatch.setattr(w.release, "call", w.alerting)
    yield w
    w.conn.close()


@pytest.fixture()
def sync(data_dir):
    w = Harness(unit_sync.Release, data_dir, "unit-sync", "4.0")
    yield w
    w.conn.close()


# ----- rows as cad and the crews' terminals write them -----

def add_incident(conn, nature="cardiac", xy=(15.0, 5.0), status="pending", test=None, seq=itertools.count(1)):
    n = next(seq)
    test = (1 if nature == "test" else 0) if test is None else test
    ani = area.test_number(n) if test else area.normal_number(n)
    now = time.time()
    return conn.execute(
        "INSERT INTO incidents (first_call_id, ani, nature, priority, unit_type, narrative, x, y, "
        "location_source, status, test, release, created_t, pending_since, updated_t) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ali', ?, ?, '3.4', ?, ?, ?)",
        (f"C-{n:08x}", ani, nature, area.NATURES[nature]["priority"], area.NATURES[nature]["unit_type"],
         area.NATURES[nature]["narratives"][0], xy[0], xy[1], status, test, now, now, now)).lastrowid


def add_assignment(conn, incident_id, unit, status, source="dispatcher", age_s=0.0):
    t = time.time() - age_s
    return conn.execute("INSERT INTO assignments (incident_id, unit_id, status, source, test, assigned_t, "
                        "next_alert_t) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (incident_id, unit, status, source, int(unit == area.TEST_UNIT), t,
                         t if status == "assigned" else None)).lastrowid


def report(conn, unit, status, incident_id=None, t=None, kind="status", payload=None):
    body = payload if payload is not None else json.dumps(
        fieldmsg.build(unit, kind, status, incident_id, later() if t is None else t))
    now = time.time()
    return conn.execute("INSERT INTO field_queue (unit_id, payload_json, status, attempts, created_t, updated_t) "
                        "VALUES (?, ?, 'pending', 0, ?, ?)", (unit, body, now, now)).lastrowid


def set_units(conn, units, status="onscene"):
    conn.executemany("UPDATE units SET status = ? WHERE id = ?", [(status, u) for u in units])


def row(conn, table, id_):
    found = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (id_,)).fetchone()
    return dict(found) if found else None


def assignments(conn, incident_id):
    return [dict(r) for r in conn.execute("SELECT * FROM assignments WHERE incident_id = ? ORDER BY id",
                                          (incident_id,))]


def unit_state(conn, unit):
    found = conn.execute("SELECT status, incident_id FROM units WHERE id = ?", (unit,)).fetchone()
    return found["status"], found["incident_id"]


def committed(conn, incident_id):
    """The unit the incident's newest open assignment names, or None."""
    found = conn.execute(f"SELECT unit_id FROM assignments WHERE incident_id = ? AND status IN "
                         f"({cadstore.placeholders(cadstore.OPEN_ASSIGNMENT)}) ORDER BY id DESC LIMIT 1",
                         (incident_id, *cadstore.OPEN_ASSIGNMENT)).fetchone()
    return found["unit_id"] if found else None


# ----- the releases as a later release sees them -----

def test_settings_follow_the_spec_and_the_defaults_are_usable():
    for name, cls in (("dispatcher", dispatcher.Release), ("unit-sync", unit_sync.Release)):
        defaults = next(c["config"] for c in spec.COMPONENTS if c["name"] == name)
        assert set(cls.SETTINGS) == set(defaults)
        assert worker.check_settings(defaults, cls.SETTINGS) == (defaults, None)
        for key in cls.SETTINGS:
            assert worker.check_settings({**defaults, key: True}, cls.SETTINGS) == (None, key)
    assert dispatcher.Release.SETTINGS["recommend_by"] == ("enum", ("closest", "station_order"))


def test_the_frozen_methods_exist_and_the_build_labels_change_nothing():
    for cls, names in ((dispatcher.Release, ("cycle", "retry_alerts", "expire_unacknowledged", "pending_batch",
                                             "free_units", "recommend", "assign", "send_alert")),
                       (unit_sync.Release, ("cycle", "take_batch", "parse", "in_order", "apply", "apply_unit",
                                            "apply_assignment"))):
        for name in names:
            assert callable(getattr(cls, name)), name
    for label, base in ((dispatcher_label.Release, dispatcher.Release),
                        (unit_sync_label.Release, unit_sync.Release)):
        assert label.__bases__ == (base,) and label.__doc__ == "build label"
        assert [n for n in vars(label) if not n.startswith("__")] == []
        assert inspect.getmodule(label).__doc__


# ----- dispatcher: what it sends and to whom -----

def test_pending_incidents_are_dispatched_by_priority_then_age(dispatch):
    conn = dispatch.conn
    alarm, fall_1, cardiac, fall_2 = (add_incident(conn, n) for n in ("alarm", "fall", "cardiac", "fall"))
    order = []
    for _ in range(4):
        assert dispatch.cycle(batch_size=1) == 1
        order.append(next(i for i in (alarm, fall_1, cardiac, fall_2)
                          if row(conn, "incidents", i)["status"] == "dispatched" and i not in order))
    assert order == [cardiac, fall_1, fall_2, alarm]


def test_the_closest_free_unit_of_the_preferred_type_goes(dispatch):
    conn = dispatch.conn
    near_s2 = (15.0, 5.0)
    cardiac, fire = add_incident(conn, "cardiac", near_s2), add_incident(conn, "structure_fire", near_s2)
    dispatch.cycle()
    assert committed(conn, cardiac) == "M3" and committed(conn, fire) == "E3"   # S2; M3/M4 tie by unit id
    set_units(conn, ["M4"])
    other = add_incident(conn, "breathing", near_s2)   # S2's engine E4 is closer, but a medic is free at S3
    dispatch.cycle()
    assert committed(conn, other) == "M5"


def test_ties_between_stations_are_broken_by_unit_id(dispatch):
    between = add_incident(dispatch.conn, "fall", (10.0, 4.0))   # 6 km from both S1 and S2
    dispatch.cycle()
    assert committed(dispatch.conn, between) == "M1"


def test_any_type_goes_when_no_unit_of_the_preferred_type_is_free(dispatch):
    set_units(dispatch.conn, MEDICS)
    cardiac = add_incident(dispatch.conn, "cardiac", (15.0, 5.0))
    dispatch.cycle()
    assert committed(dispatch.conn, cardiac) == "E3"


def test_station_order_takes_the_first_free_unit_in_roster_order(dispatch):
    conn = dispatch.conn
    medical, fire = add_incident(conn, "fall", (16.0, 16.0)), add_incident(conn, "alarm", (16.0, 16.0))
    dispatch.cycle(recommend_by="station_order")
    assert committed(conn, medical) == "M1" and committed(conn, fire) == "E1"
    set_units(conn, ["M2", "E1", "E2"])
    medical = add_incident(conn, "fall", (16.0, 16.0))
    dispatch.cycle(recommend_by="station_order")
    assert committed(conn, medical) == "M3"


def test_a_test_incident_gets_only_test_1_and_a_real_one_never_does(dispatch):
    conn = dispatch.conn
    probe = add_incident(conn, "test", area.TEST_XY)
    dispatch.cycle()
    assert committed(conn, probe) == area.TEST_UNIT
    assert [a["test"] for a in assignments(conn, probe)] == [1]
    second = add_incident(conn, "test", area.TEST_XY)   # TEST-1 is committed: the test call waits
    dispatch.cycle()
    assert committed(conn, second) is None and row(conn, "incidents", second)["status"] == "pending"
    set_units(conn, area.UNIT_IDS)
    conn.execute("UPDATE assignments SET status = 'cleared', closed_t = ?", (time.time(),))
    real = add_incident(conn, "cardiac")
    dispatch.cycle()
    assert committed(conn, real) is None and committed(conn, second) == area.TEST_UNIT


def test_a_test_incident_is_not_held_up_by_a_backlog_of_real_ones(dispatch):
    conn = dispatch.conn
    set_units(conn, area.UNIT_IDS)
    for _ in range(30):
        add_incident(conn, "cardiac")
    probe = add_incident(conn, "test", area.TEST_XY)
    dispatch.cycle()
    assert committed(conn, probe) == area.TEST_UNIT


def test_an_incident_no_free_unit_can_serve_does_not_use_up_the_batch(dispatch):
    conn = dispatch.conn
    set_units(conn, [u for u in area.UNIT_IDS if u != "M3"])
    refused = add_incident(conn, "cardiac")
    add_assignment(conn, refused, "M3", "no_ack")
    fall = add_incident(conn, "fall")
    assert dispatch.cycle(batch_size=1) == 1
    assert committed(conn, fall) == "M3" and committed(conn, refused) is None
    assert row(conn, "incidents", refused)["status"] == "pending"


def test_a_unit_whose_record_still_shows_available_is_not_committed_twice(dispatch):
    conn = dispatch.conn
    set_units(conn, [u for u in area.UNIT_IDS if u != "M3"])
    first, second = add_incident(conn, "cardiac"), add_incident(conn, "cardiac")
    dispatch.cycle()
    dispatch.cycle()
    assert committed(conn, first) == "M3" and committed(conn, second) is None
    conn.execute("UPDATE assignments SET status = 'acked'")   # the crew acknowledged; its record still lags
    dispatch.cycle()
    assert committed(conn, second) is None
    unit = {"id": "M3", "type": "medic", "station": "S2"}
    assert dispatch.release.assign(conn, row(conn, "incidents", second), unit) is None   # the commit re-checks
    assert dispatch.release.assign(conn, row(conn, "incidents", first), dict(unit, id="M4")) is None
    assert not conn.in_transaction and len(assignments(conn, second)) == 0


def test_an_unacknowledged_unit_times_out_and_is_never_offered_again(dispatch):
    conn = dispatch.conn
    cardiac = add_incident(conn, "cardiac", (15.0, 5.0))
    dispatch.cycle()
    sent = [committed(conn, cardiac)]
    for _ in range(3):
        conn.execute("UPDATE assignments SET assigned_t = assigned_t - 3 WHERE incident_id = ?", (cardiac,))
        dispatch.cycle()
        sent.append(committed(conn, cardiac))
    assert sent == ["M3", "M4", "M5", "M6"]
    rows = assignments(conn, cardiac)
    assert [a["status"] for a in rows] == ["no_ack", "no_ack", "no_ack", "alerted"]
    assert all(a["closed_t"] is not None for a in rows[:3]) and rows[3]["closed_t"] is None
    incident = row(conn, "incidents", cardiac)
    assert incident["status"] == "dispatched" and incident["attempts"] == 3 and incident["pending_since"] > 0
    free = {u["id"] for u in dispatch.release.free_units(conn, incident)}
    assert not free & {"M3", "M4", "M5", "M6"}
    warned = [r for r in dispatch.logs() if r["event"] == "no_acknowledgement"]
    assert [(r["unit"], r["incident_id"], r["level"]) for r in warned] == [(u, cardiac, "WARN") for u in sent[:3]]


def test_the_timer_leaves_an_incident_a_crew_is_on(dispatch):
    conn = dispatch.conn
    incident = add_incident(conn, "fall", status="enroute")
    add_assignment(conn, incident, "M7", "acked", source="field")
    late = add_assignment(conn, incident, "M3", "alerted", age_s=5.0)
    dispatch.cycle()
    assert row(conn, "assignments", late)["status"] == "no_ack"
    assert row(conn, "incidents", incident)["status"] == "enroute"


def test_an_incident_its_crew_has_cleared_closes_when_the_last_unit_sent_times_out(dispatch, sync):
    conn = dispatch.conn
    incident = add_incident(conn, "cardiac", (15.0, 5.0))
    dispatch.cycle()
    conn.execute("UPDATE assignments SET assigned_t = assigned_t - 3 WHERE incident_id = ?", (incident,))
    dispatch.cycle()   # M3 did not acknowledge in time, so M4 is sent
    for status in ("enroute", "onscene", "available"):   # M3's crew took the call after all, and finished it
        report(conn, "M3", status, incident if status != "available" else None)
        sync.cycle()
    assert row(conn, "incidents", incident)["status"] == "onscene"   # M4's alert is still open
    conn.execute("UPDATE assignments SET assigned_t = assigned_t - 3 WHERE status = 'alerted'")
    dispatch.cycle()
    dispatch.cycle()
    closed = row(conn, "incidents", incident)
    assert (closed["status"], closed["close_reason"]) == ("closed", "completed") and closed["closed_t"]
    assert [(a["unit_id"], a["source"], a["status"]) for a in assignments(conn, incident)] == [
        ("M3", "dispatcher", "no_ack"), ("M4", "dispatcher", "no_ack"), ("M3", "field", "cleared")]


def test_an_alert_that_is_not_delivered_is_sent_again_after_0_3_s(dispatch):
    conn = dispatch.conn
    dispatch.alerting.down = True
    cardiac = add_incident(conn, "cardiac", (13.5791357, 6.2468024))
    dispatch.cycle()
    (first,) = assignments(conn, cardiac)
    assert first["status"] == "assigned" and first["next_alert_t"] - time.time() == pytest.approx(0.3, abs=0.1)
    dispatch.cycle()
    assert len(dispatch.alerting.sent) == 1   # not due yet
    dispatch.alerting.down = False
    conn.execute("UPDATE assignments SET next_alert_t = next_alert_t - 1")
    dispatch.cycle()
    (first,) = assignments(conn, cardiac)
    assert first["status"] == "alerted" and first["alerted_t"] is not None and first["next_alert_t"] is None
    bodies = [s["body"] for s in dispatch.alerting.sent]
    assert len(bodies) == 2 and bodies[0] == bodies[1] == {
        "assignment_id": first["id"], "incident_id": cardiac, "unit": "M3", "station": "S2", "priority": 1,
        "nature": "cardiac", "x": 13.5791357, "y": 6.2468024}
    assert all(s["timeout"] == 1.0 and s["method"] == "POST" for s in dispatch.alerting.sent)
    failed = [r for r in dispatch.logs() if r["event"] == "alert_failed"]
    assert failed and failed[0]["kind"] == "timeout" and failed[0]["assignment_id"] == first["id"]


def test_the_alert_goes_to_the_primary_through_the_link_by_default(dispatch):
    add_incident(dispatch.conn, "cardiac")
    dispatch.cycle()
    assert [(s["dep"], s["url"]) for s in dispatch.alerting.sent] == [("alerting", "http://127.0.0.1:9607/alert")]


def test_after_a_failover_the_alert_goes_to_the_backup_directly(data_dir, monkeypatch):
    Routing(data_dir).set("alerting", "standby")
    w = Harness(dispatcher.Release, data_dir, "dispatcher", "2.1")
    alerting = Alerting(w.release)
    monkeypatch.setattr(w.release, "call", alerting)
    incident = add_incident(w.conn, "cardiac")
    w.cycle()
    assert [(s["dep"], s["url"]) for s in alerting.sent] == [("alerting-backup", "http://127.0.0.1:9604/alert")]
    assert row(w.conn, "assignments", assignments(w.conn, incident)[0]["id"])["status"] == "alerted"
    w.conn.close()


def test_an_incident_it_cannot_read_is_skipped_and_named_never_set_aside(dispatch):
    conn = dispatch.conn
    wordy, lost, fine = add_incident(conn, "cardiac"), add_incident(conn, "fall"), add_incident(conn, "alarm")
    conn.execute("UPDATE incidents SET priority = 'urgent' WHERE id = ?", (wordy,))
    conn.execute("UPDATE incidents SET x = 'somewhere' WHERE id = ?", (lost,))
    dispatch.cycle()
    dispatch.cycle()
    assert committed(conn, fine) == "E3"
    assert [row(conn, "incidents", i)["status"] for i in (wordy, lost)] == ["pending", "pending"]
    named = {(r["incident_id"], r["field"]) for r in dispatch.logs() if r["event"] == "incident_unreadable"}
    assert named == {(wordy, "priority"), (lost, "location")}


def test_the_dispatcher_logs_ids_never_what_the_caller_said_or_where(dispatch):
    conn = dispatch.conn
    dispatch.alerting.down = True
    incident = add_incident(conn, "breathing", (13.5791357, 6.2468024))
    dispatch.cycle()
    conn.execute("UPDATE assignments SET assigned_t = assigned_t - 3")
    dispatch.cycle()
    caller = row(conn, "incidents", incident)
    path = os.path.join(dispatch.release.data_dir, "logs", "dispatcher.jsonl")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "unit_assigned" in text and "alert_failed" in text and "no_acknowledgement" in text
    for value in (caller["narrative"], caller["ani"], "13.579", "6.2468"):
        assert value not in text


def test_one_unit_serves_two_incidents_in_a_row_without_overlap(dispatch, sync):
    conn = dispatch.conn
    first = add_incident(conn, "cardiac", (15.0, 5.0))
    dispatch.cycle()
    for status in ("enroute", "onscene", "available"):
        report(conn, "M3", status, first if status != "available" else None)
        sync.cycle()
    assert row(conn, "incidents", first)["status"] == "closed"
    second = add_incident(conn, "fall", (15.0, 5.0))
    dispatch.cycle()
    old, new = assignments(conn, first)[0], assignments(conn, second)[0]
    assert (old["unit_id"], new["unit_id"]) == ("M3", "M3")
    assert old["status"] == "cleared" and old["closed_t"] <= new["assigned_t"]


# ----- unit-sync: which reports it applies -----

def test_the_newest_report_of_each_unit_wins(sync):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="dispatched")
    older = [report(conn, "M3", "enroute", incident), report(conn, "M3", "enroute", incident, kind="heartbeat")]
    newest = report(conn, "M3", "onscene", incident)
    other = report(conn, "E5", "available", kind="heartbeat")
    assert sync.cycle() == 4
    assert [row(conn, "field_queue", i)["status"] for i in (*older, newest, other)] == \
        ["skipped", "skipped", "applied", "applied"]
    assert unit_state(conn, "M3") == ("onscene", incident)
    history = conn.execute("SELECT status FROM unit_history WHERE unit_id = 'M3' ORDER BY id").fetchall()
    assert [h["status"] for h in history] == ["available", "onscene"]   # the seed, then one write


def test_a_newer_report_beyond_the_batch_still_supersedes(sync):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="dispatched")
    ids = [report(conn, "M3", s, incident) for s in ("enroute", "onscene")]
    ids.append(report(conn, "M3", "available"))
    sync.cycle(batch_size=2)
    assert [row(conn, "field_queue", i)["status"] for i in ids] == ["skipped", "skipped", "pending"]
    assert unit_state(conn, "M3") == ("available", None)
    sync.cycle(batch_size=2)
    assert row(conn, "field_queue", ids[2])["status"] == "applied"


def test_a_report_older_than_max_message_age_is_skipped(sync):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="dispatched")
    old = report(conn, "M3", "enroute", incident, t=time.time() - 11.0)
    sync.cycle()
    assert row(conn, "field_queue", old)["status"] == "skipped"
    assert unit_state(conn, "M3") == ("available", None) and assignments(conn, incident) == []
    assert any(r["event"] == "skipped" and r["reason"] == "too old" and r["level"] == "WARN" for r in sync.logs())


def test_a_report_not_newer_than_the_last_applied_is_skipped_until_a_restart(sync, data_dir):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="dispatched")
    ahead = time.time() + 600.0
    report(conn, "M3", "enroute", incident, t=ahead)   # a terminal clock far ahead: the record freezes
    sync.cycle()
    behind = report(conn, "M3", "onscene", incident)
    sync.cycle()
    assert row(conn, "field_queue", behind)["status"] == "skipped"
    assert unit_state(conn, "M3") == ("enroute", incident)
    assert conn.execute("SELECT status_t FROM units WHERE id = 'M3'").fetchone()[0] == ahead
    restarted = Harness(unit_sync.Release, data_dir, "unit-sync", "4.0")   # a restart forgets the memory
    now = report(conn, "M3", "onscene", incident)
    restarted.cycle()
    assert row(conn, "field_queue", now)["status"] == "applied" and unit_state(conn, "M3") == ("onscene", incident)
    restarted.conn.close()


def test_a_report_set_aside_meanwhile_is_left_alone(sync):
    conn = sync.conn
    item = report(conn, "M3", "outofservice")
    (taken,), latest = sync.release.take_batch(conn, sync.settings)
    conn.execute("UPDATE field_queue SET status = 'quarantined' WHERE id = ?", (item,))
    conn.execute("BEGIN IMMEDIATE")
    assert sync.release.apply(conn, taken, sync.release.parse(taken), sync.settings, latest) is None
    conn.execute("COMMIT")
    assert row(conn, "field_queue", item)["status"] == "quarantined" and unit_state(conn, "M3")[0] == "available"


# ----- unit-sync: what applying a report does -----

def test_en_route_acknowledges_the_assignment_and_on_scene_moves_the_incident_on(sync):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="dispatched")
    sent = add_assignment(conn, incident, "M3", "alerted")
    report(conn, "M3", "enroute", incident)
    sync.cycle()
    acked = row(conn, "assignments", sent)
    assert acked["status"] == "acked" and acked["acked_t"] is not None
    assert row(conn, "incidents", incident)["status"] == "enroute"
    report(conn, "M3", "onscene", incident)
    sync.cycle()
    assert row(conn, "assignments", sent)["status"] == "onscene" and row(conn, "assignments", sent)["acked_t"]
    assert row(conn, "incidents", incident)["status"] == "onscene"
    assert unit_state(conn, "M3") == ("onscene", incident)
    applied = [r for r in sync.logs() if r["event"] == "status_applied"]
    assert [(r["unit"], r["status"], r["incident_id"]) for r in applied] == \
        [("M3", "enroute", incident), ("M3", "onscene", incident)]


def test_an_assignment_is_recorded_when_a_crew_is_on_an_incident_without_one(sync):
    conn = sync.conn
    incident = add_incident(conn, "fall", status="pending")
    add_assignment(conn, incident, "M4", "no_ack")
    report(conn, "M4", "enroute", incident)
    sync.cycle()
    rows = assignments(conn, incident)
    assert [(a["status"], a["source"], a["unit_id"]) for a in rows] == [("no_ack", "dispatcher", "M4"),
                                                                       ("acked", "field", "M4")]
    assert rows[1]["acked_t"] is not None and rows[1]["test"] == 0
    assert row(conn, "incidents", incident)["status"] == "enroute"


def test_assignments_and_incidents_never_move_down(sync):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="onscene")
    there = add_assignment(conn, incident, "M3", "onscene")
    report(conn, "M3", "enroute", incident)
    sync.cycle()
    assert row(conn, "assignments", there)["status"] == "onscene"
    assert row(conn, "incidents", incident)["status"] == "onscene"


def test_available_clears_the_work_taken_on_and_leaves_a_new_dispatch_alone(sync):
    conn = sync.conn
    done = add_incident(conn, "cardiac", status="onscene")
    worked = add_assignment(conn, done, "M3", "onscene")
    new = add_incident(conn, "fall", status="dispatched")
    on_its_way = add_assignment(conn, new, "M3", "alerted")
    report(conn, "M3", "available", kind="heartbeat")
    sync.cycle()
    cleared, closed = row(conn, "assignments", worked), row(conn, "incidents", done)
    assert cleared["status"] == "cleared" and cleared["closed_t"] is not None
    assert (closed["status"], closed["close_reason"]) == ("closed", "completed") and closed["closed_t"] is not None
    assert row(conn, "assignments", on_its_way)["status"] == "alerted"
    assert row(conn, "incidents", new)["status"] == "dispatched"


def test_an_incident_another_unit_is_still_on_stays_open(sync):
    conn = sync.conn
    incident = add_incident(conn, "collision", status="onscene")
    add_assignment(conn, incident, "M3", "onscene")
    add_assignment(conn, incident, "E5", "acked", source="field")
    report(conn, "M3", "available")
    sync.cycle()
    assert row(conn, "incidents", incident)["status"] == "onscene"
    report(conn, "E5", "available")
    sync.cycle()
    assert row(conn, "incidents", incident)["status"] == "closed"


def test_new_work_clears_the_old_and_closes_it(sync):
    conn = sync.conn
    old = add_incident(conn, "alarm", status="onscene")
    finished = add_assignment(conn, old, "E1", "onscene")
    new = add_incident(conn, "vehicle_fire", status="dispatched")
    add_assignment(conn, new, "E1", "alerted")
    report(conn, "E1", "enroute", new)
    sync.cycle()
    assert row(conn, "assignments", finished)["status"] == "cleared"
    assert row(conn, "incidents", old)["status"] == "closed"
    assert row(conn, "incidents", new)["status"] == "enroute"


def test_a_closed_incident_stays_closed(sync):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="closed")
    report(conn, "M3", "enroute", incident)
    sync.cycle()
    assert row(conn, "incidents", incident)["status"] == "closed"
    assert unit_state(conn, "M3") == ("enroute", incident)
    warned = [r for r in sync.logs() if r["event"] == "unit_on_closed_incident"]
    assert warned and warned[0]["level"] == "WARN" and warned[0]["incident_id"] == incident


def test_an_unknown_incident_changes_the_unit_record_only(sync):
    conn = sync.conn
    old = add_incident(conn, "cardiac", status="onscene")
    worked = add_assignment(conn, old, "M3", "onscene")
    report(conn, "M3", "enroute", 2 ** 63 - 1)
    sync.cycle()
    assert unit_state(conn, "M3") == ("enroute", 2 ** 63 - 1)
    assert row(conn, "assignments", worked)["status"] == "onscene"
    assert row(conn, "incidents", old)["status"] == "onscene"
    assert conn.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 1
    warned = [r for r in sync.logs() if r["event"] == "unit_on_unknown_incident"]
    assert warned and warned[0]["level"] == "WARN" and warned[0]["unit"] == "M3"


def test_out_of_service_changes_the_unit_record_only(sync):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="onscene")
    worked = add_assignment(conn, incident, "M3", "onscene")
    report(conn, "M3", "outofservice")
    sync.cycle()
    assert unit_state(conn, "M3") == ("outofservice", None)
    assert row(conn, "assignments", worked)["status"] == "onscene"
    assert row(conn, "incidents", incident)["status"] == "onscene"


def test_a_heartbeat_with_no_change_moves_only_the_report_times(sync):
    conn = sync.conn
    before = row(conn, "units", "E2")
    t = later()
    report(conn, "E2", "available", t=t, kind="heartbeat")
    sync.cycle()
    after = row(conn, "units", "E2")
    assert after["status_since"] == before["status_since"] and after["status_t"] == t
    assert after["applied_t"] is not None and after["source"] == "field"
    assert conn.execute("SELECT COUNT(*) FROM unit_history WHERE unit_id = 'E2'").fetchone()[0] == 1
    assert not [r for r in sync.logs() if r["event"] == "status_applied"]


# ----- unit-sync: a report it cannot read -----

class Stopped(Exception):
    """Raised in place of the process exit, so a test can look at what was left behind."""


def stop_instead_of_exiting(monkeypatch, release):
    def crash(exc, **fields):
        raise Stopped(exc, fields)
    monkeypatch.setattr(release, "crash", crash)


def test_an_unreadable_report_stops_unit_sync_after_the_ones_before_it(sync, data_dir, monkeypatch):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="dispatched")
    before = [report(conn, "M3", "enroute", incident), report(conn, "E7", "outofservice")]
    bad = report(conn, "M5", "enroute", payload=json.dumps(
        {"unit": "M5", "kind": "status", "status": "ZZMARK", "incident_id": incident, "t": later()}))
    after = report(conn, "M5", "available")
    stop_instead_of_exiting(monkeypatch, sync.release)
    with pytest.raises(Stopped) as stopped:
        sync.cycle()
    exc, fields = stopped.value.args
    assert fields == {"item_id": bad}
    assert str(exc) == "status: not a known unit status" and "ZZMARK" not in str(exc)
    assert [row(conn, "field_queue", i)["status"] for i in (*before, bad, after)] == \
        ["applied", "applied", "pending", "pending"]
    assert unit_state(conn, "M3") == ("enroute", incident) and unit_state(conn, "M5") == ("available", None)
    assert row(conn, "field_queue", bad)["attempts"] == 1
    head = cadstore.field_queue_state(conn, time.time(), 10.0)["head_item"]
    assert (head["id"], head["attempts"]) == (bad, 1)
    restarted = Harness(unit_sync.Release, data_dir, "unit-sync", "4.0")   # it stops on the same report again
    stop_instead_of_exiting(monkeypatch, restarted.release)
    with pytest.raises(Stopped):
        restarted.cycle()
    assert row(conn, "field_queue", bad)["attempts"] == 2
    conn.execute("UPDATE field_queue SET status = 'quarantined' WHERE id = ?", (bad,))   # set aside
    restarted.cycle()
    assert row(conn, "field_queue", after)["status"] == "applied"
    restarted.conn.close()


def test_an_unreadable_report_at_the_head_stops_unit_sync_before_any_write(sync, monkeypatch):
    conn = sync.conn
    bad = report(conn, "M1", "available", payload="{not json")
    behind = report(conn, "M1", "outofservice")
    stop_instead_of_exiting(monkeypatch, sync.release)
    with pytest.raises(Stopped):
        sync.cycle()
    left = [row(conn, "field_queue", i) for i in (bad, behind)]
    assert [(r["status"], r["attempts"]) for r in left] == [("pending", 1), ("pending", 0)]
    assert unit_state(conn, "M1") == ("available", None)


def test_every_readable_report_applies_without_raising(sync):
    conn = sync.conn
    incidents = [add_incident(conn, "cardiac", status=s)
                 for s in ("pending", "dispatched", "enroute", "onscene", "closed", "cancelled")]
    incidents.append(add_incident(conn, "test", area.TEST_XY, status="dispatched"))
    unknown = [10 ** 9, 2 ** 63 - 1]
    for n, unit in enumerate(sorted(area.ROSTER_IDS)):
        add_assignment(conn, incidents[n % len(incidents)], unit, cadstore.OPEN_ASSIGNMENT[n % 4])
    combos = [(s, None) for s in ("available", "outofservice")] + \
             [(s, i) for s in ("enroute", "onscene") for i in incidents + unknown]
    rel, settings = sync.release, sync.settings
    applied = 0
    for when in ("old", "now", "future"):
        for unit, kind, (status, incident_id) in itertools.product(sorted(area.ROSTER_IDS), fieldmsg.KINDS,
                                                                   combos):
            t = {"old": time.time() - 3600.0, "now": later(), "future": later() + 10 ** 6}[when]
            payload = json.dumps(fieldmsg.build(unit, kind, status, incident_id, t))
            assert not fieldmsg.unreadable(payload)
            item = {"id": report(conn, unit, status, payload=payload), "payload_json": payload}
            conn.execute("BEGIN IMMEDIATE")
            applied += rel.apply(conn, item, rel.parse(item), settings, {}) == "applied"
            conn.execute("COMMIT")
    assert applied > 0 and not conn.in_transaction
    for (status, incident_id), t in itertools.product(combos, (time.time() - 3600.0, later(), later() + 10 ** 6)):
        for unit in sorted(area.ROSTER_IDS):   # and the same reports through whole cycles, in batches
            report(conn, unit, status, payload=json.dumps(fieldmsg.build(unit, "status", status, incident_id, t)))
    restarted = Harness(unit_sync.Release, sync.release.data_dir, "unit-sync", "4.0")
    while conn.execute("SELECT COUNT(*) FROM field_queue WHERE status = 'pending'").fetchone()[0]:
        assert restarted.cycle() > 0
    restarted.conn.close()


def test_unit_sync_logs_ids_never_report_values(sync):
    conn = sync.conn
    incident = add_incident(conn, "cardiac", status="dispatched")
    report(conn, "M3", "enroute", incident, t=later() + 0.123456789)
    report(conn, "M4", "enroute", 10 ** 9)
    report(conn, "M6", "available", t=time.time() - 3600.123456789)
    sync.cycle()
    path = os.path.join(sync.release.data_dir, "logs", "unit-sync.jsonl")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "status_applied" in text and "unit_on_unknown_incident" in text and "too old" in text
    assert "123456789" not in text and "payload" not in text
