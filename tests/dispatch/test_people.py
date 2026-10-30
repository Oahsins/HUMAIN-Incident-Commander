"""The dispatch centre's test users, the call surge helper and the incident archive job, without a network.

Callers run against a stand-in call centre on a fake clock. Crews are moved tick by tick against a temporary
data folder, sending their reports to a list. The surge helper's arguments, registry and number blocks, and
the archive job, run on temporary files and a fresh cad-db."""

import glob
import http.client
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import types

import pytest

from ic.kit import net
from ic.kit.store import read_json, write_json
from targets.dispatch import area, cadstore, control, fieldmsg, people, spec, surge
from targets.dispatch.control import paths_for
from targets.dispatch.jobs import incident_archive

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T0 = 1_800_000_000.0
BASE = "http://127.0.0.1:1"
ANI = area.normal_number(47)
HOME = area.subscriber_location(ANI)
CALLER_KEYS = ["who", "source", "emergency_id", "kind", "attempt", "call_id", "ani", "nature", "t_start",
               "t_answer", "answer_ms", "location", "t_told", "incident_id", "linked", "outcome", "status",
               "t_end"]


# ----- stand-ins -----

class FakeClock:
    """Time that moves only when a caller waits, or when the stand-in centre takes time to answer."""

    def __init__(self):
        self.t = T0
        self.pauses = []

    def now(self):
        return self.t

    def pause(self, seconds, stop_event=None):
        self.pauses.append(round(seconds, 3))
        self.t += seconds
        return stop_event is not None and stop_event.is_set()


class MidRng:
    """Every uniform draw is the middle of its range, and random() is fixed."""

    def __init__(self, r=0.5):
        self.r = r

    def uniform(self, a, b):
        return (a + b) / 2

    def random(self):
        return self.r


class Centre:
    """A stand-in for call-handling: each dial and each report gets the next scripted answer (a body, or a
    net.CallError to raise) after the scripted time."""

    def __init__(self, clock, dials=(), reports=()):
        self.clock = clock
        self.dials = list(dials)
        self.reports = list(reports)
        self.posts = []

    def __call__(self, url, payload, timeout):
        self.posts.append((url, payload, timeout))
        answer, took = (self.dials if url.endswith("/dial") else self.reports).pop(0)
        self.clock.t += took
        if isinstance(answer, net.CallError):
            raise answer
        return 200, answer


class Lines:
    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(dict(record))


def answered(location=HOME, call_id="C-0000abcd", took=0.02):
    where = None if location is None else {"x": location[0], "y": location[1]}
    return {"call_id": call_id, "location": where, "position": 1}, took


def told(incident_id=512, linked=False, took=0.1):
    return {"told": True, "incident_id": incident_id, "linked": linked}, took


def fails(kind, status=None, body=None, took=0.0):
    return net.CallError(kind, status, body), took


ROLLED_OVER = fails("http", 503, {"error": "rolled over", "at": "call-handling"}, took=2.5)


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(people, "clock", fake.now)
    monkeypatch.setattr(people, "pause", fake.pause)
    return fake


def emergency(centre, rng=None, stop=None, nature="cardiac", narrative="a made-up sentence"):
    log = Lines()
    outcomes = people.run_emergency(log, BASE, rng or MidRng(), "normal", "E-N-000001", ANI, nature, narrative,
                                    stop_event=stop, post=centre)
    return outcomes, log.records


# ----- outcomes -----

@pytest.mark.parametrize("exc, expected", [
    (net.CallError("http", 503, {"error": "rolled over", "at": "call-handling"}), ("rolled_over", 503)),
    (net.CallError("http", 503, {"error": "call handling unavailable (settings)"}), ("not_answered", 503)),
    (net.CallError("http", 500, {"error": "internal error"}), ("not_answered", 500)),
    (net.CallError("http", 400, {"error": "ani: not a valid number"}), ("rejected", 400)),
    (net.CallError("http", 404, {"error": "no such endpoint"}), ("rejected", 404)),
    (net.CallError("refused"), ("refused", "refused")),
    (net.CallError("reset"), ("cut_off", "reset")),
    (net.CallError("timeout"), ("timeout", "timeout")),
    (net.CallError("bad_response", 200), ("not_answered", "bad_response")),
])
def test_a_failed_dial_has_the_outcome_of_the_table(exc, expected):
    assert people.dial_outcome(exc) == expected


@pytest.mark.parametrize("exc, expected", [
    (net.CallError("http", 404, {"error": "no such call"}), ("dropped", 404)),
    (net.CallError("refused"), ("dropped", "refused")),
    (net.CallError("reset"), ("dropped", "reset")),
    (net.CallError("http", 502, {"error": "cad unavailable (refused)", "at": "cad"}), ("not_entered", 502)),
    (net.CallError("http", 504, {"error": "cad timed out", "at": "cad"}), ("not_entered", 504)),
    (net.CallError("http", 503, {"error": "call handling unavailable (settings)"}), ("not_entered", 503)),
    (net.CallError("http", 400, {"error": "location: required when the call network gave none"}),
     ("rejected", 400)),
    (net.CallError("timeout"), ("timeout", "timeout")),
    (net.CallError("bad_response", 200), ("not_entered", "bad_response")),
])
def test_a_failed_report_has_the_outcome_of_the_table(exc, expected):
    assert people.report_outcome(exc) == expected


# ----- the callers' own HTTP client -----

class FakeConnection:
    """Stands in for http.client.HTTPConnection: raises the scripted exception at the scripted step."""

    def __init__(self, script):
        self.script = script
        self.sock = self

    def settimeout(self, seconds):
        assert seconds > 0

    def connect(self):
        self._step("connect")

    def request(self, method, path, body=None, headers=None):
        self.script["sent"] = (method, path, json.loads(body), headers)
        self._step("request")

    def getresponse(self):
        self._step("response")
        return FakeResponse(*self.script.get("answer", (200, b"{}")))

    def close(self):
        self.script["closed"] = True

    def _step(self, name):
        if name in self.script:
            raise self.script[name]


