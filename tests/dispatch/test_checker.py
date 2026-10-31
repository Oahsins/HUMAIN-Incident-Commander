"""The dispatch checker's rules on invented data (docs/DISPATCH.md, The checker): a fresh cad-db in a temporary
folder, hand-written callers' and crews' lines, and rows written through cad-db's own triggers. cad-db stamps the
triggers' evidence rows with the real clock, so the tests move them to the times they need, and fix the clock the
checker reads. No running centre and no network."""

import ast
import inspect
import itertools
import json
import os
import sys
import time

import pytest

from ic.kit.conformance import check_verdict
from ic.kit.store import read_json, write_json
from targets.dispatch import area, cadstore, checker, fieldmsg
from targets.dispatch.control import paths_for

SPARE = ("M9", "M10", "E9", "E10")      # units the healthy traffic leaves free for each test's own story
ROTATION = tuple(u for u in area.UNIT_IDS if u not in SPARE)
BLOCKING = ("told_without_incident", "incidents_dropped", "unit_records_wrong", "duplicate_incidents",
            "incidents_double_sent", "units_double_committed", "incident_details_wrong", "test_alerts_to_crews",
            "wrongly_quarantined")
COUNTS = BLOCKING + ("harmful_quarantines", "calls_dropped", "incidents_waiting", "unreadable_set_aside",
                     "field_messages_waiting")
NOT_THEIRS = {"missing": 0, "test": 0, "other_emergency": 0, "closed_before_link": 0}


class Fake:
    """Stands in for Control: the checker needs only the data folder's paths."""

    def __init__(self, data_dir):
        self.data_dir = data_dir

    def paths(self):
        return paths_for(self.data_dir)


