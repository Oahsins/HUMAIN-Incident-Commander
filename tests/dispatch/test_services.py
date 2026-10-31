"""The dispatch centre's four services, run in-process: call handling 5.2, CAD 3.4, alerting 1.6 and the call
network 1.0, with their build labels.

No process starts and no port opens. Each Release is built on a temporary data folder and its routes are called
with request dicts shaped like ic.kit.net.JsonServer's. Call handling's dependencies are other Releases, or
stand-ins that fail as a real dependency would, wired in through Release.call.
"""

import json
import os
import re
import sqlite3
import threading
import time
import types

import pytest

from ic.kit import net
from ic.kit.run_service import load_release
from ic.kit.store import ConfigStore
from targets.dispatch import area, cadstore, fieldmsg, spec
from targets.dispatch.releases.alerting.v1_6 import Release as Alerting
from targets.dispatch.releases.alerting.v1_6_1 import Release as Alerting161
from targets.dispatch.releases.cad.v3_4 import Release as Cad
from targets.dispatch.releases.cad.v3_4_1 import Release as Cad341
from targets.dispatch.releases.call_handling.v5_2 import Release as CallHandling
from targets.dispatch.releases.call_handling.v5_2_1 import Release as CallHandling521
from targets.dispatch.releases.call_network.v1_0 import Release as CallNetwork

DEFAULTS = {c["name"]: c["config"] for c in spec.COMPONENTS}
PORTS = {"call-handling": 61000, "cad": 61001, "alerting": 61003, "alerting-backup": 61004, "call-network": 61006,
         "dispatcher->alerting": 61007, "call-handling->call-network": 61008}   # only ever formatted into URLs
API = {"call_handling": ("routes", "dial", "take_position", "lookup_location", "report", "enter_incident",
                         "release_position", "background", "extra_metrics"),
       "cad": ("routes", "validate_call", "find_call", "find_open_incident", "create_incident", "link_call",
               "create_call", "mdt", "extra_metrics"),
       "alerting": ("routes", "alert", "deliver"),
       "call_network": ("routes", "ali", "locate")}
UNAVAILABLE = (503, {"error": "call handling unavailable (settings)", "at": "call-handling"})
NO_SUCH_CALL = (404, {"error": "no such call"})
NOT_A_POINT = "location: not {x, y} finite numbers"


# ----- helpers -----

def post(body=None, tail=""):
    """A request as ic.kit.net.JsonServer hands it to a route."""
    return {"method": "POST", "path": "/", "tail": tail, "query": {}, "body": body, "headers": {}}


def answer(route, request):
    """(status, body) as the client sees them."""
    try:
        return 200, route(request)
    except net.Reply as reply:
        return reply.status, reply.body


def until(check, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while not check():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.01)


def make(cls, data_dir, component, version, **settings):
    if settings:
        ConfigStore(data_dir, component).init({**DEFAULTS[component], **settings})
    return cls({"component": component, "version": version, "port": 0, "data_dir": data_dir, "ports": dict(PORTS)})


def rows(data_dir, sql, *args):
    conn = cadstore.connect(data_dir)
    try:
        return [dict(row) for row in conn.execute(sql, args)]
    finally:
        conn.close()