class FakeResponse:
    def __init__(self, status, raw):
        self.status = status
        self.raw = raw

    def read(self):
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


def client_call(monkeypatch, script):
    monkeypatch.setattr(http.client, "HTTPConnection", lambda host, port, timeout=None: FakeConnection(script))
    return people.post_json(f"{BASE}/dial", {"ani": ANI, "test": 0}, 3.5)


@pytest.mark.parametrize("step, exc, kind", [
    ("connect", ConnectionRefusedError(), "refused"),
    ("connect", OSError("no route to the host"), "refused"),
    ("connect", TimeoutError(), "timeout"),
    ("request", BrokenPipeError(), "reset"),
    ("request", ConnectionResetError(), "reset"),
    ("response", http.client.RemoteDisconnected("closed without an answer"), "reset"),
    ("response", ConnectionAbortedError(), "reset"),
    ("response", ConnectionResetError(), "reset"),
    ("response", TimeoutError(), "timeout"),
    ("response", http.client.BadStatusLine("garbage"), "bad_response"),
])
def test_the_client_tells_a_refused_connection_from_one_cut_off(monkeypatch, step, exc, kind):
    script = {step: exc}
    with pytest.raises(net.CallError) as caught:
        client_call(monkeypatch, script)
    assert caught.value.kind == kind
    assert script["closed"]


def test_the_client_returns_json_and_raises_4xx_and_5xx_with_their_body(monkeypatch):
    script = {"answer": (200, b'{"call_id": "C-0000abcd", "location": null, "position": 3}')}
    assert client_call(monkeypatch, script) == (200, {"call_id": "C-0000abcd", "location": None, "position": 3})
    method, path, body, headers = script["sent"]
    assert (method, path, body) == ("POST", "/dial", {"ani": ANI, "test": 0})
    assert headers["Content-Type"] == "application/json"
    with pytest.raises(net.CallError) as caught:
        client_call(monkeypatch, {"answer": (503, b'{"error": "rolled over", "at": "call-handling"}')})
    assert (caught.value.kind, caught.value.status, caught.value.body["error"]) == ("http", 503, "rolled over")
    with pytest.raises(net.CallError) as caught:
        client_call(monkeypatch, {"answer": (500, b"<html>")})
    assert (caught.value.kind, caught.value.status, caught.value.body) == ("http", 500, {})
    with pytest.raises(net.CallError) as caught:
        client_call(monkeypatch, {"answer": (200, b"not json")})
    assert caught.value.kind == "bad_response"
    with pytest.raises(net.CallError) as caught:
        client_call(monkeypatch, {"answer": (200, http.client.IncompleteRead(b"{"))})
    assert caught.value.kind == "reset"


# ----- one call, and the redial and callback rules -----

def test_a_call_answered_with_the_right_location_is_told(clock):
    centre = Centre(clock, dials=[answered()], reports=[told(512)])
    outcomes, lines = emergency(centre)
    assert outcomes == ["told"]
    [line] = lines
    assert list(line) == CALLER_KEYS
    assert {k: line[k] for k in ("who", "source", "emergency_id", "kind", "attempt", "call_id", "ani", "nature",
                                 "location", "incident_id", "linked", "outcome", "status")} == {
        "who": "caller", "source": "normal", "emergency_id": "E-N-000001", "kind": "first", "attempt": 1,
        "call_id": "C-0000abcd", "ani": ANI, "nature": "cardiac", "location": "ali", "incident_id": 512,
        "linked": False, "outcome": "told", "status": 200}
    assert line["t_start"] == T0 and line["t_answer"] == round(T0 + 0.02, 3)
    assert isinstance(line["answer_ms"], float) and line["answer_ms"] >= 0
    assert line["t_told"] - line["t_answer"] == pytest.approx(1.2 + 0.1, abs=0.002)   # talk, then the report
    assert line["t_end"] == line["t_told"]
    assert centre.posts == [(f"{BASE}/dial", {"ani": ANI, "test": 0}, 3.5),
                            (f"{BASE}/calls/C-0000abcd/report", {"nature": "cardiac",
                                                                 "narrative": "a made-up sentence"}, 2.0)]
    assert clock.pauses == [1.2]


@pytest.mark.parametrize("location", [None, (HOME[0] + 0.2, HOME[1]), (HOME[0], HOME[1] - 0.06)])
def test_a_caller_gives_the_location_when_the_read_back_is_missing_or_wrong(clock, location):
    centre = Centre(clock, dials=[answered(location)], reports=[told()])
    outcomes, [line] = emergency(centre)
    assert outcomes == ["told"] and line["location"] == "verbal"
    assert centre.posts[1][1]["location"] == {"x": HOME[0], "y": HOME[1]}
    assert clock.pauses == [1.6, 1.2]   # the location by voice (1.2-2.0 s), then the talk (0.8-1.6 s)


def test_a_read_back_within_fifty_metres_is_accepted(clock):
    centre = Centre(clock, dials=[answered((HOME[0] + 0.03, HOME[1] + 0.03))], reports=[told()])
    _, [line] = emergency(centre)
    assert line["location"] == "ali" and "location" not in centre.posts[1][1]


def test_refused_and_cut_off_dials_redial_until_the_third_call(clock):
    centre = Centre(clock, dials=[fails("refused"), fails("reset"), fails("refused")])
    outcomes, lines = emergency(centre)
    assert outcomes == ["refused", "cut_off", "refused"]
    assert [line["kind"] for line in lines] == ["first", "redial", "redial"]
    assert [line["attempt"] for line in lines] == [1, 2, 3]
    assert [line["status"] for line in lines] == ["refused", "reset", "refused"]
    unreached = ("call_id", "t_answer", "answer_ms", "location", "t_told", "incident_id", "linked")
    assert all(line[k] is None for line in lines for k in unreached)
    assert {line["emergency_id"] for line in lines} == {"E-N-000001"} and {line["ani"] for line in lines} == {ANI}
    assert clock.pauses == [0.45, 0.45]   # 0.3-0.6 s before each redial