class World:
    """An invented centre: cad-db, the callers' and crews' lines, and the clock the checker reads.

    The clock stands 1,000 s after the real one, so the seed's unit_history rows (stamped by cad-db's real clock)
    lie well before every window. Writes stay in one transaction until the checker is asked."""

    def __init__(self, data_dir):
        self.dir = data_dir
        self.now = float(int(time.time()) + 1000)
        self.lo, self.hi = self.now - 30.0, self.now - 10.0     # the default window
        cadstore.create(data_dir)
        os.makedirs(os.path.join(data_dir, "logs"))
        self.db = cadstore.connect(data_dir)
        self.db.execute("BEGIN")
        self.lines, self.surge_lines = [], []
        self.numbers = itertools.count(1)
        self.rotation = itertools.cycle(ROTATION)
        for unit in area.UNIT_IDS:
            self.crew(unit, self.now - 300.0, "available", event="start")

    def close(self):
        self.db.execute("COMMIT")
        self.db.close()

    # ----- cad-db -----

    def evidence(self, sql, args, t):
        """Run a statement whose trigger writes incident_events rows, and move those rows to time t."""
        last = self.db.execute("SELECT COALESCE(MAX(id), 0) FROM incident_events").fetchone()[0]
        row_id = self.db.execute(sql, args).lastrowid
        self.db.execute("UPDATE incident_events SET t = ? WHERE id > ?", (t, last))
        return row_id

    def incident(self, t, call_id, ani, nature="cardiac", test=0, priority=None, x=None, y=None):
        """An incident created at t from call_id, as cad creates one: priority from the nature, place from ALI."""
        where = area.subscriber_location(ani)
        return self.evidence(
            "INSERT INTO incidents (first_call_id, ani, nature, priority, unit_type, narrative, x, y, "
            "location_source, status, test, created_t, pending_since, updated_t) "
            "VALUES (?, ?, ?, ?, ?, '', ?, ?, 'ali', 'pending', ?, ?, ?, ?)",
            (call_id, ani, nature, area.NATURES[nature]["priority"] if priority is None else priority,
             area.NATURES[nature]["unit_type"], where[0] if x is None else x, where[1] if y is None else y, test,
             t, t, t), t)

    def status(self, incident, status, t):
        self.evidence("UPDATE incidents SET status = ?, updated_t = ? WHERE id = ?", (status, t, incident), t)

    def delete(self, incident, t):
        self.evidence("DELETE FROM incidents WHERE id = ?", (incident,), t)

    def call_row(self, call_id, incident, ani, t, linked=0):
        self.db.execute("INSERT INTO calls (call_id, incident_id, ani, linked, test, t) VALUES (?, ?, ?, ?, ?, ?)",
                        (call_id, incident, ani, linked, int(area.is_test_number(ani)), t))

    def assignment(self, incident, unit, assigned_t, status="cleared", closed_t=None, test=0):
        return self.db.execute(
            "INSERT INTO assignments (incident_id, unit_id, status, source, test, assigned_t, alerted_t, "
            "closed_t) VALUES (?, ?, ?, 'dispatcher', ?, ?, ?, ?)",
            (incident, unit, status, test, assigned_t, assigned_t + 0.02, closed_t)).lastrowid

    def history(self, unit, t, status, incident=None):
        """A row of CAD's unit record history at t (the trigger's row, placed by hand)."""
        self.db.execute("INSERT INTO unit_history (unit_id, status, incident_id, t) VALUES (?, ?, ?, ?)",
                        (unit, status, incident, t))

    def report(self, payload, status, created_t, updated_t=None):
        """A row of the field-report queue."""
        return self.db.execute(
            "INSERT INTO field_queue (unit_id, payload_json, status, attempts, created_t, updated_t) "
            "VALUES (NULL, ?, ?, 1, ?, ?)",
            (payload, status, created_t, created_t if updated_t is None else updated_t)).lastrowid

    # ----- the users' lines -----

    def caller(self, start, source="normal", **fields):
        """A caller's line: by default a fresh emergency's first call, answered after 30 ms, told at +1.2 s."""
        n = next(self.numbers)
        line = {"who": "caller", "source": source, "kind": "first", "attempt": 1, "call_id": f"C-{n:08x}",
                "emergency_id": f"E-N-{n:06d}" if source == "normal" else f"E-S4242-{n:06d}",
                "ani": area.normal_number(n) if source == "normal" else area.surge_number(0, n),
                "nature": "cardiac", "t_start": start, "t_answer": start + 0.03, "answer_ms": 30.0,
                "location": "ali", "t_told": start + 1.2, "incident_id": None, "linked": False, "outcome": "told",
                "status": 200, "t_end": start + 1.2}
        line.update(fields)
        (self.surge_lines if source == "surge" else self.lines).append(line)
        return line

    def failed(self, start, outcome, answered=False, **fields):
        """A call that was never told: refused, cut off or not answered at the dial, or answered and then lost."""
        cut = {"t_told": None, "linked": None, "status": outcome}
        if not answered:
            cut.update(call_id=None, t_answer=None, answer_ms=None, location=None)
        return self.caller(start, outcome=outcome, **{**cut, **fields})

    def crew(self, unit, t, status, incident=None, event="status"):
        self.lines.append({"who": "crew", "event": event, "unit": unit, "status": status, "incident_id": incident,
                           "t": t})

    def alert(self, unit, t, incident, assignment=None, taken=True):
        self.lines.append({"who": "crew", "event": "alert", "unit": unit, "incident_id": incident,
                           "assignment_id": assignment, "via": "alerting", "t": t, "taken": taken})

    # ----- whole stories -----

    def entered(self, start, **fields):
        """A caller told help is on the way at +1.2 s, with the incident CAD created for the call at +1.15 s."""
        line = self.caller(start, **fields)
        incident = self.incident(start + 1.15, line["call_id"], line["ani"], line["nature"])
        self.call_row(line["call_id"], incident, line["ani"], start + 1.15)
        line["incident_id"] = incident
        return line, incident

    def respond(self, incident, unit, t):
        """The dispatcher commits unit at t; its crew is alerted at once, en route at +0.3 s, on scene at +1.1 s
        and available at +1.9 s; CAD's record follows each change 0.3 s later, and the incident closes then."""
        self.status(incident, "dispatched", t)
        assignment = self.assignment(incident, unit, t, "cleared", closed_t=t + 2.2)
        self.alert(unit, t + 0.05, incident, assignment)
        for offset, status, incident_id in ((0.3, "enroute", incident), (1.1, "onscene", incident),
                                            (1.9, "available", None)):
            self.crew(unit, t + offset, status, incident_id)
            self.history(unit, t + offset + 0.3, status, incident_id)
        self.status(incident, "enroute", t + 0.6)
        self.status(incident, "onscene", t + 1.4)
        self.status(incident, "closed", t + 2.2)

    def emergency(self, start, unit=None, **fields):
        """A healthy emergency: its first call is told at +1.2 s, and unit (the next in rotation unless given)
        is committed at +1.3 s and en route at +1.6 s."""
        line, incident = self.entered(start, **fields)
        self.respond(incident, unit or next(self.rotation), start + 1.3)
        return line

    def callback(self, first, start, link_t=None):
        """The same caller calls back, told at +0.28 s; CAD links the call to the first call's incident at link_t
        (+0.25 s unless given)."""
        line = self.caller(start, source=first["source"], emergency_id=first["emergency_id"], ani=first["ani"],
                           nature=first["nature"], kind="callback", attempt=2, incident_id=first["incident_id"],
                           linked=True, t_told=start + 0.28, t_end=start + 0.28)
        self.call_row(line["call_id"], first["incident_id"], first["ani"],
                      start + 0.25 if link_t is None else link_t, linked=1)
        return line

    def healthy(self):
        """A healthy minute and more: an emergency every 0.4 s from -70 s to -4 s, a surge emergency every 2 s
        from -40 s, and a callback after every tenth, each served by the next unit in rotation."""
        starts = [(round(-69.95 + 0.4 * k, 3), "normal") for k in range(165)]
        starts += [(round(-40.1 + 2.0 * k, 3), "surge") for k in range(18)]
        for k, (offset, source) in enumerate(sorted(starts)):
            first = self.emergency(self.now + offset, source=source, answer_ms=20.0 + 5 * (k % 7))
            if k % 10 == 3:
                self.callback(first, first["t_told"] + 0.3)

    # ----- the checker -----

    def window_count(self, lines):
        """How many callers' lines start in the default window."""
        return sum(1 for line in lines if line.get("who") == "caller" and self.lo <= line["t_start"] < self.hi)

    def flush(self):
        self.db.execute("COMMIT")
        self.db.execute("BEGIN")
        for name, lines in (("people.jsonl", self.lines),
                            (os.path.join("logs", "call-surge-4242.jsonl"), self.surge_lines)):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as handle:
                handle.writelines(json.dumps(line) + "\n" for line in lines)

    def verdict(self, since_t=None, **kwargs):
        """The checker's verdict now; every verdict must keep the contract eval/ reads."""
        self.flush()
        result = checker.verify(Fake(self.dir), since_t=since_t, **kwargs)
        assert check_verdict(result, impact=since_t is not None) == []
        return result