def records(data_dir, component, event=None):
    path = os.path.join(data_dir, "logs", f"{component}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        found = [json.loads(line) for line in handle if line.strip()]
    return [r for r in found if event is None or r["event"] == event]


def failing(kind, status=None, body=None):
    """A dependency that cannot be reached, or answers with an error, as ServiceBase.call reports it."""
    def route(request):
        if status is not None:
            raise net.Reply(status, body or {})
        raise net.CallError(kind)
    return route


class Wire:
    """Answers call handling's dependency calls in-process, through the dependency's own route."""

    def __init__(self, handling, routes):
        self.routes = routes
        self.seen = []
        handling.call = self.call

    def call(self, dep, method, url, payload=None, timeout=2.0):
        self.seen.append((dep, method, url, timeout))
        status, body = answer(self.routes[dep], post(json.loads(json.dumps(payload))))
        if status >= 400:
            raise net.CallError("http", status, body, body.get("error", ""))
        return status, body


def dial(handling, ani, test=0):
    return answer(handling.dial, post({"ani": ani, "test": test}))


def report(handling, call_id, body):
    return answer(handling.report, post(body, tail=f"{call_id}/report"))


def told(handling, ani, nature="fall", narrative="", **extra):
    """One whole call: dial, then report. Returns (dial answer, report status, report answer)."""
    status, answered = dial(handling, ani)
    assert status == 200, answered
    return (answered, *report(handling, answered["call_id"], {"nature": nature, "narrative": narrative, **extra}))


@pytest.fixture
def data(tmp_path):
    d = str(tmp_path)
    cadstore.create(d)
    for name, config in DEFAULTS.items():
        if config is not None:
            ConfigStore(d, name).init(config)
    os.makedirs(os.path.join(d, "logs"), exist_ok=True)
    return d


@pytest.fixture
def centre(data):
    network = make(CallNetwork, data, "call-network", "1.0")
    cad = make(Cad, data, "cad", "3.4")
    handling = make(CallHandling, data, "call-handling", "5.2")
    wire = Wire(handling, {"call-network": network.ali, "cad": cad.create_call})
    return types.SimpleNamespace(data=data, network=network, cad=cad, handling=handling, wire=wire)


def idle(handling):
    return not handling.seats and not handling.calls and not handling.ringing


# ----- the releases as the kit loads them -----

@pytest.mark.parametrize("component,image,version", [
    ("call-handling", "call_handling", "5.2"), ("call-handling", "call_handling", "5.2.1"), ("cad", "cad", "3.4"),
    ("cad", "cad", "3.4.1"), ("alerting", "alerting", "1.6"), ("alerting-backup", "alerting", "1.6.1"),
    ("call-network", "call_network", "1.0")])
def test_the_kit_loads_each_release_with_its_whole_api(data, component, image, version):
    cls = load_release("dispatch", component, image, version, data)
    release = cls({"component": component, "version": version, "port": 0, "data_dir": data, "ports": dict(PORTS)})
    assert all(callable(getattr(release, name, None)) for name in API[image])


def test_build_labels_change_nothing_but_the_label(data):
    for label, base in ((CallHandling521, CallHandling), (Cad341, Cad), (Alerting161, Alerting)):
        assert label.__bases__ == (base,) and label.__doc__ == "build label"
        assert [name for name in vars(label) if not name.startswith("__")] == []
    cad = make(Cad341, data, "cad", "3.4.1")
    call = {"call_id": "C-0000abcd", "ani": area.normal_number(5), "nature": "alarm", "narrative": "",
            "location": {"x": 1, "y": 2}, "location_source": "ali", "test": 0}
    assert answer(cad.create_call, post(call))[0] == 201
    assert rows(data, "SELECT release FROM incidents") == [{"release": "3.4.1"}]


def test_routes_match_the_paths_callers_crews_and_the_probe_use(centre, data):
    def route(release, path):
        handler = types.SimpleNamespace(server=types.SimpleNamespace(routes=release.routes()))
        return net._Handler._route(handler, "POST", path)

    assert route(centre.handling, "/dial") == (centre.handling.dial, "")
    assert route(centre.handling, "/calls/C-0123abcd/report") == (centre.handling.report, "C-0123abcd/report")
    assert route(centre.cad, "/calls") == (centre.cad.create_call, "")
    assert route(centre.cad, "/mdt") == (centre.cad.mdt, "")
    assert route(centre.network, "/ali") == (centre.network.ali, "")
    alerting = make(Alerting, data, "alerting", "1.6")
    assert route(alerting, "/alert") == (alerting.alert, "")


# ----- call handling: answering -----

def test_a_call_is_answered_located_entered_and_told(centre):
    ani = area.normal_number(47)
    narrative = area.NATURES["cardiac"]["narratives"][0]
    answered, status, result = told(centre.handling, ani, nature="cardiac", narrative=narrative)
    x, y = area.subscriber_location(ani)
    assert re.fullmatch(r"C-[0-9a-f]{8}", answered["call_id"])
    assert (answered["location"], answered["position"]) == ({"x": x, "y": y}, 1)
    assert (status, result) == (200, {"told": True, "incident_id": 1, "linked": False})
    [incident] = rows(centre.data, "SELECT * FROM incidents")
    assert {k: incident[k] for k in ("first_call_id", "ani", "nature", "priority", "unit_type", "narrative", "x",
                                      "y", "location_source", "status", "test", "attempts", "release")} == \
        {"first_call_id": answered["call_id"], "ani": ani, "nature": "cardiac", "priority": 1,
         "unit_type": "medic", "narrative": narrative, "x": x, "y": y, "location_source": "ali",
         "status": "pending", "test": 0, "attempts": 0, "release": "3.4"}
    assert incident["created_t"] == incident["pending_since"] == incident["updated_t"]
    assert rows(centre.data, "SELECT call_id, incident_id, ani, linked, test FROM calls") == \
        [{"call_id": answered["call_id"], "incident_id": 1, "ani": ani, "linked": 0, "test": 0}]
    assert idle(centre.handling)
    # the call network is reached through its relay route, CAD directly, each with its own setting as timeout
    assert centre.wire.seen == [
        ("call-network", "POST", f"http://127.0.0.1:{PORTS['call-handling->call-network']}/ali", 0.5),
        ("cad", "POST", f"http://127.0.0.1:{PORTS['cad']}/calls", 1.0)]
    [answered_line] = records(centre.data, "call-handling", "call_answered")
    [entered_line] = records(centre.data, "call-handling", "call_entered")
    assert (answered_line["call_id"], answered_line["position"], answered_line["ali"]) == \
        (answered["call_id"], 1, "verified")
    assert (entered_line["incident_id"], entered_line["linked"]) == (1, False)


@pytest.mark.parametrize("body,error", [
    ([], "body: not an object"),
    ({"test": 0}, "ani: not a valid number"),
    ({"ani": "12-555-0147", "test": 0}, "ani: not a valid number"),
    ({"ani": "012-555-0247", "test": 0}, "ani: not a valid number"),
    ({"ani": "012-555-0147\n", "test": 0}, "ani: not a valid number"),
    ({"ani": "0\u0661\u0662-555-0147", "test": 0}, "ani: not a valid number"),
    ({"ani": 125550147, "test": 0}, "ani: not a valid number"),
    ({"ani": "012-555-0147"}, "test: not 0 or 1"),
    ({"ani": "012-555-0147", "test": True}, "test: not 0 or 1"),
    ({"ani": "012-555-0147", "test": 2}, "test: not 0 or 1"),
    ({"ani": "012-555-0147", "test": 1.0}, "test: not 0 or 1"),
    ({"ani": "012-555-0147", "test": "0"}, "test: not 0 or 1"),
])
def test_dial_refuses_a_bad_number_or_test_flag(centre, body, error):
    assert answer(centre.handling.dial, post(body)) == (400, {"error": error})
    assert idle(centre.handling) and centre.wire.seen == []


def test_a_call_rolls_over_when_no_position_comes_free(centre, data):
    handling = make(CallHandling, data, "call-handling", "5.2", positions=1, rollover_s=0.3)
    Wire(handling, {"call-network": centre.network.ali, "cad": centre.cad.create_call})
    status, first = dial(handling, area.normal_number(1))
    assert status == 200
    started = time.monotonic()
    assert dial(handling, area.normal_number(2)) == (503, {"error": "rolled over", "at": "call-handling"})
    assert time.monotonic() - started >= 0.3
    assert list(handling.seats) == [1] and not handling.ringing
    handling.release_position(handling.calls[first["call_id"]])
    status, again = dial(handling, area.normal_number(3))
    assert (status, again["position"]) == (200, 1)
    [line] = records(data, "call-handling", "call_rolled_over")
    assert line["level"] == "WARN"


def test_ringing_calls_are_answered_in_the_order_they_rang(centre, data):
    handling = make(CallHandling, data, "call-handling", "5.2", positions=1, rollover_s=5)
    Wire(handling, {"call-network": centre.network.ali, "cad": centre.cad.create_call})
    status, first = dial(handling, area.normal_number(1))
    answered = []
    threads = []
    for i in (2, 3):
        ring = (lambda i=i: answered.append((i, dial(handling, area.normal_number(i)))))
        threads.append(threading.Thread(target=ring))
        threads[-1].start()
        until(lambda: len(handling.ringing) == i - 1)
    metrics = handling.extra_metrics(10)
    assert metrics["queue_depth"] == 2 and metrics["oldest_pending_s"] >= 0 and metrics["processed_per_s"] == 0.1
    handling.release_position(handling.calls[first["call_id"]])
    until(lambda: len(answered) == 1)
    assert answered[0][0] == 2 and len(handling.ringing) == 1
    handling.release_position(handling.calls[answered[0][1][1]["call_id"]])
    until(lambda: len(answered) == 2)
    for thread in threads:
        thread.join(5)
    assert [(i, status, body["position"]) for i, (status, body) in answered] == [(2, 200, 1), (3, 200, 1)]
    assert handling.extra_metrics(10) == {"queue_depth": 0, "oldest_pending_s": 0.0, "processed_per_s": 0.3}


def test_a_position_added_while_a_call_rings_answers_it(centre, data):
    handling = make(CallHandling, data, "call-handling", "5.2", positions=1, rollover_s=5)
    Wire(handling, {"call-network": centre.network.ali, "cad": centre.cad.create_call})
    assert dial(handling, area.normal_number(1))[0] == 200
    result = []
    thread = threading.Thread(target=lambda: result.append(dial(handling, area.normal_number(2))))
    thread.start()
    until(lambda: len(handling.ringing) == 1)
    started = time.monotonic()
    ConfigStore(data, "call-handling").set("positions", 2, "operator")
    thread.join(5)
    assert result[0][0] == 200 and result[0][1]["position"] == 2
    assert time.monotonic() - started < 2.0


def test_the_call_network_failing_leaves_the_location_to_the_caller(centre, data):
    handling = make(CallHandling, data, "call-handling", "5.2")
    Wire(handling, {"call-network": failing("timeout"), "cad": centre.cad.create_call})
    status, answered = dial(handling, area.normal_number(9))
    assert (status, answered["location"]) == (200, None)
    assert report(handling, answered["call_id"], {"nature": "fall", "narrative": ""}) == \
        (400, {"error": "location: required when the call network gave none"})
    assert idle(handling)
    answered, status, result = told(handling, area.normal_number(9), location={"x": 3, "y": 4.5})
    assert status == 200 and result["told"]
    assert rows(data, "SELECT x, y, location_source FROM incidents") == \
        [{"x": 3.0, "y": 4.5, "location_source": "verbal"}]
    [line] = records(data, "call-handling", "ali_failed")
    assert (line["level"], line["kind"]) == ("WARN", "timeout")
    assert records(data, "call-handling", "call_answered")[-1]["ali"] == "unavailable"


@pytest.mark.parametrize("ali,kind", [
    (failing("refused"), "refused"),
    (failing("bad_response"), "bad_response"),
    (lambda request: {"x": "near the park", "y": 2.0}, "bad_response"),
    (lambda request: ["x", "y"], "bad_response"),
    (None, "http"),   # the real call network: it has no record of the number
])
def test_any_call_network_failure_gives_no_location(centre, data, ali, kind):
    handling = make(CallHandling, data, "call-handling", "5.2")
    Wire(handling, {"call-network": ali or centre.network.ali, "cad": centre.cad.create_call})
    status, answered = dial(handling, "001-555-0100" if ali is None else area.normal_number(4))
    assert (status, answered["location"]) == (200, None)
    [line] = records(data, "call-handling", "ali_failed")
    assert line["kind"] == kind and line["status"] == (404 if ali is None else None)


def test_a_spoken_location_wins_over_the_call_networks(centre):
    answered, status, _ = told(centre.handling, area.normal_number(21), location={"x": 7, "y": 8})
    assert answered["location"] is not None and status == 200
    assert rows(centre.data, "SELECT x, y, location_source FROM incidents") == \
        [{"x": 7.0, "y": 8.0, "location_source": "verbal"}]


# ----- call handling: the report -----

@pytest.mark.parametrize("body,error", [
    ("cardiac", "body: not an object"),
    ({"narrative": ""}, "nature: not a known nature"),
    ({"nature": "flood", "narrative": ""}, "nature: not a known nature"),
    ({"nature": ["fall"], "narrative": ""}, "nature: not a known nature"),
    ({"nature": "test", "narrative": ""}, "nature: test is only for test calls"),
    ({"nature": "fall"}, "narrative: not text of at most 500 characters"),
    ({"nature": "fall", "narrative": 7}, "narrative: not text of at most 500 characters"),
    ({"nature": "fall", "narrative": "x" * 501}, "narrative: not text of at most 500 characters"),
    ({"nature": "fall", "narrative": "\ud800"}, "narrative: not text of at most 500 characters"),
    ({"nature": "fall", "narrative": "", "location": {"x": 1}}, NOT_A_POINT),
    ({"nature": "fall", "narrative": "", "location": {"x": 1, "y": float("nan")}}, NOT_A_POINT),
    ({"nature": "fall", "narrative": "", "location": {"x": True, "y": 2}}, NOT_A_POINT),
    ({"nature": "fall", "narrative": "", "location": {"x": "1", "y": 2}}, NOT_A_POINT),
    ({"nature": "fall", "narrative": "", "location": {"x": 10 ** 400, "y": 2}}, NOT_A_POINT),
    ({"nature": "fall", "narrative": "", "location": [1, 2]}, NOT_A_POINT),
])
def test_report_names_the_first_field_that_is_wrong(centre, body, error):
    status, answered = dial(centre.handling, area.normal_number(5))
    assert report(centre.handling, answered["call_id"], body) == (400, {"error": error})
    assert idle(centre.handling)   # a refused report still ends the call and frees the position
    assert rows(centre.data, "SELECT COUNT(*) AS n FROM incidents") == [{"n": 0}]


def test_the_test_nature_is_for_the_test_call_which_reaches_cad_as_the_probe_expects(centre):
    status, answered = dial(centre.handling, area.test_number(7), test=1)
    assert (status, answered["location"]) == (200, {"x": 0.0, "y": 0.0})
    status, result = report(centre.handling, answered["call_id"], {"nature": "test", "narrative": ""})
    assert status == 200 and result["told"]
    assert spec._test_incident_recorded(centre.data, result["incident_id"], answered["call_id"]) == \
        (True, "incident recorded")
    assert rows(centre.data, "SELECT unit_type, test FROM incidents") == [{"unit_type": "test", "test": 1}]
    # a test call may still report a real nature; CAD keeps it a test incident
    status, answered = dial(centre.handling, area.test_number(8), test=1)
    status, result = report(centre.handling, answered["call_id"], {"nature": "alarm", "narrative": ""})
    assert status == 200
    assert rows(centre.data, "SELECT nature, test FROM incidents WHERE id = ?", result["incident_id"]) == \
        [{"nature": "alarm", "test": 1}]


def test_a_report_for_an_unknown_call_gets_404(centre):
    assert report(centre.handling, "C-00000000", {"nature": "fall", "narrative": ""}) == NO_SUCH_CALL
    assert answer(centre.handling.report, post({}, tail="C-00000000/other")) == \
        (404, {"error": "no such endpoint"})
    answered, status, _ = told(centre.handling, area.normal_number(6))
    assert status == 200
    assert report(centre.handling, answered["call_id"], {"nature": "fall", "narrative": ""}) == NO_SUCH_CALL


@pytest.mark.parametrize("cad,status,body,kind", [
    (failing("timeout"), 504, {"error": "cad timed out", "at": "cad"}, "timeout"),
    (failing("refused"), 502, {"error": "cad unavailable (refused)", "at": "cad"}, "refused"),
    (failing("bad_response"), 502, {"error": "cad unavailable (bad_response)", "at": "cad"}, "bad_response"),
    (failing("http", 503, {"error": "cad-db busy"}), 502, {"error": "cad unavailable (http)", "at": "cad"},
     "http"),
    (failing("http", 400, {"error": "nature: not a known nature"}), 400, {"error": "nature: not a known nature"},
     "http"),
    (failing("http", 409, {"error": "call_id: already taken"}), 409, {"error": "call_id: already taken"}, "http"),
    (lambda request: {"incident_id": "seven", "linked": False}, 502,
     {"error": "cad unavailable (bad_response)", "at": "cad"}, "bad_response"),
    (lambda request: [1, False], 502, {"error": "cad unavailable (bad_response)", "at": "cad"}, "bad_response"),
])
def test_cad_failures_reach_the_caller_and_free_the_position(centre, data, cad, status, body, kind):
    handling = make(CallHandling, data, "call-handling", "5.2")
    Wire(handling, {"call-network": centre.network.ali, "cad": cad})
    answered, got_status, got_body = told(handling, area.normal_number(11))
    assert (got_status, got_body) == (status, body)
    assert idle(handling)
    assert report(handling, answered["call_id"], {"nature": "fall", "narrative": ""}) == NO_SUCH_CALL
    [line] = records(data, "call-handling", "call_not_entered")
    assert (line["level"], line["call_id"], line["kind"]) == ("ERROR", answered["call_id"], kind)


def test_a_position_held_by_a_call_that_never_reported_is_freed(centre):
    status, answered = dial(centre.handling, area.normal_number(12))
    call = centre.handling.calls[answered["call_id"]]
    assert centre.handling._free_idle(time.time()) == 0
    call["answered_t"] -= 16
    assert centre.handling._free_idle(time.time()) == 1
    assert idle(centre.handling)
    assert report(centre.handling, answered["call_id"], {"nature": "fall", "narrative": ""}) == NO_SUCH_CALL
    [line] = records(centre.data, "call-handling", "position_freed_idle")
    assert (line["level"], line["calls"]) == ("WARN", 1)


def test_the_background_loop_stops_at_the_gate_and_frees_idle_positions(centre):
    handling = centre.handling
    handling.server = types.SimpleNamespace(gate=threading.Event())   # cleared: the process is hung
    status, answered = dial(handling, area.normal_number(13))
    handling.calls[answered["call_id"]]["answered_t"] -= 16
    threading.Thread(target=handling.background, daemon=True).start()
    time.sleep(0.3)
    assert answered["call_id"] in handling.calls
    handling.server.gate.set()
    until(lambda: idle(handling), 3.0)
    handling.server.gate.clear()   # park the loop again


def test_a_position_freed_by_the_sweep_is_never_freed_twice(centre):
    status, first = dial(centre.handling, area.normal_number(14))
    old = centre.handling.calls[first["call_id"]]
    old["answered_t"] -= 16
    centre.handling._free_idle(time.time())
    status, second = dial(centre.handling, area.normal_number(15))
    assert second["position"] == 1
    centre.handling.release_position(old)   # the old call's late release must not free the new call's position
    assert centre.handling.seats == {1: second["call_id"]}


@pytest.mark.parametrize("key,value", [
    ("positions", 0), ("positions", 65), ("positions", True), ("positions", 2.5), ("positions", "ZZMARK"),
    ("rollover_s", 0), ("rollover_s", 10.5), ("ali_timeout_s", None), ("cad_timeout_s", float("nan")),
    ("cad_timeout_s", "1.0")])
def test_call_handling_with_an_unusable_setting_answers_503_and_names_the_key(centre, data, key, value):
    status, answered = dial(centre.handling, area.normal_number(16))
    assert status == 200
    ConfigStore(data, "call-handling").set(key, value, "operator")
    time.sleep(0.25)   # settings are re-read at most every 0.2 s
    assert dial(centre.handling, area.normal_number(17)) == UNAVAILABLE
    assert report(centre.handling, answered["call_id"], {"nature": "fall", "narrative": ""}) == UNAVAILABLE
    assert idle(centre.handling)
    lines = records(data, "call-handling", "settings_unusable")
    assert lines and all(line["level"] == "ERROR" and line["key"] == key for line in lines)
    assert set(lines[0]) == {"t", "level", "component", "event", "msg", "occurrences", "key"}
    assert all("ZZMARK" not in json.dumps(line) for line in lines)


def test_many_calls_at_once_are_all_told_and_free_every_position(centre):
    results = []

    def caller(i):
        answered, status, result = told(centre.handling, area.normal_number(100 + i), nature="alarm")
        results.append((status, result.get("linked")))

    threads = [threading.Thread(target=caller, args=(i,)) for i in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert results == [(200, False)] * 24
    assert idle(centre.handling)
    assert rows(centre.data, "SELECT COUNT(*) AS n FROM incidents") == [{"n": 24}]


# ----- CAD -----

def cad_call(call_id, ani, **change):
    return {"call_id": call_id, "ani": ani, "nature": "fall", "narrative": "", "location": {"x": 5.0, "y": 6.0},
            "location_source": "ali", "test": 0, **change}


def test_cad_creates_an_incident_then_links_a_repeat_call(data):
    cad = make(Cad, data, "cad", "3.4")
    ani = area.normal_number(3)
    assert answer(cad.create_call, post(cad_call("C-00000001", ani, nature="structure_fire"))) == \
        (201, {"incident_id": 1, "linked": False})
    assert answer(cad.create_call, post(cad_call("C-00000002", ani, nature="alarm"))) == \
        (200, {"incident_id": 1, "linked": True})
    [incident] = rows(data, "SELECT first_call_id, nature, priority, unit_type, status, attempts FROM incidents")
    assert incident == {"first_call_id": "C-00000001", "nature": "structure_fire", "priority": 1,
                        "unit_type": "engine", "status": "pending", "attempts": 0}
    assert rows(data, "SELECT call_id, incident_id, linked FROM calls ORDER BY t") == \
        [{"call_id": "C-00000001", "incident_id": 1, "linked": 0},
         {"call_id": "C-00000002", "incident_id": 1, "linked": 1}]
    assert rows(data, "SELECT op, status, first_call_id FROM incident_events") == \
        [{"op": "insert", "status": "pending", "first_call_id": "C-00000001"}]
    [created] = records(data, "cad", "incident_created")
    [linked] = records(data, "cad", "call_linked")
    assert (created["incident_id"], created["call_id"], created["priority"]) == (1, "C-00000001", 1)
    assert (linked["call_id"], linked["incident_id"]) == ("C-00000002", 1)


def test_cad_entry_is_idempotent_by_call_id(data):
    cad = make(Cad, data, "cad", "3.4")
    ani = area.normal_number(4)
    for _ in range(2):
        assert answer(cad.create_call, post(cad_call("C-0000000a", ani)))[1] == {"incident_id": 1, "linked": False}
    assert answer(cad.create_call, post(cad_call("C-0000000a", ani)))[0] == 200
    for _ in range(2):
        assert answer(cad.create_call, post(cad_call("C-0000000b", ani))) == \
            (200, {"incident_id": 1, "linked": True})
    assert rows(data, "SELECT COUNT(*) AS n FROM incidents") == [{"n": 1}]
    assert rows(data, "SELECT COUNT(*) AS n FROM calls") == [{"n": 2}]


def test_with_repeat_match_off_every_call_opens_an_incident(data):
    cad = make(Cad, data, "cad", "3.4", repeat_match="off")
    ani = area.normal_number(5)
    assert [answer(cad.create_call, post(cad_call(f"C-0000000{i}", ani))) for i in (1, 2)] == \
        [(201, {"incident_id": 1, "linked": False}), (201, {"incident_id": 2, "linked": False})]


def test_cad_links_to_the_newest_open_incident_of_the_same_kind(data):
    ani = area.normal_number(6)
    off = make(Cad, data, "cad", "3.4", repeat_match="off")
    for i in (1, 2):
        assert answer(off.create_call, post(cad_call(f"C-0000000{i}", ani)))[0] == 201
    cad = make(Cad, data, "cad", "3.4", repeat_match="ani_open")
    assert answer(cad.create_call, post(cad_call("C-00000003", ani))) == (200, {"incident_id": 2, "linked": True})
    conn = cadstore.connect(data)
    try:
        conn.execute("UPDATE incidents SET status = 'closed' WHERE id = 2")
        assert answer(cad.create_call, post(cad_call("C-00000004", ani))) == \
            (200, {"incident_id": 1, "linked": True})
        conn.execute("UPDATE incidents SET status = 'cancelled' WHERE id = 1")
        assert answer(cad.create_call, post(cad_call("C-00000005", ani))) == \
            (201, {"incident_id": 3, "linked": False})
        # a test call never joins a real incident, even from the same number
        assert answer(cad.create_call, post(cad_call("C-00000006", ani, test=1))) == \
            (201, {"incident_id": 4, "linked": False})
        assert answer(cad.create_call, post(cad_call("C-00000007", area.normal_number(7)))) == \
            (201, {"incident_id": 5, "linked": False})
    finally:
        conn.close()


GOOD = cad_call("C-0123abcd", "012-555-0147")


@pytest.mark.parametrize("change,error", [
    ({"call_id": "C-0123abcG"}, "call_id: not a call id"),
    ({"call_id": "C-0123ABCD"}, "call_id: not a call id"),
    ({"call_id": "C-0123abcde"}, "call_id: not a call id"),
    ({"call_id": "C-0123abcd\n"}, "call_id: not a call id"),
    ({"call_id": 5}, "call_id: not a call id"),
    ({"ani": "012-555-0147 "}, "ani: not a valid number"),
    ({"ani": None}, "ani: not a valid number"),
    ({"test": True}, "test: not 0 or 1"),
    ({"test": None}, "test: not 0 or 1"),
    ({"nature": "flood"}, "nature: not a known nature"),
    ({"nature": {"code": "fall"}}, "nature: not a known nature"),
    ({"nature": "test"}, "nature: test is only for test calls"),
    ({"narrative": None}, "narrative: not text of at most 500 characters"),
    ({"narrative": "x" * 501}, "narrative: not text of at most 500 characters"),
    ({"narrative": "\udfff"}, "narrative: not text of at most 500 characters"),
    ({"location": None}, "location: not {x, y} finite numbers"),
    ({"location": {"x": 1.0, "y": float("inf")}}, "location: not {x, y} finite numbers"),
    ({"location": {"x": 1.0, "y": False}}, "location: not {x, y} finite numbers"),
    ({"location_source": "gps"}, "location_source: not ali or verbal"),
    ({"location_source": ["ali"]}, "location_source: not ali or verbal"),
])
def test_cad_names_the_first_field_that_is_wrong(data, change, error):
    cad = make(Cad, data, "cad", "3.4")
    assert answer(cad.create_call, post({**GOOD, **change})) == (400, {"error": error})
    assert rows(data, "SELECT COUNT(*) AS n FROM calls") == [{"n": 0}]


def test_cad_takes_the_edges_of_every_field(data):
    cad = make(Cad, data, "cad", "3.4")
    assert answer(cad.create_call, post(["not", "an", "object"])) == (400, {"error": "body: not an object"})
    assert answer(cad.create_call, post({**GOOD, "narrative": "x" * 500, "location_source": "verbal"}))[0] == 201
    assert answer(cad.create_call, post({**GOOD, "call_id": "C-99999999", "ani": area.test_number(3),
                                         "nature": "test", "test": 1, "location": {"x": 0, "y": 0}}))[0] == 201
    assert rows(data, "SELECT priority, unit_type, test, x FROM incidents WHERE id = 2") == \
        [{"priority": 3, "unit_type": "test", "test": 1, "x": 0.0}]


def test_a_busy_cad_db_answers_503_and_counts_a_failed_write(data):
    cad = make(Cad, data, "cad", "3.4", write_timeout_ms=5000)
    assert answer(cad.mdt, post({"unit": "M1"}))[0] == 200   # this thread's connection now waits up to 5 s
    ConfigStore(data, "cad").set("write_timeout_ms", 50, "operator")
    time.sleep(0.25)
    holder = cadstore.connect(data, busy_timeout_ms=50)
    holder.execute("BEGIN IMMEDIATE")
    try:
        started = time.monotonic()
        assert answer(cad.create_call, post(GOOD)) == (503, {"error": "cad-db busy"})
        assert answer(cad.mdt, post({"unit": "M3"})) == (503, {"error": "cad-db busy"})
        assert time.monotonic() - started < 2.0   # the new write timeout took effect on the next request
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert cad.extra_metrics(10) == {"db_write_errors": 2}
    lines = records(data, "cad", "db_busy")
    assert sorted(line["operation"] for line in lines) == ["calls", "mdt"]
    assert all(line["level"] == "WARN" for line in lines)
    assert answer(cad.create_call, post(GOOD))[0] == 201   # the lock is gone: the same call goes in


def test_a_failing_cad_db_rolls_back_and_names_only_the_error_type(data, monkeypatch):
    cad = make(Cad, data, "cad", "3.4")
    create_incident = cad.create_incident

    def broken(conn, call):
        create_incident(conn, call)
        raise sqlite3.DatabaseError(f"disk image is malformed near {call['ani']} ZZMARK")

    monkeypatch.setattr(cad, "create_incident", broken)
    assert answer(cad.create_call, post(GOOD)) == (503, {"error": "cad-db unavailable"})
    assert rows(data, "SELECT COUNT(*) AS n FROM incidents") == [{"n": 0}]
    assert rows(data, "SELECT COUNT(*) AS n FROM incident_events") == [{"n": 0}]
    assert cad.extra_metrics(10) == {"db_write_errors": 1}
    [line] = records(data, "cad", "db_error")
    assert (line["level"], line["error"], line["operation"]) == ("ERROR", "DatabaseError", "calls")
    assert "ZZMARK" not in json.dumps(line) and GOOD["ani"] not in json.dumps(line)
    # a bug that is not a database error still leaves no transaction open
    monkeypatch.setattr(cad, "create_incident", lambda conn, call: {}["missing"])
    with pytest.raises(KeyError):
        cad.create_call(post(GOOD))
    monkeypatch.setattr(cad, "create_incident", create_incident)
    assert answer(cad.create_call, post(GOOD)) == (201, {"incident_id": 1, "linked": False})


@pytest.mark.parametrize("key,value", [("repeat_match", "ZZMARK"), ("repeat_match", None), ("write_timeout_ms", 0),
                                       ("write_timeout_ms", 10001), ("write_timeout_ms", 1.5),
                                       ("write_timeout_ms", True)])
def test_cad_with_an_unusable_setting_refuses_calls_and_reports(data, key, value):
    cad = make(Cad, data, "cad", "3.4", **{key: value})
    assert answer(cad.create_call, post(GOOD)) == (503, {"error": "cad unavailable (settings)"})
    assert answer(cad.mdt, post({"unit": "M3"})) == (503, {"error": "cad unavailable (settings)"})
    lines = records(data, "cad", "settings_unusable")
    assert lines and all(line["level"] == "ERROR" and line["key"] == key for line in lines)
    assert all("ZZMARK" not in json.dumps(line) for line in lines)


# ----- CAD: the gateway for unit terminals -----

def test_mdt_queues_any_small_object_for_unit_sync(data):
    cad = make(Cad, data, "cad", "3.4")
    body = fieldmsg.build("M3", "status", "enroute", 12, 1767225600.5)
    assert answer(cad.mdt, post(body)) == (200, {"queued": 1})
    [row] = rows(data, "SELECT * FROM field_queue")
    assert (row["unit_id"], row["payload_json"], row["status"], row["attempts"]) == \
        ("M3", json.dumps(body), "pending", 0)
    assert row["created_t"] == row["updated_t"]
    assert fieldmsg.parse(row["payload_json"]) == fieldmsg.Report("M3", "status", "enroute", 12, 1767225600.5)
    # CAD checks no fields: unit_id is kept only when the unit can be one
    for body, unit_id in [({"unit": 7}, None), ({"unit": "X" * 17}, None), ({"unit": "X" * 16}, "X" * 16),
                          ({}, None), ({"unit": "\ud800"}, None), ({"unit": "TEST-1", "t": "soon"}, "TEST-1"),
                          ({"unit": "M3", "t": float("nan")}, "M3")]:
        status, queued = answer(cad.mdt, post(body))
        assert status == 200
        assert rows(data, "SELECT unit_id, payload_json FROM field_queue WHERE id = ?", queued["queued"]) == \
            [{"unit_id": unit_id, "payload_json": json.dumps(body)}]
    newest = rows(data, "SELECT payload_json FROM field_queue ORDER BY id DESC LIMIT 1")[0]["payload_json"]
    assert fieldmsg.unreadable(newest)   # stored as it came; unit-sync is the one that cannot read it


def test_mdt_refuses_anything_but_an_object_of_at_most_4096_bytes(data):
    cad = make(Cad, data, "cad", "3.4")
    refused = (400, {"error": "body: not an object or too large"})
    for body in ([], "M3", 7, None, [{"unit": "M3"}]):
        assert answer(cad.mdt, post(body)) == refused
    padding = 4096 - len(json.dumps({"unit": "M3", "pad": ""}))
    exact = {"unit": "M3", "pad": "x" * padding}
    assert len(json.dumps(exact).encode("utf-8")) == 4096
    assert answer(cad.mdt, post(exact))[0] == 200
    assert answer(cad.mdt, post({**exact, "pad": "x" * (padding + 1)})) == refused
    assert answer(cad.mdt, post({"unit": "M3", "pad": "\u00e9" * (padding // 6 + 1)})) == refused   # 6 bytes each
    deep = {}
    for _ in range(100_000):
        deep = {"a": deep}
    assert answer(cad.mdt, post(deep)) == refused
    assert rows(data, "SELECT COUNT(*) AS n FROM field_queue") == [{"n": 1}]


# ----- alerting -----

def test_an_alert_is_one_json_line_in_its_controllers_inbox(data):
    primary = make(Alerting, data, "alerting", "1.6")
    backup = make(Alerting161, data, "alerting-backup", "1.6.1")
    alert = {"assignment_id": 913, "incident_id": 512, "unit": "M3", "station": "S2", "priority": 1,
             "nature": "cardiac", "x": 12.5, "y": 3.25}
    before = time.time()
    assert answer(primary.alert, post(alert)) == (200, {"delivered": True})
    path = os.path.join(data, "alerts-alerting.jsonl")
    with open(path, encoding="utf-8") as handle:
        [line] = handle.read().splitlines()
    written = json.loads(line)
    assert before <= written.pop("t") <= time.time() and written == alert
    assert spec._alert_delivered(path, 0, 913)   # as the probe reads the inbox
    assert not os.path.exists(os.path.join(data, "alerts-alerting-backup.jsonl"))
    assert answer(backup.alert, post({**alert, "assignment_id": 914}))[1] == {"delivered": True}
    assert spec._alert_delivered(os.path.join(data, "alerts-alerting-backup.jsonl"), 0, 914)
    assert not spec._alert_delivered(path, 0, 914)


@pytest.mark.parametrize("body,error", [([], "body: not an object"), (None, "body: not an object"),
                                        ({"assignment_id": 1}, "unit: missing or not text"),
                                        ({"unit": 3}, "unit: missing or not text")])
def test_an_alert_needs_a_unit(data, body, error):
    alerting = make(Alerting, data, "alerting", "1.6")
    assert answer(alerting.alert, post(body)) == (400, {"error": error})
    assert not os.path.exists(os.path.join(data, "alerts-alerting.jsonl"))


def test_alerts_sent_at_once_stay_whole_lines(data):
    alerting = make(Alerting, data, "alerting", "1.6")

    def send(k):
        for i in range(25):
            alerting.alert(post({"unit": f"M{k}", "assignment_id": k * 100 + i, "pad": "x" * 3000}))

    threads = [threading.Thread(target=send, args=(k,)) for k in range(1, 9)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    with open(os.path.join(data, "alerts-alerting.jsonl"), encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle.read().splitlines()]
    assert sorted(line["assignment_id"] for line in lines) == \
        sorted(k * 100 + i for k in range(1, 9) for i in range(25))


# ----- the call network -----

def test_the_call_network_locates_the_numbers_it_has_records_for(data):
    network = make(CallNetwork, data, "call-network", "1.0")
    for ani in (area.normal_number(0), area.normal_number(2999), area.surge_number(0, 0),
                area.surge_number(4, 999), area.test_number(42)):
        status, body = answer(network.ali, post({"ani": ani}))
        assert (status, (body["x"], body["y"])) == (200, area.subscriber_location(ani))
    assert answer(network.ali, post({"ani": area.test_number(0)})) == (200, {"x": 0.0, "y": 0.0})
    for ani in ("001-555-0100", "095-555-0100"):
        assert answer(network.ali, post({"ani": ani})) == (404, {"error": "ani: unknown"})
    for body in ({}, {"ani": None}, {"ani": "0125550147"}, [], None, {"ani": "012-555-0147\n"}):
        assert answer(network.ali, post(body)) == (400, {"error": "ani: not a valid number"})


# ----- what logs may hold -----

def test_no_log_line_holds_a_callers_number_words_or_place(centre, data, monkeypatch):
    marker = "ZZMARK"
    spoken = {"x": 13.579135, "y": 2.468024}
    narratives = [n for nature in area.REAL_NATURES for n in area.NATURES[nature]["narratives"]]
    anis = [area.normal_number(200 + i) for i in range(len(narratives) + 4)]
    fresh = iter(anis[len(narratives):])   # numbers with no open incident yet
    replies = []
    # everyday calls with what callers say, spoken locations, and a repeat call
    for i, (ani, narrative) in enumerate(zip(anis, narratives)):
        nature = area.REAL_NATURES[i % len(area.REAL_NATURES)]
        replies.append(told(centre.handling, ani, nature=nature, narrative=narrative,
                            **({"location": spoken} if i % 3 == 0 else {})))
    replies.append(told(centre.handling, anis[0], nature="cardiac", narrative=narratives[1]))
    # refused requests carrying a marker in every field
    replies.append(answer(centre.handling.dial, post({"ani": marker, "test": marker})))
    status, answered = dial(centre.handling, anis[1])
    replies.append(report(centre.handling, answered["call_id"], {"nature": marker, "narrative": marker}))
    status, answered = dial(centre.handling, anis[2])
    replies.append(report(centre.handling, answered["call_id"], {"nature": "fall", "narrative": marker * 100}))
    for change in ({"call_id": marker}, {"ani": marker}, {"nature": marker}, {"narrative": marker * 100},
                   {"location": {"x": marker, "y": 1}}, {"location_source": marker}, {"test": marker}):
        replies.append(answer(centre.cad.create_call, post({**GOOD, **change})))
    replies.append(answer(centre.network.ali, post({"ani": marker})))
    replies.append(answer(centre.cad.mdt, post({"unit": marker, "narrative": marker, "pad": marker * 1000})))
    # every failure path of call handling: no location, CAD failing every way, a roll-over and an idle call
    for ali, cad in ((failing("timeout"), centre.cad.create_call), (failing("refused"), failing("timeout")),
                     (centre.network.ali, failing("refused")),
                     (centre.network.ali, failing("http", 400, {"error": "nature: not a known nature"})),
                     (centre.network.ali, failing("http", 503, {"error": "cad-db busy"}))):
        handling = make(CallHandling, data, "call-handling", "5.2")
        Wire(handling, {"call-network": ali, "cad": cad})
        replies.append(told(handling, anis[3], nature="breathing", narrative=narratives[3], location=spoken))
    handling = make(CallHandling, data, "call-handling", "5.2", positions=1, rollover_s=0.1)
    Wire(handling, {"call-network": centre.network.ali, "cad": centre.cad.create_call})
    status, answered = dial(handling, anis[4])
    replies.append(dial(handling, anis[5]))
    handling.calls[answered["call_id"]]["answered_t"] -= 16
    handling._free_idle(time.time())
    # a busy and a failing database, whose errors quote what the caller said
    def busy(conn, call):
        raise sqlite3.OperationalError(f"database is locked near {call['ani']}")

    def broken(conn, call):
        raise sqlite3.DatabaseError(f"malformed near {call['narrative']}")

    for create_incident in (busy, broken):
        monkeypatch.setattr(centre.cad, "create_incident", create_incident)
        replies.append(told(centre.handling, next(fresh), narrative=narratives[5], location=spoken))
    # an unusable setting holding the marker
    ConfigStore(data, "call-handling").set("positions", marker, "operator")
    time.sleep(0.25)
    replies.append(dial(centre.handling, next(fresh)))

    assert marker not in json.dumps(replies)   # error answers name fields, never values
    logs = os.path.join(data, "logs")
    texts = {}
    for name in os.listdir(logs):
        with open(os.path.join(logs, name), encoding="utf-8") as handle:
            texts[name] = handle.read()
    assert {"call-handling.jsonl", "cad.jsonl"} <= set(texts)
    events = {json.loads(line)["event"] for text in texts.values() for line in text.splitlines()}
    assert {"call_answered", "call_entered", "call_not_entered", "ali_failed", "call_rolled_over",
            "position_freed_idle", "incident_created", "call_linked", "db_busy", "db_error",
            "settings_unusable"} <= events
    for name, text in texts.items():
        for secret in [marker, str(spoken["x"]), str(spoken["y"]), *anis, *narratives]:
            assert secret not in text, (name, secret)
        for line in text.splitlines():
            assert not {"ani", "narrative", "location", "x", "y"} & set(json.loads(line)), (name, line)