@pytest.mark.parametrize("dial, report, outcome", [
    (fails("http", 500, {"error": "internal error"}), None, "not_answered"),
    (fails("timeout", took=3.5), None, "timeout"),
    (answered(), fails("http", 404, {"error": "no such call"}), "dropped"),
    (answered(), fails("reset"), "dropped"),
    (answered(), fails("refused"), "dropped"),
    (answered(), fails("http", 502, {"error": "cad unavailable (refused)", "at": "cad"}), "not_entered"),
    (answered(), fails("timeout", took=2.0), "timeout"),
])
def test_a_caller_who_is_not_told_redials_with_the_same_number(clock, dial, report, outcome):
    centre = Centre(clock, dials=[dial, answered(call_id="C-0000abce")],
                    reports=([report] if report else []) + [told()])
    outcomes, lines = emergency(centre)
    assert outcomes == [outcome, "told"]
    assert (lines[1]["kind"], lines[1]["attempt"], lines[1]["ani"]) == ("redial", 2, ANI)
    assert centre.posts[-2][1] == {"ani": ANI, "test": 0}


@pytest.mark.parametrize("dial, report, outcome", [
    (ROLLED_OVER, None, "rolled_over"),
    (fails("http", 400, {"error": "ani: not a valid number"}), None, "rejected"),
    (answered(), fails("http", 400, {"error": "nature: not a known nature"}), "rejected"),
    (answered(), told(), "told"),
])
def test_no_redial_after_rolled_over_rejected_or_told(clock, dial, report, outcome):
    centre = Centre(clock, dials=[dial], reports=[report] if report else [])
    outcomes, lines = emergency(centre)
    assert outcomes == [outcome] and len(lines) == 1
    if outcome == "rolled_over":
        assert lines[0]["status"] == 503 and lines[0]["call_id"] is None


def test_no_redial_once_the_first_dial_is_seven_seconds_old(clock):
    centre = Centre(clock, dials=[fails("timeout", took=3.5)] * 3)
    outcomes, lines = emergency(centre)
    # the first dial times out at 3.5 s and the redial, started at 3.95 s, at 7.45 s: a third would start too late
    assert outcomes == ["timeout", "timeout"]
    assert lines[1]["t_start"] == round(T0 + 3.95, 3)


def test_answers_that_cannot_be_used_are_failed_calls(clock):
    centre = Centre(clock, dials=[({"location": None}, 0.0), answered(), answered(call_id="C-1/2")],
                    reports=[({"told": False}, 0.0), told()])
    outcomes, lines = emergency(centre)
    assert outcomes == ["not_answered", "not_entered", "told"]
    assert [line["status"] for line in lines] == ["bad_response", "bad_response", 200]
    assert centre.posts[-1][0] == f"{BASE}/calls/C-1%2F2/report"


def test_one_told_emergency_in_ten_calls_back_with_nothing_new_to_say(clock):
    centre = Centre(clock, dials=[answered(), answered(call_id="C-0000abce")],
                    reports=[told(512), told(512, linked=True)])
    outcomes, lines = emergency(centre, rng=MidRng(0.05))
    assert outcomes == ["told", "told"]
    assert [line["kind"] for line in lines] == ["first", "callback"]
    callback = lines[1]
    assert (callback["attempt"], callback["ani"], callback["nature"]) == (2, ANI, "cardiac")
    assert callback["linked"] is True
    assert centre.posts[3][1] == {"nature": "cardiac", "narrative": ""}
    assert clock.pauses == [1.2, 0.35, 0.25]   # talk; 0.2-0.5 s before calling back; a 0.2-0.3 s talk
    assert callback["t_start"] == pytest.approx(lines[0]["t_end"] + 0.35, abs=0.002)


def test_a_callback_that_fails_is_not_redialled(clock):
    centre = Centre(clock, dials=[answered(), fails("refused")], reports=[told()])
    outcomes, _ = emergency(centre, rng=MidRng(0.05))
    assert outcomes == ["told", "refused"]


def test_about_one_told_emergency_in_ten_calls_back(clock):
    import random
    rng = random.Random(3)
    callbacks = 0
    for _ in range(2000):
        centre = Centre(clock, dials=[answered(), answered()], reports=[told(), told(linked=True)])
        outcomes, _ = emergency(centre, rng=rng)
        callbacks += len(outcomes) - 1
    assert 140 < callbacks < 260


def test_once_stopped_no_further_call_starts(clock):
    stop = threading.Event()
    stop.set()
    assert emergency(Centre(clock, dials=[fails("refused")]), stop=stop)[0] == ["refused"]
    centre = Centre(clock, dials=[answered()], reports=[told()])
    assert emergency(centre, rng=MidRng(0.05), stop=stop)[0] == ["told"]   # and no callback


def test_caller_lines_hold_ids_and_codes_never_what_was_said_or_where(clock):
    narrative = area.NATURES["fall"]["narratives"][1]
    centre = Centre(clock, dials=[answered(None), fails("refused")], reports=[told(), ])
    _, lines = emergency(centre, rng=MidRng(0.05), nature="fall", narrative=narrative)
    assert narrative not in json.dumps(lines)
    assert all(list(line) == CALLER_KEYS for line in lines)


def test_the_mixes_draw_only_their_own_natures():
    import random
    rng = random.Random(5)
    for mix, codes in (("medical", area.MEDICAL_NATURES), ("fire", area.FIRE_NATURES)):
        assert {people.pick_nature(rng, mix) for _ in range(500)} == set(codes)
    drawn = [people.pick_nature(rng) for _ in range(5000)]
    assert set(drawn) == set(area.REAL_NATURES)
    assert 0.17 < drawn.count("alarm") / len(drawn) < 0.23   # weight 0.20
    assert people.pick_narrative(rng, "alarm") in area.NATURES["alarm"]["narratives"]