@pytest.fixture()
def world(tmp_path, monkeypatch):
    found = World(str(tmp_path))
    monkeypatch.setattr(time, "time", lambda: found.now)
    yield found
    found.close()


def assert_counts(result, **expected):
    """The verdict's integrity counts are exactly these, and 0 for every one not named."""
    assert {key: result["integrity"][key] for key in COUNTS} == {**dict.fromkeys(COUNTS, 0), **expected}
    assert result["integrity"]["ok"] is not any(expected.get(key) for key in BLOCKING)


# ----- a healthy centre -----

def test_a_healthy_minute_is_green_with_every_count_at_zero(world):
    world.healthy()
    result = world.verdict()
    assert result["recovered"] and result["slo_ok"], result["reasons"]
    assert_counts(result)
    journeys = result["journeys"]
    assert journeys["n"] == journeys["ok"] >= 60 and journeys["success_rate"] == 1.0
    assert journeys["failures"] == {} and journeys["linked"] >= 5
    surge = world.window_count(world.surge_lines)
    assert surge >= 10 and journeys["by_source"]["surge"] == {"n": surge, "ok": surge}
    assert journeys["p95_ms"] <= 50.0 and journeys["p95_allowed_ms"] == 1000.0
    assert result["integrity"]["told_without_incident_by"] == NOT_THEIRS
    assert result["integrity"]["unit_records_wrong_by"] == {"wrong_writes": 0, "units_behind": 0}
    assert result["integrity"]["for_operations"] == [] and result["reasons"] == []
    since_t = world.now - 60
    assert world.verdict(since_t=since_t)["impact"] == {
        "since_t": since_t, "until_t": world.hi, "breach_seconds": 0.0, "failed_journeys": 0,
        "time_to_mitigate_s": 0.0, "mitigation_censored": False, "told_without_incident": 0,
        "incidents_dropped": 0, "unit_record_wrong_seconds": 0.0, "calls_dropped": 0, "duplicate_incidents": 0,
        "incidents_double_sent": 0}


def test_a_unit_serving_two_incidents_in_a_row_is_not_double_committed(world):
    world.healthy()
    first = world.emergency(world.now - 25.0, "M9")    # M9's first assignment closes at +3.5 s
    world.emergency(first["t_start"] + 2.25, "M9")     # and M9 is committed again 0.05 s later
    result = world.verdict()
    assert result["recovered"], result["reasons"]
    assert_counts(result)


def test_a_callback_linked_to_its_own_open_incident_belongs_and_succeeds(world):
    world.healthy()
    first = world.emergency(world.now - 25.0, "M9")
    world.callback(first, first["t_told"] + 0.3)
    result = world.verdict()
    assert result["recovered"], result["reasons"]
    assert_counts(result)


def test_an_empty_centre_keeps_the_contract_and_is_red(world):
    for since_t in (None, world.now - 60):
        result = world.verdict(since_t=since_t)
        assert result["journeys"]["n"] == 0 and result["journeys"]["p95_ms"] is None
        assert result["integrity"]["ok"] and not result["slo_ok"] and not result["recovered"]
        assert result["reasons"] == ["only 0 calls started in the 20 s window; at least 20 are needed"]


def test_a_half_written_last_line_is_skipped(world):
    world.healthy()
    world.flush()
    with open(os.path.join(world.dir, "people.jsonl"), "a", encoding="utf-8") as handle:
        handle.write('{"who": "caller", "source": "normal", "t_start": ')
    result = checker.verify(Fake(world.dir))
    assert result["recovered"], result["reasons"]


# ----- shape (a): told help is on the way, with no incident of theirs -----

def test_a_caller_told_with_no_calls_row_and_no_incident_is_shape_a(world):
    world.healthy()
    world.caller(world.now - 20.0, incident_id=999999)
    result = world.verdict()
    assert_counts(result, told_without_incident=1)
    assert result["integrity"]["told_without_incident_by"] == {**NOT_THEIRS, "missing": 1}
    assert result["journeys"]["failures"] == {"no_incident": 1}
    assert "1 callers were told help is on the way but CAD holds no incident of theirs" in result["reasons"]


def test_an_incident_deleted_before_the_caller_was_told_is_shape_a(world):
    world.healthy()
    line, incident = world.entered(world.now - 20.0)
    world.delete(incident, line["t_start"] + 1.18)     # the calls row still points at it
    result = world.verdict()
    assert_counts(result, told_without_incident=1)
    assert result["integrity"]["told_without_incident_by"] == {**NOT_THEIRS, "missing": 1}


def test_a_link_to_an_incident_closed_before_the_link_is_shape_a(world):
    world.healthy()
    first = world.emergency(world.now - 25.0, "M9")    # closed at +3.5 s
    world.callback(first, first["t_start"] + 4.0)      # linked at +4.25 s
    result = world.verdict()
    assert_counts(result, told_without_incident=1)
    assert result["integrity"]["told_without_incident_by"] == {**NOT_THEIRS, "closed_before_link": 1}


def test_a_link_to_another_emergencys_incident_is_shape_a(world):
    world.healthy()
    first = world.emergency(world.now - 25.0, "M9")
    other = world.caller(first["t_start"] + 1.0, incident_id=first["incident_id"], linked=True)
    world.call_row(other["call_id"], first["incident_id"], other["ani"], other["t_start"] + 1.1, linked=1)
    result = world.verdict()
    assert_counts(result, told_without_incident=1)
    assert result["integrity"]["told_without_incident_by"] == {**NOT_THEIRS, "other_emergency": 1}


def test_a_caller_told_about_a_test_incident_is_shape_a(world):
    world.healthy()
    line = world.caller(world.now - 20.0)
    line["incident_id"] = world.incident(line["t_start"] + 1.15, line["call_id"], line["ani"], test=1)
    world.call_row(line["call_id"], line["incident_id"], line["ani"], line["t_start"] + 1.15)
    result = world.verdict()
    assert_counts(result, told_without_incident=1)
    assert result["integrity"]["told_without_incident_by"] == {**NOT_THEIRS, "test": 1}


# ----- shape (b): an incident a caller was told about, dropped with no crew ever sent -----

def test_an_incident_closed_before_any_crew_is_shape_b(world):
    world.healthy()
    line, incident = world.entered(world.now - 20.0)
    world.status(incident, "closed", line["t_start"] + 1.5)
    result = world.verdict()
    assert_counts(result, incidents_dropped=1)
    assert result["journeys"]["failures"] == {"not_reached": 1}


def test_an_incident_en_route_in_cad_with_no_crew_line_is_shape_b(world):
    world.healthy()
    line, incident = world.entered(world.now - 20.0)
    world.status(incident, "dispatched", line["t_start"] + 1.3)
    world.assignment(incident, "M9", line["t_start"] + 1.3, "acked")
    world.status(incident, "enroute", line["t_start"] + 1.9)
    assert_counts(world.verdict(), incidents_dropped=1)


def test_an_incident_left_on_a_4_s_old_alerted_assignment_is_shape_b(world):
    world.healthy()
    _, incident = world.entered(world.now - 20.0)
    world.status(incident, "dispatched", world.now - 4.0)
    world.assignment(incident, "M9", world.now - 4.0, "alerted")
    assert_counts(world.verdict(), incidents_dropped=1)


def test_an_incident_deleted_after_the_caller_was_told_is_shape_b(world):
    world.healthy()
    line, incident = world.entered(world.now - 20.0)
    world.delete(incident, line["t_start"] + 2.0)
    result = world.verdict()
    assert_counts(result, incidents_dropped=1)     # not shape (a), and its details are not judged
    assert result["journeys"]["failures"] == {"not_reached": 1}


def test_an_incident_still_pending_is_only_waiting(world):
    world.healthy()
    world.entered(world.now - 20.0)
    result = world.verdict()
    assert_counts(result, incidents_waiting=1)
    assert result["integrity"]["ok"] and result["journeys"]["failures"] == {"not_reached": 1}


def test_an_incident_with_a_1_s_old_assignment_is_only_waiting(world):
    world.healthy()
    _, incident = world.entered(world.now - 20.0)
    world.status(incident, "dispatched", world.now - 1.0)
    world.assignment(incident, "M9", world.now - 1.0, "assigned")
    assert_counts(world.verdict(), incidents_waiting=1)


# ----- shape (c): a unit's CAD record against its crew -----

def test_rule_w_counts_a_state_no_crew_held_even_when_healed_half_a_second_later(world):
    world.healthy()
    world.history("M9", world.now - 20.0, "enroute", 777)
    world.history("M9", world.now - 19.5, "available")
    result = world.verdict()
    assert_counts(result, unit_records_wrong=1)
    assert result["integrity"]["unit_records_wrong_by"] == {"wrong_writes": 1, "units_behind": 1}
    assert "1 units' CAD records differed from their crews for longer than the 3 s status lag" in result["reasons"]


def test_rule_w_alone_catches_a_wrong_state_shorter_than_a_sample(world):
    world.healthy()
    world.history("M9", world.now - 20.08, "enroute", 777)
    world.history("M9", world.now - 20.03, "available")
    result = world.verdict()
    assert_counts(result, unit_records_wrong=1)
    assert result["integrity"]["unit_records_wrong_by"] == {"wrong_writes": 1, "units_behind": 0}


def test_rule_w_allows_a_row_2_9_s_behind_its_crew(world):
    world.healthy()
    world.crew("M9", world.now - 25.0, "enroute", 777)
    world.history("M9", world.now - 22.1, "enroute", 777)
    assert_counts(world.verdict())


def test_rule_w_counts_a_row_a_tenth_of_a_second_ahead_of_its_crew(world):
    world.healthy()
    world.crew("M9", world.now - 25.0, "enroute", 777)
    world.history("M9", world.now - 25.1, "enroute", 777)
    result = world.verdict()
    assert_counts(result, unit_records_wrong=1)
    assert result["integrity"]["unit_records_wrong_by"]["wrong_writes"] == 1


def test_rule_w_counts_out_of_service_which_no_crew_reports(world):
    world.healthy()
    world.history("M9", world.now - 20.0, "outofservice")
    assert_counts(world.verdict(), unit_records_wrong=1)


def frozen(world, behind_s, start=-25.0):
    """M9's crew goes en route at start (seconds from now) and on scene 1 s later; CAD's record stays available
    until behind_s after the first change, then shows on scene."""
    world.crew("M9", world.now + start, "enroute", 777)
    world.crew("M9", world.now + start + 1.0, "onscene", 777)
    world.history("M9", world.now + start + behind_s, "onscene", 777)