# ----- crews -----

class Field:
    """Crews on a temporary data folder. Reports go to a list, with a copy of the users' log at that moment."""

    def __init__(self, data_dir):
        self.paths = paths_for(data_dir)
        for path in self.paths["alert_inboxes"].values():
            open(path, "w", encoding="utf-8").close()
        self.log = people.Log(self.paths["traffic_log"])
        self.sent = []
        inboxes = [people.Inbox(path, via) for via, path in self.paths["alert_inboxes"].items()]
        self.crews = people.Crews(inboxes, self.log, MidRng(), self.send, T0)
        self.crews.start(T0)

    def send(self, index, report):
        self.sent.append((index, report, self.lines()))

    def lines(self):
        with open(self.paths["traffic_log"], encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def alert(self, unit, incident_id, assignment_id, via="alerting", xy=(16.0, 10.0)):
        self.write(via, json.dumps(alert_body(unit, incident_id, assignment_id, xy)) + "\n")

    def write(self, via, text):
        with open(self.paths["alert_inboxes"][via], "a", encoding="utf-8") as handle:
            handle.write(text)

    def run(self, until):
        """Tick every 0.05 s, as the scheduler does, from just after the last tick to `until`."""
        k = getattr(self, "k", 0)
        while T0 + 0.05 * (k + 1) <= until + 1e-9:
            k += 1
            self.crews.tick(T0 + 0.05 * k)
        self.k = k

    def of(self, unit, event=None):
        return [line for line in self.lines() if line.get("unit") == unit and event in (None, line["event"])]


def alert_body(unit, incident_id, assignment_id, xy=(16.0, 10.0)):
    return {"t": T0, "assignment_id": assignment_id, "incident_id": incident_id, "unit": unit, "station": "S2",
            "priority": 1, "nature": "cardiac", "x": xy[0], "y": xy[1]}


@pytest.fixture()
def field(tmp_path):
    f = Field(str(tmp_path))
    yield f
    f.log.close()


def test_crews_come_on_shift_available(field):
    starts = [line for line in field.lines() if line["event"] == "start"]
    assert [line["unit"] for line in starts] == list(area.UNIT_IDS)
    assert starts[0] == {"who": "crew", "event": "start", "unit": "M1", "status": "available", "incident_id": None,
                         "t": T0}


def test_a_free_crew_takes_an_alert_turns_out_drives_works_and_clears(field):
    field.alert("M3", 512, 913, xy=(16.0, 10.0))   # M3 is at S2 (16, 4): 6 km, a 0.66 s drive
    field.run(T0 + 3.0)
    lines = field.of("M3")
    assert [(line["event"], line.get("status"), line["incident_id"]) for line in lines] == [
        ("start", "available", None), ("alert", None, 512), ("status", "enroute", 512),
        ("status", "onscene", 512), ("status", "available", None)]
    alert, enroute, onscene, clear = lines[1:]
    assert alert == {"who": "crew", "event": "alert", "unit": "M3", "incident_id": 512, "assignment_id": 913,
                     "via": "alerting", "t": round(T0 + 0.05, 3), "taken": True}
    assert list(enroute) == ["who", "event", "unit", "status", "incident_id", "t"]
    assert enroute["t"] - alert["t"] == pytest.approx(0.3, abs=0.051)     # turnout, the middle of 0.2-0.4 s
    assert onscene["t"] - enroute["t"] == pytest.approx(0.66, abs=0.051)  # area.drive_s(6.0)
    assert clear["t"] - onscene["t"] == pytest.approx(0.9, abs=0.051)     # on scene, the middle of 0.6-1.2 s
    times = [line["t"] for line in lines]
    assert times == sorted(set(times))


def test_each_status_is_logged_before_its_report_leaves_with_the_same_time(field):
    field.alert("M3", 512, 913)
    field.alert("E7", 600, 914, via="alerting-backup", xy=(4.0, 4.0))
    field.run(T0 + 4.0)
    statuses = [(index, report, seen) for index, report, seen in field.sent if report["kind"] == "status"]
    assert len(statuses) == 6
    for index, report, seen in field.sent:
        assert index == area.UNIT_IDS.index(report["unit"])   # unit k always uses uplink k mod 4
        fieldmsg.parse(json.dumps(report))                    # every report the crews make can be read
        logged = [line for line in seen if line["unit"] == report["unit"] and line["event"] in ("start", "status")]
        if report["kind"] == "status":
            assert logged[-1]["t"] == report["t"]
        assert (logged[-1]["status"], logged[-1]["incident_id"]) == (report["status"], report["incident_id"])
        assert logged[-1]["t"] <= report["t"]
    for unit in ("M3", "E7"):
        beats = [r["t"] for _, r, _ in field.sent if r["unit"] == unit and r["kind"] == "heartbeat"]
        times = [line["t"] for line in field.of(unit)] + beats
        assert len(times) == len(set(times))   # a status report shares its line's time; nothing else does
        reports = [r["t"] for _, r, _ in field.sent if r["unit"] == unit]
        assert reports == sorted(set(reports))   # strictly increasing


def test_every_unit_sends_a_heartbeat_each_second_staggered_and_unlogged(field):
    field.run(T0 + 2.97)   # three whole seconds of ticks
    beats = {}
    for _, report, _ in field.sent:
        assert report["kind"] == "heartbeat"
        beats.setdefault(report["unit"], []).append(report["t"])
    assert set(beats) == set(area.UNIT_IDS)
    assert all(len(times) == 3 for times in beats.values())
    gaps = [b - a for times in beats.values() for a, b in zip(times, times[1:])]
    assert all(gap == pytest.approx(1.0, abs=0.051) for gap in gaps)
    firsts = [beats[unit][0] for unit in area.UNIT_IDS]
    assert firsts == sorted(firsts) and firsts[-1] - firsts[0] > 0.9   # spread over the second, in roster order
    assert not [line for line in field.lines() if line["event"] != "start"]


def test_a_busy_crew_does_not_take_an_alert_and_repeats_are_ignored(field):
    field.alert("M3", 512, 913)
    field.run(T0 + 0.05)                          # taken
    field.alert("M3", 513, 914)                   # busy: logged, not taken
    field.alert("M3", 512, 913)                   # the same alert again: ignored
    field.alert("TEST-1", 514, 915)               # no crew staffs TEST-1
    field.alert("X9", 516, 917)                   # no such unit
    field.run(T0 + 3.0)                           # M3 has cleared
    field.alert("M3", 512, 918)                   # an incident M3 has already served: ignored
    field.alert("M4", 519, 920, via="alerting-backup")
    field.run(T0 + 3.05)
    alerts = [line for line in field.lines() if line["event"] == "alert"]
    assert [(a["unit"], a["incident_id"], a["assignment_id"], a["via"], a["taken"]) for a in alerts] == [
        ("M3", 512, 913, "alerting", True), ("M3", 513, 914, "alerting", False),
        ("M4", 519, 920, "alerting-backup", True)]
    assert [line["incident_id"] for line in field.of("M3", "status")] == [512, 512, None]


def test_crews_act_on_whole_new_lines_only(field):
    early = os.path.join(os.path.dirname(field.paths["traffic_log"]), "early.jsonl")
    with open(early, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(alert_body("M1", 700, 1)) + "\n")
    inbox = people.Inbox(early, "alerting")
    assert inbox.new_alerts() == []               # sent before the crews came on shift
    text = json.dumps(alert_body("M5", 701, 2))
    field.write("alerting", "not json\n" + json.dumps(["a", "list"]) + "\n" + text[:25])
    field.run(T0 + 0.05)
    assert field.of("M5", "alert") == []          # half a line is not an alert yet
    field.write("alerting", text[25:] + "\n")
    for bad in ({"incident_id": "701"}, {"incident_id": 0}, {"incident_id": True}, {"incident_id": 2 ** 63},
                {"unit": None}):
        field.write("alerting", json.dumps({**alert_body("M6", 702, 3), **bad}) + "\n")
    field.run(T0 + 0.10)
    assert [line["incident_id"] for line in field.of("M5", "alert")] == [701]
    assert field.of("M6") == [line for line in field.of("M6") if line["event"] == "start"]


def test_a_crew_stamps_strictly_increasing_times():
    crew = people.Crew("M1", 0, T0)
    times = [crew.stamp(T0) for _ in range(5)]
    assert times == sorted(set(times)) and times[1] - times[0] == pytest.approx(0.001, abs=1e-6)
    assert crew.stamp(T0 - 10) > times[-1]   # even a clock that steps back never repeats a time
    assert crew.stamp(T0 + 5.00049) == round(T0 + 5.0, 3)


# ----- the terminals' uplinks -----

def report(kind, t, unit="M1"):
    return fieldmsg.build(unit, kind, "available", None, t)


def test_a_full_uplink_drops_the_oldest_heartbeat_first():
    assert people.Uplink(BASE + "/mdt").capacity == 200
    uplink = people.Uplink(BASE + "/mdt", capacity=4)
    for r in (report("status", 1), report("heartbeat", 2), report("status", 3), report("heartbeat", 4)):
        uplink.put(r)
    uplink.put(report("status", 5))
    assert [r["t"] for r in uplink.queue] == [1, 3, 4, 5]
    uplink.put(report("status", 6))
    assert [r["t"] for r in uplink.queue] == [1, 3, 5, 6]
    uplink.put(report("status", 7))              # no heartbeat left: the oldest report goes
    assert [r["t"] for r in uplink.queue] == [3, 5, 6, 7]
    assert [uplink.take(0)["t"] for _ in range(4)] == [3, 5, 6, 7] and uplink.take(0) is None


def test_an_uplink_drops_a_report_older_than_two_seconds_and_never_retries():
    posts = []

    def post(url, payload, timeout):
        posts.append((url, payload, timeout))
        if len(posts) == 1:
            raise net.CallError("timeout")
        return 200, {"queued": 1}

    uplink = people.Uplink(BASE + "/mdt", post=post)
    assert not uplink.send(report("status", T0), T0 + 2.01)      # too old to send
    assert posts == []
    assert not uplink.send(report("status", T0 + 1.0), T0 + 2.5)  # sent, failed, not tried again
    assert uplink.send(report("heartbeat", T0 + 2.4), T0 + 2.5)
    assert posts == [(BASE + "/mdt", report("status", T0 + 1.0), 1.0),
                     (BASE + "/mdt", report("heartbeat", T0 + 2.4), 1.0)]


# ----- the call surge helper -----

@pytest.fixture()
def copy_dir(tmp_path):
    """A data folder as a running copy has it, with ports.json."""
    d = str(tmp_path)
    write_json(os.path.join(d, "surge.json"), {"helpers": []})
    os.makedirs(os.path.join(d, "surge-slots"))
    os.makedirs(os.path.join(d, "logs"))
    write_json(os.path.join(d, "ports.json"), {"ports": {"call-handling": 9600, "cad": 9601}, "port_base": 9600})
    return d


STARTED = T0 - 5.0   # the start time every made-up helper registered with


@pytest.fixture()
def running(monkeypatch):
    """Made-up process ids; the ones in this set are running, each the process that started at STARTED."""
    pids = set()
    monkeypatch.setattr(surge, "alive", lambda pid: pid in pids)
    monkeypatch.setattr(surge, "started_as", lambda pid, started_t: pid in pids and started_t == STARTED)
    return pids


def registry(d):
    return read_json(os.path.join(d, "surge.json"))


def slot(d, k):
    return read_json(os.path.join(d, "surge-slots", str(k)))


@pytest.mark.parametrize("extra, reason", [
    (["--rate", "0"], "rate must be a number above 0 and at most 3"),
    (["--rate", "3.5"], "rate must be"),
    (["--rate", "fast"], "rate must be"),
    (["--rate", "nan"], "rate must be"),
    (["--seconds", "0.5"], "seconds must be a number from 1 to 900"),
    (["--seconds", "901"], "seconds must be"),
    (["--rate", "3.0", "--seconds", "400"], "rate x seconds is 1200 emergencies"),
    (["--seed", "x"], "seed must be a whole number"),
    (["--mix", "trauma"], "mix must be normal, medical or fire"),
    (["--surprise", "1"], "bad arguments"),
    (["--rate"], "bad arguments"),
])
def test_bad_arguments_are_refused_with_code_2_and_no_call(copy_dir, running, capsys, extra, reason):
    assert surge.main(["--data", copy_dir, *extra]) == 2
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1 and out[0].startswith(f"call-surge {os.getpid()}: refused: {reason}")
    assert glob.glob(os.path.join(copy_dir, "logs", "call-surge-*.jsonl")) == []
    assert registry(copy_dir) == {"helpers": []} and os.listdir(os.path.join(copy_dir, "surge-slots")) == []


def test_a_copy_without_ports_json_or_a_data_folder_is_refused(copy_dir, running, capsys):
    os.remove(os.path.join(copy_dir, "ports.json"))
    assert surge.main(["--data", copy_dir]) == 2
    assert surge.main(["--data", os.path.join(copy_dir, "missing")]) == 2
    assert surge.main([]) == 2
    out = capsys.readouterr().out.splitlines()
    assert [line.split(": refused: ")[1] for line in out] == [
        "ports.json is missing or names no call-handling port", "the data folder does not exist",
        "--data is required"]
    assert registry(copy_dir) == {"helpers": []}


def test_the_helper_refuses_as_a_process_in_the_line_control_reads(copy_dir):
    result = subprocess.run([sys.executable, "-m", "targets.dispatch.surge", "--data", copy_dir, "--rate", "5"],
                            cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT}, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 2
    [line] = result.stdout.splitlines()
    match = re.fullmatch(r"call-surge (\d+): refused: (rate must be .+)", line)
    assert match
    out = os.path.join(copy_dir, "logs", "call-surge.out")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("call-surge 11: refused: an earlier surge's reason\n")
    offset = os.path.getsize(out)
    with open(out, "a", encoding="utf-8") as handle:
        handle.write(result.stdout)
    assert control._refusal(out, offset) == match.group(2)
    assert control._refusal(out, os.path.getsize(out)) == "the helper exited before registering"


def surge_control(copy_dir, spawn):
    """A Control for copy_dir whose spawn() is the given function (no supervisor behind it)."""
    ctl = object.__new__(control.Control)
    ctl.data_dir = copy_dir
    ctl.spawn = spawn
    return ctl


def test_surge_finds_its_helper_started_through_a_venv_launcher(copy_dir, monkeypatch):
    """On Windows a venv's python.exe is a launcher: spawn() returns its pid, and the helper, its child, registers
    its own. surge() returns the helper's pid; an entry left by a process that has gone is not taken for it."""
    me, launcher = os.getpid(), 4_000_000
    def spawn(name, argv):
        write_json(os.path.join(copy_dir, "surge.json"), {"helpers": [
            {"pid": launcher, "rate": 1.0, "until_t": time.time() + 60, "started_t": T0},   # a pid reused since
            {"pid": me, "rate": 1.0, "until_t": time.time() + 60, "started_t": spec.process_started(me)}]})
        return launcher
    monkeypatch.setattr(control, "process_tree", lambda pid: [pid, me] if pid == launcher else [pid])
    monkeypatch.setattr(control.proc, "alive", lambda pid: True)
    assert surge_control(copy_dir, spawn).surge(1.0, 60) == me


def test_surge_gives_the_refusal_of_a_helper_started_through_a_venv_launcher(copy_dir, monkeypatch):
    out = os.path.join(copy_dir, "logs", "call-surge.out")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("call-surge 11: refused: an earlier surge's reason\n")
    def spawn(name, argv):   # the helper, the launcher's child, refused under its own pid and is gone
        with open(out, "a", encoding="utf-8") as handle:
            handle.write("call-surge 4000001: refused: all 5 number blocks are held by running surges\n")
        return 4_000_000
    monkeypatch.setattr(control.proc, "alive", lambda pid: False)
    with pytest.raises(RuntimeError, match="call surge refused: all 5 number blocks are held by running surges"):
        surge_control(copy_dir, spawn).surge(1.0, 60)


def test_the_registry_caps_all_surges_together_at_three_per_second(copy_dir, running):
    running.update({101, 103, 104})
    path = os.path.join(copy_dir, "surge.json")
    write_json(path, {"helpers": [{"pid": 101, "rate": 2.0, "until_t": T0 + 60, "started_t": STARTED},  # running
                                  {"pid": 102, "rate": 2.0, "until_t": T0 + 60, "started_t": STARTED},  # gone
                                  {"pid": 103, "rate": 1.5, "until_t": T0 - 1, "started_t": STARTED},   # time passed
                                  {"pid": 104, "rate": 2.0, "until_t": T0 + 60, "started_t": T0 - 90},  # pid reused
                                  {"pid": 104, "rate": 2.0, "until_t": T0 + 60}]})                      # no start time
    with pytest.raises(surge.Refused, match=r"3\.50 emergencies per second, above the cap of 3"):
        surge.register(copy_dir, 201, 1.5, T0 + 100, STARTED, now=T0)
    assert len(registry(copy_dir)["helpers"]) == 5 and os.listdir(os.path.join(copy_dir, "surge-slots")) == []
    assert surge.register(copy_dir, 200, 1.0, T0 + 150, STARTED, now=T0) == (0, 0)   # 2.0 + 1.0: exactly the cap
    assert registry(copy_dir) == {"helpers": [{"pid": 101, "rate": 2.0, "until_t": T0 + 60, "started_t": STARTED},
                                              {"pid": 200, "rate": 1.0, "until_t": T0 + 150, "started_t": STARTED}]}
    assert slot(copy_dir, 0) == {"pid": 200, "next": 0}
    running.add(200)
    with pytest.raises(surge.Refused):
        surge.register(copy_dir, 202, 0.1, T0 + 100, STARTED, now=T0)
    surge.unregister(copy_dir, 200)
    assert [h["pid"] for h in registry(copy_dir)["helpers"]] == [101]


def test_a_surge_takes_a_free_block_and_continues_where_the_last_one_stopped(copy_dir, running):
    running.update({301, 302, 303, 304})
    for k, pid in enumerate((301, 302, 303, 304)):
        write_json(os.path.join(copy_dir, "surge-slots", str(k)), {"pid": pid, "next": 10 * k})
    write_json(os.path.join(copy_dir, "surge-slots", "4"), {"pid": 305, "next": 437})   # 305 has gone
    assert surge.claim_block(copy_dir, 400) == (4, 437)
    assert slot(copy_dir, 4) == {"pid": 400, "next": 437}
    running.add(400)
    with pytest.raises(surge.Refused, match="all 5 number blocks are held by running surges"):
        surge.claim_block(copy_dir, 401)
    block = surge.Block(copy_dir, 400, 4, 437)
    assert [block.take() for _ in range(3)] == [area.surge_number(4, 437 + i) for i in range(3)]
    assert slot(copy_dir, 4)["next"] > 440       # saved ahead while it runs: a kill now repeats no number
    block.release()
    assert slot(copy_dir, 4) == {"pid": None, "next": 440}
    running.discard(400)
    assert surge.claim_block(copy_dir, 402) == (4, 440)


def test_a_lock_left_by_a_dead_helper_is_removed_and_a_held_one_refuses(copy_dir, running, monkeypatch):
    lock = os.path.join(copy_dir, "surge.lock")
    open(lock, "w", encoding="utf-8").close()
    os.utime(lock, (time.time() - 10, time.time() - 10))
    assert surge.register(copy_dir, 500, 1.0, time.time() + 60, STARTED) == (0, 0)
    assert not os.path.exists(lock)
    open(lock, "w", encoding="utf-8").close()
    monkeypatch.setattr(surge, "LOCK_WAIT_S", 0.2)
    with pytest.raises(surge.Refused, match="stayed locked"):
        surge.register(copy_dir, 501, 1.0, time.time() + 60, STARTED)
    assert [h["pid"] for h in registry(copy_dir)["helpers"]] == [500]


def test_a_surge_registers_before_its_first_call_and_logs_surge_lines(copy_dir, monkeypatch, capsys):
    pid = os.getpid()
    registered = []

    def centre(url, payload, timeout):
        if url.endswith("/dial"):
            registered.append([(h["pid"], h["started_t"]) for h in registry(copy_dir)["helpers"]])
            return 200, {"call_id": f"C-{len(registered):08x}", "location": None, "position": 1}
        return 200, {"told": True, "incident_id": len(registered), "linked": False}

    monkeypatch.setattr(people, "post_json", centre)
    monkeypatch.setattr(people, "pause", lambda seconds, stop_event=None: False)
    assert surge.main(["--data", copy_dir, "--rate", "3", "--seconds", "2", "--seed", "4", "--mix", "fire"]) == 0
    with open(os.path.join(copy_dir, "logs", f"call-surge-{pid}.jsonl"), encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle]
    emergencies = {line["emergency_id"] for line in lines}
    assert lines and all(list(line) == CALLER_KEYS for line in lines)
    assert all(line["source"] == "surge" and line["nature"] in area.FIRE_NATURES for line in lines)
    assert all(re.fullmatch(rf"E-S{pid}-\d{{6}}", e) for e in emergencies)
    assert registered and all(entries == [(pid, spec.process_started(pid))] for entries in registered)
    assert {line["ani"] for line in lines} <= {area.surge_number(0, i) for i in range(len(emergencies))}
    out = capsys.readouterr().out.splitlines()
    assert len(out) >= 2 and all(line.startswith(f"call-surge {pid}: ") for line in out)
    assert registry(copy_dir) == {"helpers": []}
    assert slot(copy_dir, 0) == {"pid": None, "next": len(emergencies)}


def helper_process():
    """A real process that is not this one, as a surge helper would be; ended by the caller."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_a_registered_start_time_tells_a_helper_from_a_process_that_reused_its_pid():
    child = helper_process()
    try:
        started = spec.process_started(child.pid)
        assert isinstance(started, float) and abs(started - time.time()) < 60
        assert spec.started_as(child.pid, started)
        assert not spec.started_as(child.pid, started - 30)   # the pid now belongs to a later process
        assert not spec.started_as(child.pid, started + 30)
    finally:
        child.kill()
        child.wait()
    assert not spec.started_as(child.pid, started)            # gone
    assert spec.process_started(child.pid) is None
    for bad in (None, "1", True, float("nan"), float("inf")):
        assert not spec.started_as(os.getpid(), bad)


def test_cleanup_ends_only_helpers_still_running_as_the_process_that_registered(tmp_path, monkeypatch):
    d = str(tmp_path)
    write_json(cadstore.locks_path(d), {"holders": []})
    helper, other = helper_process(), helper_process()
    try:
        started = spec.process_started(helper.pid)
        write_json(os.path.join(d, "surge.json"), {"helpers": [
            {"pid": helper.pid, "rate": 1.0, "until_t": time.time() + 60, "started_t": started},
            {"pid": other.pid, "rate": 1.0, "until_t": time.time() + 60,            # as if other had reused the pid
             "started_t": spec.process_started(other.pid) - 30},
            {"pid": other.pid, "rate": 1.0, "until_t": time.time() + 60},           # no start time: never trusted
            {"pid": 0, "rate": 1.0, "until_t": time.time() + 60, "started_t": started}, "junk"]})
        assert [h["pid"] for h in spec.live_helpers(d)] == [helper.pid]
        ended = []
        monkeypatch.setattr(spec.proc, "kill", lambda pid, grace_s=0.0: ended.append(pid) or True)
        spec.Spec().cleanup(types.SimpleNamespace(data_dir=d))
        assert ended == [helper.pid]
    finally:
        for child in (helper, other):
            child.kill()
            child.wait()
    assert spec.live_helpers(d) == []


# ----- the incident archive job -----

@pytest.fixture()
def cad(tmp_path):
    d = str(tmp_path)
    cadstore.create(d)
    write_json(cadstore.locks_path(d), {"holders": []})
    return d


def add_incident(conn, status, test=0):
    now = time.time()
    return conn.execute(
        "INSERT INTO incidents (first_call_id, ani, nature, priority, unit_type, narrative, x, y, "
        "location_source, status, test, created_t, updated_t, closed_t) VALUES ('C-00000001', ?, 'fall', 2, "
        "'medic', '', 1.0, 1.0, 'ali', ?, ?, ?, ?, ?)",
        (area.normal_number(1), status, test, now, now, now if status in cadstore.CLOSED_INCIDENT else None)
    ).lastrowid


def test_export_copies_closed_real_incidents_in_batches_and_changes_no_incident(cad, capsys, monkeypatch):
    # Each batch stamps its rows with one time.time(); a counter keeps batches apart even where the clock is coarse
    # (about 15 ms on Windows), and the gaps between batches are skipped.
    ticks = iter(range(1_000_000))
    monkeypatch.setattr(incident_archive, "time", types.SimpleNamespace(time=lambda: T0 + next(ticks),
                                                                        sleep=lambda seconds: None))
    conn = cadstore.connect(cad)
    closed = [add_incident(conn, "closed") for _ in range(120)]
    cancelled = add_incident(conn, "cancelled")
    for status in cadstore.OPEN_INCIDENT:
        add_incident(conn, status)
    add_incident(conn, "closed", test=1)
    incidents = [tuple(row) for row in conn.execute("SELECT * FROM incidents ORDER BY id")]
    events = conn.execute("SELECT COUNT(*) FROM incident_events").fetchone()[0]
    assert incident_archive.export(cad) == (121, 3)
    exported = {row[0]: row[1] for row in conn.execute("SELECT incident_id, exported_t FROM rms_export")}
    assert set(exported) == set(closed) | {cancelled}
    per_batch = sorted(list(exported.values()).count(t) for t in set(exported.values()))
    assert per_batch == [21, 50, 50]
    assert [tuple(row) for row in conn.execute("SELECT * FROM incidents ORDER BY id")] == incidents
    assert conn.execute("SELECT COUNT(*) FROM incident_events").fetchone()[0] == events
    assert incident_archive.export(cad) == (0, 0)
    add_incident(conn, "closed")
    assert incident_archive.main(["--data", cad, "--export"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2 and all(line.startswith(f"incident-archive {os.getpid()}: ") for line in out)
    assert "exported 1 closed incidents in 1 batches" in out[1]
    assert read_json(cadstore.locks_path(cad)) == {"holders": []}   # a normal export holds no lock to show
    conn.close()


def test_hold_lock_blocks_writers_and_shows_as_a_lock_holder_until_it_ends(cad, monkeypatch):
    pid = os.getpid()
    monkeypatch.setattr(incident_archive, "alive", lambda p: p in (777, pid))
    path = cadstore.locks_path(cad)
    write_json(path, {"holders": [{"session": "rms-sync", "pid": 777, "since_t": T0, "mode": "write",
                                   "statement": "x"},
                                  {"session": "gone", "pid": 778, "since_t": T0, "mode": "write",
                                   "statement": "y"}]})
    holder = threading.Thread(target=incident_archive.hold_lock, args=(cad, 1.0))
    holder.start()
    deadline = time.time() + 5
    while pid not in [h["pid"] for h in read_json(path)["holders"]] and time.time() < deadline:
        time.sleep(0.02)
    holders = read_json(path)["holders"]
    assert [h["pid"] for h in holders] == [777, pid]   # the other running holder stays; the dead one goes
    assert {k: v for k, v in holders[1].items() if k != "since_t"} == {
        "session": f"incident-archive-{pid}", "pid": pid, "mode": "write",
        "statement": "INSERT INTO rms_export ... (export batch)"}
    writer = cadstore.connect(cad, busy_timeout_ms=50)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        writer.execute("INSERT INTO rms_export (incident_id, exported_t) VALUES (1, 0)")
    reader = cadstore.connect(cad, readonly=True)
    assert reader.execute("SELECT COUNT(*) FROM units").fetchone()[0] == 21   # readers carry on
    holder.join(10)
    assert not holder.is_alive()
    assert [h["pid"] for h in read_json(path)["holders"]] == [777]
    writer.execute("INSERT INTO rms_export (incident_id, exported_t) VALUES (1, 0)")
    writer.close()
    reader.close()


@pytest.mark.parametrize("argv", [[], ["--export", "--cpu", "1"], ["--hold-lock", "0"], ["--cpu", "nan"]])
def test_the_job_runs_in_exactly_one_mode(cad, argv):
    with pytest.raises(SystemExit) as caught:
        incident_archive.main(["--data", cad, *argv])
    assert caught.value.code == 2


def test_the_cpu_run_says_when_it_starts_and_ends(cad):
    result = subprocess.run([sys.executable, "-m", "targets.dispatch.jobs.incident_archive", "--data", cad,
                             "--cpu", "0.2"], cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT},
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert len(lines) == 2 and all(re.match(r"incident-archive \d+: heavy run ", line) for line in lines)