def test_rule_s_counts_a_record_frozen_3_5_s_behind_a_changing_crew(world):
    world.healthy()
    frozen(world, 3.5)
    result = world.verdict()
    assert_counts(result, unit_records_wrong=1)
    assert result["integrity"]["unit_records_wrong_by"] == {"wrong_writes": 0, "units_behind": 1}


def test_rule_s_samples_every_tenth_of_a_second(world):
    world.healthy()
    frozen(world, 3.4, start=-25.45)    # wrong from -22.45 s to -22.05 s: between two whole seconds
    result = world.verdict()
    assert_counts(result, unit_records_wrong=1)
    assert result["integrity"]["unit_records_wrong_by"] == {"wrong_writes": 0, "units_behind": 1}


def test_rule_s_allows_a_record_frozen_2_5_s(world):
    world.healthy()
    frozen(world, 2.5)
    assert_counts(world.verdict())


def test_the_status_lag_is_read_from_its_module_constant(world, monkeypatch):
    world.healthy()
    frozen(world, 2.5)
    monkeypatch.setattr(checker, "LAG_ALLOW_S", 2.0)
    result = world.verdict()
    assert_counts(result, unit_records_wrong=1)
    assert "1 units' CAD records differed from their crews for longer than the 2 s status lag" in result["reasons"]


# ----- the other blocking counts -----

@pytest.mark.parametrize("after_s, duplicates", [(1.5, 1), (4.0, 0)])
def test_a_second_incident_while_the_first_is_open_is_a_duplicate(world, after_s, duplicates):
    """With repeat_match "off", cad opens a new incident for a callback instead of linking it: a duplicate while
    the first incident is open (it closes 3.5 s after the first call started), and none once it has closed."""
    world.healthy()
    first = world.emergency(world.now - 25.0, "M9")
    back, second = world.entered(first["t_start"] + after_s, emergency_id=first["emergency_id"], ani=first["ani"],
                                 kind="callback", attempt=2)
    world.respond(second, "M10", back["t_start"] + 1.3)
    result = world.verdict()
    assert_counts(result, duplicate_incidents=duplicates)
    assert result["journeys"]["failures"] == {}


def test_two_incidents_created_for_one_call_in_the_same_millisecond_are_one_duplicate(world):
    """A release that opens two incidents for one call in one transaction: both carry the same insert time, and
    the second (by id) is the duplicate."""
    world.healthy()
    line, first = world.entered(world.now - 25.0)
    second = world.incident(world.now - 25.0 + 1.15, line["call_id"], line["ani"], line["nature"])
    world.respond(first, "M9", line["t_start"] + 1.3)
    world.respond(second, "M10", line["t_start"] + 1.3)
    assert_counts(world.verdict(), duplicate_incidents=1, incidents_double_sent=0)


def test_an_incident_reached_by_two_crews_is_double_sent(world):
    world.healthy()
    first = world.emergency(world.now - 25.0, "M9")
    incident, t = first["incident_id"], first["t_start"]
    world.assignment(incident, "M10", t + 1.35, "cleared", closed_t=t + 2.8)
    world.alert("M10", t + 1.4, incident)
    for offset, status, incident_id in ((1.7, "enroute", incident), (2.5, "available", None)):
        world.crew("M10", t + offset, status, incident_id)
        world.history("M10", t + offset + 0.3, status, incident_id)
    assert_counts(world.verdict(), incidents_double_sent=1)


def test_a_unit_committed_to_two_incidents_at_once_is_double_committed(world):
    world.healthy()
    incidents = [world.incident(world.now - 50.0 + k, f"C-0000f00{k}", area.normal_number(2000 + k))
                 for k in range(4)]
    world.assignment(incidents[0], "M9", world.now - 25.0, "alerted")              # still open
    world.assignment(incidents[1], "M9", world.now - 23.0, "cleared", closed_t=world.now - 21.0)
    world.assignment(incidents[2], "M10", world.now - 40.0, "no_ack", closed_t=world.now - 36.0)
    world.assignment(incidents[3], "M10", world.now - 39.0, "cleared", closed_t=world.now - 35.0)   # before lo
    result = world.verdict()
    assert_counts(result, units_double_committed=1)
    assert "1 units were committed to two incidents at once" in result["reasons"]


@pytest.mark.parametrize("change, wrong", [({"priority": 3}, 1), ({"dx": 0.5}, 1), ({"dx": 0.09}, 0)])
def test_an_incident_with_another_priority_or_place_has_wrong_details(world, change, wrong):
    world.healthy()
    line = world.caller(world.now - 20.0)
    x, y = area.subscriber_location(line["ani"])
    incident = world.incident(line["t_start"] + 1.15, line["call_id"], line["ani"],
                              priority=change.get("priority"), x=x + change.get("dx", 0.0), y=y)
    world.call_row(line["call_id"], incident, line["ani"], line["t_start"] + 1.15)
    line["incident_id"] = incident
    world.respond(incident, "M9", line["t_start"] + 1.3)
    result = world.verdict()
    assert_counts(result, incident_details_wrong=wrong)
    assert result["journeys"]["failures"] == ({"details_wrong": 1} if wrong else {})
    sentence = "1 calls were entered in CAD with details other than their callers'"
    assert (sentence in result["reasons"]) is bool(wrong)


def test_an_alert_for_a_test_incident_reaching_a_crew_is_counted(world):
    world.healthy()
    kept = world.incident(world.now - 22.0, "C-0000beef", area.test_number(5), "test", test=1)
    gone = world.incident(world.now - 21.0, "C-0000feed", area.test_number(6), "test", test=1)
    world.delete(gone, world.now - 19.0)              # its insert row still says it was a test incident
    world.alert("M9", world.now - 20.0, kept, taken=False)
    world.alert("M10", world.now - 20.0, gone, taken=False)
    world.alert("M9", world.now - 35.0, kept, taken=False)    # before the window
    assert_counts(world.verdict(), test_alerts_to_crews=2)


def test_only_readable_field_reports_set_aside_are_harmful(world):
    world.healthy()
    readable = json.dumps(fieldmsg.build("M3", "status", "enroute", 12, world.now - 20.0))
    world.report(readable, "quarantined", world.now - 20.0, world.now - 19.0)
    world.report('{"unit": "M4", "kind": "status"', "quarantined", world.now - 18.0, world.now - 17.0)
    world.report(readable, "pending", world.now - 5.0)       # waiting more than 3 s: information only
    world.report(readable, "pending", world.now - 1.0)
    result = world.verdict()
    assert_counts(result, wrongly_quarantined=1, harmful_quarantines=1, unreadable_set_aside=1,
                  field_messages_waiting=1)
    assert result["integrity"]["for_operations"] == [{"kind": "set_aside", "item": 1, "unit": "M3"},
                                                     {"kind": "set_aside", "item": 2, "unit": None}]
    assert "1 readable field reports have been set aside" in result["reasons"]


def test_an_unreadable_report_set_aside_is_listed_but_does_not_block(world):
    world.healthy()
    world.report("not json", "quarantined", world.now - 500.0, world.now - 400.0)
    result = world.verdict()
    assert result["recovered"], result["reasons"]
    assert_counts(result, unreadable_set_aside=1)
    assert result["integrity"]["for_operations"] == [{"kind": "set_aside", "item": 1, "unit": None}]


# ----- calls, sources and test rows -----

def test_calls_lost_to_a_restart_are_counted_and_fail_but_do_not_block_integrity(world):
    world.healthy()
    world.failed(world.now - 21.0, "dropped", answered=True)
    world.failed(world.now - 20.0, "cut_off")
    world.failed(world.now - 19.0, "refused")
    world.failed(world.now - 18.0, "rolled_over")
    result = world.verdict()
    assert_counts(result, calls_dropped=2)
    assert result["integrity"]["ok"] and not result["slo_ok"]
    assert result["journeys"]["failures"] == {"not_answered": 2, "rolled_over": 1, "not_told": 1}


def test_surge_callers_are_merged_with_the_everyday_callers(world):
    world.healthy()
    world.failed(world.now - 20.0, "not_answered", source="surge")
    journeys = world.verdict()["journeys"]
    normal, surge = world.window_count(world.lines), world.window_count(world.surge_lines)
    assert journeys["by_source"] == {"normal": {"n": normal, "ok": normal}, "surge": {"n": surge, "ok": surge - 1}}
    assert journeys["n"] == normal + surge and journeys["failures"] == {"not_answered": 1}


def test_test_rows_are_ignored_everywhere(world):
    world.healthy()
    n = world.verdict()["journeys"]["n"]
    ani = area.test_number(7)
    line = world.caller(world.now - 20.0, ani=ani, nature="test")      # the users never call from these numbers
    line["incident_id"] = first = world.incident(world.now - 19.0, line["call_id"], ani, "test", test=1)
    second = world.incident(world.now - 18.0, "C-0000abcd", ani, "test", test=1)    # a second open one
    world.call_row(line["call_id"], first, ani, world.now - 19.0)
    world.status(first, "closed", world.now - 17.0)                     # closed with no crew
    world.history(area.TEST_UNIT, world.now - 20.0, "outofservice")     # no crew staffs TEST-1
    world.assignment(first, area.TEST_UNIT, world.now - 19.5, "alerted", test=1)
    world.assignment(second, area.TEST_UNIT, world.now - 18.5, "alerted", test=1)
    world.alert(area.TEST_UNIT, world.now - 18.4, second)
    world.crew(area.TEST_UNIT, world.now - 18.3, "enroute", second)
    result = world.verdict()
    assert result["recovered"], result["reasons"]
    assert_counts(result)
    assert result["journeys"]["n"] == n


# ----- the service level -----

@pytest.mark.parametrize("after_s, failure", [(3.1, "slow_entry"), (2.9, None)])
def test_a_caller_must_be_told_within_3_s_of_answer(world, after_s, failure):
    world.healthy()
    world.emergency(world.now - 20.0, "M9", t_told=world.now - 20.0 + 0.03 + after_s)
    result = world.verdict()
    assert result["journeys"]["failures"] == ({failure: 1} if failure else {})
    assert_counts(result)


@pytest.mark.parametrize("after_s, failure", [(3.1, "not_reached"), (2.9, None)])
def test_a_crew_must_be_en_route_within_3_s_of_the_caller_being_told(world, after_s, failure):
    world.healthy()
    line, incident = world.entered(world.now - 20.0)
    world.respond(incident, "M9", line["t_told"] + after_s - 0.3)     # the crew goes en route 0.3 s after
    result = world.verdict()
    assert result["journeys"]["failures"] == ({failure: 1} if failure else {})
    assert_counts(result)


@pytest.mark.parametrize("failed, ok", [(1, True), (2, False)])
def test_99_percent_of_calls_must_succeed(world, failed, ok):
    for k in range(100 - failed):
        world.emergency(world.lo + 0.1 + 0.2 * k)
    for k in range(failed):
        world.failed(world.lo + 0.15 + 0.2 * k, "refused")
    result = world.verdict()
    assert result["journeys"]["n"] == 100 and result["slo_ok"] is result["recovered"] is ok
    if not ok:
        assert result["reasons"] == ["2 of 100 calls failed: 2 not answered"]


@pytest.mark.parametrize("calls", [19, 20])
def test_a_window_needs_at_least_20_calls(world, calls):
    for k in range(calls):
        world.emergency(world.lo + 0.5 + 0.9 * k)
    result = world.verdict()
    assert result["journeys"]["n"] == result["journeys"]["ok"] == calls
    assert result["slo_ok"] is result["recovered"] is (calls >= 20)
    if calls < 20:
        assert result["reasons"] == ["only 19 calls started in the 20 s window; at least 20 are needed"]


def test_answer_p95_is_held_to_the_band_around_the_warm_up_baseline(world):
    for k in range(30):
        world.emergency(world.lo + 0.3 + 0.6 * k, answer_ms=300.0)
    assert world.verdict()["slo_ok"]                    # no baseline: the flat 1000 ms
    write_json(paths_for(world.dir)["checker_baseline"], {"answer_p95_ms": 30.0})
    result = world.verdict()
    assert result["journeys"]["p95_allowed_ms"] == 280.0 and not result["slo_ok"] and result["integrity"]["ok"]
    assert result["reasons"] == ["answer time p95 300 ms is above 280 ms"]


def test_p95_allowed_follows_the_baseline_within_the_slo():
    assert checker.p95_allowed({"answer_p95_ms": 20}) == 270.0
    assert checker.p95_allowed({"answer_p95_ms": 400}) == 800.0
    assert checker.p95_allowed({"answer_p95_ms": 900}) == 1000.0
    assert checker.p95_allowed({"answer_p95_ms": None}) == 1000.0     # fewer than 10 answered warm-up calls
    assert checker.p95_allowed({}) == checker.p95_allowed(None) == 1000.0


@pytest.mark.parametrize("slow, ok", [(8, False), (2, True)])
def test_answer_p90_must_stay_within_750_ms(world, slow, ok):
    for k in range(40):
        world.emergency(world.lo + 0.3 + 0.45 * k, answer_ms=800.0 if k < slow else 30.0)
    result = world.verdict()
    assert result["journeys"]["p95_allowed_ms"] == 1000.0 and result["slo_ok"] is ok
    if not ok:
        assert result["journeys"]["p90_ms"] == result["journeys"]["p95_ms"] == 800.0
        assert result["reasons"] == ["answer time p90 800 ms is above 750 ms"]


def test_the_baseline_needs_10_answered_warm_up_calls(world):
    world.caller(world.now - 30.0, answer_ms=900.0)    # before the warm-up window
    for k in range(9):
        world.caller(world.now - 9.0 + 0.5 * k, answer_ms=40.0)
    world.flush()
    path = paths_for(world.dir)["checker_baseline"]
    baseline = checker.record_baseline(Fake(world.dir), window_s=10.0)
    assert (baseline["n"], baseline["answer_p95_ms"], baseline["success_rate"]) == (9, None, None)
    assert read_json(path) == baseline
    world.caller(world.now - 1.0, answer_ms=60.0)
    world.flush()
    baseline = checker.record_baseline(Fake(world.dir), window_s=10.0)
    assert baseline == {"t": world.now, "window_s": 10.0, "n": 10, "success_rate": 1.0, "answer_p95_ms": 60.0,
                        "answer_p90_ms": 40.0}
    assert read_json(path) == baseline and checker.p95_allowed(baseline) == 310.0


def test_the_baseline_never_raises():
    class Broken:
        def paths(self):
            raise OSError("no data folder")

    assert checker.record_baseline(Broken(), 10.0)["answer_p95_ms"] is None


# ----- integrity.for_operations -----

def test_for_operations_lists_only_incidents_dropped_before_the_window(world):
    world.healthy()
    early, early_incident = world.entered(world.lo - 15.0)
    world.status(early_incident, "closed", early["t_start"] + 1.5)          # listed
    late, late_incident = world.entered(world.now - 20.0)
    world.status(late_incident, "closed", late["t_start"] + 1.5)            # blocks through shape (b) instead
    helped, helped_incident = world.entered(world.lo - 14.0)
    world.status(helped_incident, "closed", helped["t_start"] + 1.5)        # but the caller called back
    back, again = world.entered(helped["t_start"] + 2.0, emergency_id=helped["emergency_id"], ani=helped["ani"],
                                kind="callback", attempt=2)
    world.respond(again, "M10", back["t_start"] + 1.3)                     # and that incident was reached
    waiting, _ = world.entered(world.lo - 13.0)                             # still pending: not dropped
    world.report("not json", "quarantined", world.now - 15.0, world.now - 15.0)
    result = world.verdict()
    assert_counts(result, incidents_dropped=1, unreadable_set_aside=1)
    operations = result["integrity"]["for_operations"]
    assert operations == [{"kind": "dropped_incident", "incident_id": early_incident, "calls": [early["call_id"]]},
                          {"kind": "set_aside", "item": 1, "unit": None}]
    for item in operations:     # eval/ names an item by id, item, <x>_id or <x>_ids: only these two keys
        named = {key for key in item if key in ("id", "item") or key.endswith(("_id", "_ids"))}
        assert named == ({"item"} if item["kind"] == "set_aside" else {"incident_id"})


def test_for_operations_is_in_time_order_and_capped_at_50(world):
    world.healthy()
    for k in range(60):     # the newest row is set aside first
        world.report("not json", "quarantined", world.now - 200.0, world.now - 100.0 - k)
    operations = world.verdict()["integrity"]["for_operations"]
    assert [item["item"] for item in operations] == list(range(60, 10, -1))


# ----- impact (since_t) -----

def span(world, failures=()):
    """Healthy calls every 0.5 s through the 50 s from since_t = now - 60 s to the end of the window, and a call
    not told at each offset in failures."""
    since_t = world.now - 60.0
    for k in range(100):
        world.emergency(since_t + 0.05 + 0.5 * k)
    for offset in failures:
        world.failed(since_t + offset, "not_entered", answered=True)
    return since_t


def test_impact_buckets_and_time_to_mitigate_match_a_hand_worked_case(world):
    since_t = span(world, failures=(1.2, 12.1, 27.3))      # buckets 0, 2 and 5 miss the SLO
    impact = world.verdict(since_t=since_t)["impact"]
    assert (impact["breach_seconds"], impact["failed_journeys"]) == (15.0, 3)
    assert (impact["time_to_mitigate_s"], impact["mitigation_censored"]) == (30.0, False)


def test_a_failure_in_the_last_bucket_is_censored(world):
    since_t = span(world, failures=(3.0, 47.6))
    impact = world.verdict(since_t=since_t)["impact"]
    assert (impact["breach_seconds"], impact["time_to_mitigate_s"], impact["mitigation_censored"]) == (10.0, 50.0,
                                                                                                    True)


def test_impact_counts_each_shape_over_the_span(world):
    since_t = span(world)
    world.caller(since_t + 20.3, incident_id=999999)                                  # told, no incident
    line, incident = world.entered(since_t + 21.3)
    world.status(incident, "closed", line["t_start"] + 1.5)                            # dropped
    world.failed(since_t + 22.3, "dropped", answered=True)
    world.failed(since_t + 23.3, "cut_off")
    first = world.emergency(since_t + 24.3, "M9")
    back, second = world.entered(first["t_told"] + 0.3, emergency_id=first["emergency_id"], ani=first["ani"],
                                 kind="callback", attempt=2)
    world.respond(second, "M10", back["t_start"] + 1.3)                                # a duplicate
    sent = world.emergency(since_t + 25.3, "E9")
    world.alert("E10", sent["t_start"] + 1.4, sent["incident_id"])                     # and a second crew
    world.crew("E10", sent["t_start"] + 1.7, "enroute", sent["incident_id"])
    world.history("E10", sent["t_start"] + 2.0, "enroute", sent["incident_id"])
    world.crew("E10", sent["t_start"] + 2.5, "available")
    world.history("E10", sent["t_start"] + 2.8, "available")
    world.history("M9", since_t + 10.2, "enroute", 777)                                # wrong from +10.2 s ...
    world.history("M9", since_t + 11.3, "available")             # ... to +11.3 s: the samples at +10.5 and +11
    result = world.verdict(since_t=since_t)
    assert result["recovered"], result["reasons"]       # all of it before the window
    assert result["impact"] == {
        "since_t": since_t, "until_t": world.hi, "breach_seconds": 5.0, "failed_journeys": 4,
        "time_to_mitigate_s": 25.0, "mitigation_censored": False, "told_without_incident": 1,
        "incidents_dropped": 1, "unit_record_wrong_seconds": 1.0, "calls_dropped": 2, "duplicate_incidents": 1,
        "incidents_double_sent": 1}
    assert result["integrity"]["for_operations"] == [
        {"kind": "dropped_incident", "incident_id": incident, "calls": [line["call_id"]]}]


# ----- the command line and what the checker may touch -----

def test_the_command_line_judges_a_data_folder(world, monkeypatch, capsys):
    world.healthy()
    world.flush()
    monkeypatch.setattr(sys, "argv", ["checker", "--data", world.dir, "--since", str(world.now - 60.0)])
    checker.main()
    result = json.loads(capsys.readouterr().out)
    assert result["recovered"] and result["impact"]["breach_seconds"] == 0, result["reasons"]
    assert check_verdict(result) == []


def test_the_checker_reads_files_and_cad_db_and_never_a_component():
    """Its imports are the standard library, the kit's pure helpers and dispatch's shared data modules: no
    release, worker, job, users' code or network client."""
    modules = set()
    for node in ast.walk(ast.parse(inspect.getsource(checker))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.update(f"{node.module}.{alias.name}" if node.module == "targets.dispatch" else node.module
                           for alias in node.names)
    assert modules <= {"argparse", "glob", "json", "math", "os", "sqlite3", "time", "bisect", "collections",
                       "ic.kit.slo", "ic.kit.stats", "ic.kit.store", "targets.dispatch.area",
                       "targets.dispatch.cadstore", "targets.dispatch.fieldmsg", "targets.dispatch.control"}
    assert checker.verify.__kwdefaults__ == {"window_s": 20.0, "lag_s": 10.0, "since_t": None}
