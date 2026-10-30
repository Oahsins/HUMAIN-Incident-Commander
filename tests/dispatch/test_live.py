"""Live copies of the test dispatch centre, end to end (docs/DISPATCH.md, Break and heal by hand).

Both tiers are skipped unless IC_SLOW=1.

The CI tier (IC_SLOW=1, as CI runs it) uses one copy on port base 9700 and takes about three minutes: the
adapter keeps the contract, the probe passes, a healthy minute with a small call surge is green, two breaks turn
the checker red until their fix is applied, and the copy comes down leaving nothing running.

The long tier (IC_SLOW=1 and IC_DISPATCH_LONG=1, run by hand, about 25 minutes) uses port bases 9600, 9700 and
9800: up and down three times in a row, three copies side by side and healthy for five minutes, the whole
break-and-heal table, the two breaks that have no fix, a call surge at the cap, privacy, and three families at
the real timing (the verdict about 125 s after the break, with since_t the break).

Every copy gets its port base and data folder from this file, never from runs/current.json, and is brought down
in a finally block or a fixture's teardown, also when a test fails. A port base already in use is left alone.
"""

import contextlib
import glob
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
import pytest

from ic import contract, systems
from ic.kit import net, proc
from ic.kit.conformance import check_adapter, check_verdict
from ic.kit.store import read_json
from targets.dispatch import area, fieldmsg
from tests.dispatch.test_static import RESERVED

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SLOW = os.environ.get("IC_SLOW") == "1"
LONG = SLOW and os.environ.get("IC_DISPATCH_LONG") == "1"
ci_tier = pytest.mark.skipif(not SLOW, reason="starts a live copy of the dispatch centre; set IC_SLOW=1")
long_tier = pytest.mark.skipif(not LONG, reason="the long dispatch live tests; set IC_SLOW=1 and IC_DISPATCH_LONG=1")

CI_PORT_BASE = 9700
LONG_PORT_BASES = (9600, 9700, 9800)
checker = systems.checker("dispatch")

WINDOW_S, LAG_S = contract.CHECK_WINDOW_S, contract.CHECK_LAG_S   # the verdict eval/ takes: 20 s ending 10 s ago
POLL_S = 2.5
HEALTHY_S = 50.0                      # after warm-up: about a minute of traffic in all
RED_LIMIT_S = 40.0                    # a break shows in the verdict about 10-20 s after it
GREEN_AFTER_S = WINDOW_S + LAG_S + 2  # the first verdict whose window starts after the fix
GREEN_LIMIT_S = 80.0                  # a backlog can take a few seconds more to drain (unit-sync: about 41 s)
TABLE_RED_AT_S = 35.0                 # spec 17.3: red about 35 s after the break, green about 35 s after the fix
FIX_AT_S = 5.0                        # the real timing: the alert comes 5 s after the break ...
VERDICT_AT_S = 125.0                  # ... and the verdict 125 s after it, on the window [95 s, 115 s)
PROBE_STEPS = ["call-handling", "cad", "cad-db", "call-network", "dispatcher", "alerting", "unit-sync"]
SENTENCES = [text for nature in area.NATURES.values() for text in nature["narratives"] if text]
CALLER_NUMBER = re.compile(r"0[0-9]{2}-555-01[0-9]{2}")
MARKER = "ZZMARK"


# ----- one copy: up and down -----

def data_dir(port_base):
    """Each copy's own data folder, under runs/ (which git ignores)."""
    return os.path.join(ROOT, "runs", f"dispatch-live-{port_base}")


def ports_in_use(port_base):
    return [port_base + offset for offset in range(10) if not net.port_free(port_base + offset)]


def still_running(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def processes_of(platform):
    """This copy's running processes, by pid: its supervisor with everything under it (components, users, link
    proxy, jobs and helpers), and any process whose command line names its data folder."""
    found = {}
    pid = read_json(os.path.join(platform.data_dir, "supervisor.json"), {}).get("pid")
    with contextlib.suppress(psutil.Error, TypeError, ValueError):
        supervisor = psutil.Process(pid)
        for process in [supervisor] + supervisor.children(recursive=True):
            found[process.pid] = process
    for process in psutil.process_iter(["pid", "cmdline"]):
        if any(platform.data_dir in part for part in process.info.get("cmdline") or ()):
            found[process.pid] = process
    return {pid: process for pid, process in found.items() if still_running(process)}


def start_copy(port_base, seed=1, warmup_s=contract.WARMUP_S):
    """Start one copy on its own port base and data folder. A port base someone else is using is left alone."""
    busy = ports_in_use(port_base)
    if busy:
        pytest.fail(f"ports {busy} are already in use; a copy is started only on a free port base")
    platform = systems.platform("dispatch", port_base=port_base, data_dir=data_dir(port_base), seed=seed)
    try:
        platform.start(warmup_s=warmup_s)
    except BaseException:
        bring_down(platform)
        raise
    platform.ready_t = time.time()
    return platform


def bring_down(platform, wait_s=10.0):
    """Stop a copy (safe twice) and wait until nothing of it is left: no listener on its ports and none of its
    processes. Ends what is still running after wait_s (only this copy's own processes) and returns what that
    was; empty when the copy came down by itself."""
    tracked = processes_of(platform)   # taken first: once the supervisor is gone, its children are not traceable
    platform.stop()
    deadline = time.time() + wait_s
    while True:
        tracked.update(processes_of(platform))
        running = sorted(pid for pid, process in tracked.items() if still_running(process))
        busy = ports_in_use(platform.port_base)
        if not running and not busy:
            return {}
        if time.time() > deadline:
            break
        time.sleep(0.25)
    for pid in running:
        with contextlib.suppress(psutil.Error):
            tracked[pid].kill()   # psutil refuses a pid that has since been given to another process
    return {"ports": busy, "pids": running}


# ----- verdicts -----

def verdict(platform, since_t=None):
    """The verdict eval/ takes: the calls that started in the 20 s that ended 10 s ago."""
    return checker.verify(platform.control(), window_s=WINDOW_S, lag_s=LAG_S, since_t=since_t)


def is_green(v):
    return v["recovered"]


def nonzero_counts(integrity):
    """Every integrity count that is not 0, breakdowns included; a non-empty for_operations shows as its list."""
    found = {}
    for key, value in integrity.items():
        if key == "ok":
            continue
        if isinstance(value, dict):
            found.update({f"{key}.{part}": n for part, n in value.items() if n})
        elif value:
            found[key] = value
    return found


def explain(v):
    """What an assertion message shows: the checker's reasons and the numbers behind them."""
    if v is None:
        return "no verdict was taken"
    journeys = {key: v["journeys"].get(key) for key in ("n", "ok", "failures", "p95_ms", "p95_allowed_ms")}
    return f"reasons {v['reasons']}; journeys {journeys}; counts {nonzero_counts(v['integrity'])}"


def failures(v):
    return v["journeys"].get("failures") or {}


def poll_verdict(platform, until_t, wanted):
    """Take the verdict every POLL_S until wanted(verdict) holds or until_t passes. Returns (held, last verdict)."""
    while True:
        v = verdict(platform)
        if wanted(v):
            return True, v
        if time.time() + POLL_S > until_t:
            return False, v
        time.sleep(POLL_S)


def sleep_until(t):
    time.sleep(max(0.0, t - time.time()))


# The sign each break leaves in a red verdict (docs/DISPATCH.md, Break and heal by hand).
def not_told(v):
    return bool(failures(v).get("not_told"))           # "... answered but not told help is on the way"


def not_reached(v):
    return bool(failures(v).get("not_reached"))        # "... with no crew en route within 3 s of being told"


def records_behind(v):
    return v["integrity"]["unit_records_wrong"] > 0    # "N units' CAD records differed from their crews ..."


def double_sent(v):
    return v["integrity"]["incidents_double_sent"] > 0  # "N incidents had more than one crew en route"


def records_behind_or_double_sent(v):
    """A unit record that stops following its crew shows one way or the other: a record left on a state its crew
    has left differs from the crew, and a record left at available has the unit sent again while its crew is
    already out, so a second crew goes."""
    return records_behind(v) or double_sent(v)


def duplicates(v):
    return v["integrity"]["duplicate_incidents"] > 0    # "N incidents duplicate an open incident ..."


def answered_late(v):
    journeys = v["journeys"]                            # "... rolled over to the backup centre", "answer time p95 ..."
    return bool(failures(v).get("rolled_over")) or (journeys["p95_ms"] or 0) > journeys["p95_allowed_ms"]


# ----- breaks, made through Control as an operator or the harness would -----

def kill(component):
    return lambda platform: platform.control().kill(component)


def stop(component):
    return lambda platform: platform.control().stop(component)


def hang(component):
    return lambda platform: platform.control().admin(component, "hang")


def setting(component, key, value):
    return lambda platform: platform.control().set_config(component, key, value)


def slow_link(route, **values):
    return lambda platform: platform.control().link(route, **values)


def queue_report(platform, payload, unit_id):
    """Put one field report in unit-sync's queue as cad's /mdt does; returns its queue id."""
    conn = platform.control().db()
    try:
        now = time.time()
        return conn.execute("INSERT INTO field_queue (unit_id, payload_json, status, attempts, created_t, "
                            "updated_t) VALUES (?, ?, 'pending', 0, ?, ?)", (unit_id, payload, now, now)).lastrowid
    finally:
        conn.close()


def unit_sync_seen(platform):
    return platform.adapter().observe(5.0)["components"]["unit-sync"]


def stopped_on(platform, item, limit_s=10.0):
    """unit-sync's queue head once unit-sync has stopped on this report: its id and attempts, as observe shows."""
    deadline = time.time() + limit_s
    seen = None
    while time.time() < deadline:
        seen = unit_sync_seen(platform)
        head = seen["extra"].get("head_item") or {}
        if not seen["up"] and head.get("id") == item and (head.get("attempts") or 0) >= 1:
            return head
        time.sleep(0.25)
    raise AssertionError(f"unit-sync did not stop on report {item} within {limit_s:g} s: {seen}")


def unreadable_report(platform, unit="M3"):
    """A report from a terminal whose status code is not one CAD knows ("en route"): unreadable, so unit-sync
    stops on it and stays down."""
    payload = json.dumps(fieldmsg.build(unit, "status", "en route", None, round(time.time(), 3)))
    assert fieldmsg.unreadable(payload)
    item = queue_report(platform, payload, unit)
    return {"item": item, "head": stopped_on(platform, item)}


def crew_state(platform, unit):
    """The unit's crew state now, from its latest line in the users' log: (status, incident_id)."""
    status, incident_id = "available", None
    with open(platform.control().paths()["users_log"], encoding="utf-8") as handle:
        for line in handle:
            if f'"{unit}"' not in line or not line.endswith("\n"):
                continue
            record = json.loads(line)
            if (record.get("who"), record.get("unit")) == ("crew", unit) and record.get("event") in ("start", "status"):
                status, incident_id = record["status"], record.get("incident_id")
    return status, incident_id


def status_t_of(platform, unit):
    conn = platform.control().db()
    try:
        return conn.execute("SELECT status_t FROM units WHERE id = ?", (unit,)).fetchone()["status_t"]
    finally:
        conn.close()


def far_future_report(platform, unit="M3"):
    """A report from the unit's terminal dated an hour ahead, carrying the crew's state now. It freezes the unit's
    record only if no newer report of that unit is waiting at unit-sync's next cycle, so the freeze is confirmed
    by the unit's status_t, and the report is sent once more if it did not take."""
    seen = None
    for attempt in (1, 2):
        status, incident_id = crew_state(platform, unit)
        t = round(time.time() + 3600.0, 3)
        item = queue_report(platform, json.dumps(fieldmsg.build(unit, "heartbeat", status, incident_id, t)), unit)
        time.sleep(1.5)
        seen = status_t_of(platform, unit)
        if seen is not None and abs(seen - t) < 1e-3:
            return {"item": item, "t": t, "attempt": attempt}
    raise AssertionError(f"{unit}'s record did not take a far-future report in two tries (status_t {seen})")


def hold_lock(platform):
    """incident-archive --hold-lock 600: an export batch that holds cad-db's write lock for ten minutes."""
    pid = platform.control().spawn("incident-archive", ["{python}", "-m", "targets.dispatch.jobs.incident_archive",
                                                        "--data", "{data}", "--hold-lock", "600"])
    deadline = time.time() + 5.0
    while time.time() < deadline:
        holders = platform.adapter().observe(5.0)["components"]["cad-db"]["extra"].get("lock_holders") or []
        if holders:
            return {"pid": pid, "holders": holders}
        time.sleep(0.1)
    raise AssertionError(f"the export batch {pid} never showed as a cad-db lock holder")


# ----- fixes, applied through the adapter as the incident commander would -----

def act(platform, action, target, params=None):
    answer = platform.adapter().act(action, target, params or {})
    assert answer.get("ok"), f"{action} on {target} did not succeed: {answer}"
    return answer


def fix_with(action, target, params=None):
    return lambda platform, state: act(platform, action, target, params)


def quarantine_then_restart(platform, state):
    """Set aside the report unit-sync stopped on (its queue head, as observe shows it), then restart unit-sync."""
    head = unit_sync_seen(platform)["extra"].get("head_item") or {}
    assert head.get("id") == state["item"] and (head.get("attempts") or 0) >= 1, \
        f"the queue head is not the unreadable report {state['item']}: {head}"
    act(platform, "quarantine", "unit-sync", {"item": head["id"]})
    act(platform, "restart", "unit-sync")


# ----- break, wait red, fix, wait green -----

def break_and_heal(platform, do_break, shows, fix):
    """One row of the table, quickly: green first; the break; a red verdict that shows(); the fix; a green verdict
    a whole window later. Returns (red verdict, green verdict, what the break returned)."""
    held, v = poll_verdict(platform, time.time() + 45.0, is_green)
    assert held, f"not green before the break: {explain(v)}"
    broken_t = time.time()
    state = do_break(platform)
    time.sleep(5.0)
    held, red = poll_verdict(platform, broken_t + RED_LIMIT_S, lambda v: not v["recovered"] and shows(v))
    assert held, f"not red the expected way {time.time() - broken_t:.0f} s after the break: {explain(red)}"
    fixed_t = time.time()
    fix(platform, state)
    sleep_until(fixed_t + GREEN_AFTER_S)
    held, green = poll_verdict(platform, fixed_t + GREEN_LIMIT_S, is_green)
    assert held, f"still red {time.time() - fixed_t:.0f} s after the fix: {explain(green)}"
    return red, green, state


# ----- what the logs may not hold -----

def monitors_not_zero(components):
    """Every CAD monitor (extra.integrity) that is not 0, by component."""
    return {f"{name}.{key}": value for name, seen in components.items()
            for key, value in ((seen.get("extra") or {}).get("integrity") or {}).items() if value}


def component_logs(folder):
    """The components' own logs (logs/<component>.jsonl); the surge helpers' caller logs are not theirs."""
    logs = glob.escape(os.path.join(folder, "logs"))
    return [path for path in glob.glob(os.path.join(logs, "*.jsonl"))
            if not os.path.basename(path).startswith("call-surge-")]


def lines_above_info(folder):
    found = []
    for path in component_logs(folder):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.endswith("\n"):
                    continue   # still being written
                record = json.loads(line)
                if record.get("level") != "INFO":
                    found.append(f"{os.path.basename(path)}: {record.get('level')} {record.get('event')}")
    return found


def leaks(folder):
    """(file, what) for every narrative sentence, caller's number, marker or reserved word found in the
    components' logs, every .out file, actions.jsonl and changes.jsonl."""
    paths = component_logs(folder) + glob.glob(os.path.join(glob.escape(os.path.join(folder, "logs")), "*.out"))
    paths += [os.path.join(folder, name) for name in ("actions.jsonl", "changes.jsonl")]
    found = []
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        name = os.path.relpath(path, folder)
        found += [(name, f"the narrative {sentence!r}") for sentence in SENTENCES if sentence in text]
        for pattern, what in ((CALLER_NUMBER, "a caller's number"), (re.compile(MARKER), "the marker"),
                              (RESERVED, "a reserved word")):
            match = pattern.search(text)
            if match:
                found.append((name, f"{what} {match.group()!r}"))
    return found


def crew_lines_on_test_incidents(platform):
    """Crew lines in the users' log that name a test incident. Only TEST-1 serves the test call."""
    conn = platform.control().db()
    try:
        tests = {row[0] for row in conn.execute("SELECT id FROM incidents WHERE test = 1")}
    finally:
        conn.close()
    assert tests, "the probe left no test incident to look for"
    found = []
    with open(platform.control().paths()["users_log"], encoding="utf-8") as handle:
        for line in handle:
            if '"crew"' in line and line.endswith("\n"):
                record = json.loads(line)
                if record.get("who") == "crew" and record.get("incident_id") in tests:
                    found.append(record)
    return found


def surge_logs(platform):
    return set(glob.glob(os.path.join(glob.escape(os.path.join(platform.data_dir, "logs")), "call-surge-*.jsonl")))


def check_probe(adapter):
    names = {c["name"] for c in adapter.describe()["components"]}
    result = adapter.probe()
    assert result["ok"], result["steps"]
    assert [step["step"] for step in result["steps"]] == PROBE_STEPS, result["steps"]
    assert all(step["step"] in names and step["component"] in names for step in result["steps"]), result["steps"]


def check_healthy(platform, monitor_window_s):
    """Green, every checker count and monitor 0, no failed write and no line above INFO."""
    v = verdict(platform)
    assert v["recovered"], f"port base {platform.port_base}: {explain(v)}"
    assert nonzero_counts(v["integrity"]) == {}, explain(v)
    seen = platform.adapter().observe(monitor_window_s)["components"]
    assert seen["cad-db"]["extra"]["write_errors"] == 0, seen["cad-db"]
    assert monitors_not_zero(seen) == {}
    return v


# ===== the CI tier: one copy, about three minutes =====

@pytest.fixture(scope="class")
def copy():
    """The CI tier's one copy, on port base 9700, for the tests of one class."""
    platform = start_copy(CI_PORT_BASE)
    try:
        yield platform
    finally:
        bring_down(platform)


@ci_tier
class TestOneCopy:
    def test_the_adapter_keeps_the_contract(self, copy):
        assert check_adapter(copy.adapter()) == []

    def test_the_probe_passes_in_seven_steps_and_no_crew_hears_of_it(self, copy):
        check_probe(copy.adapter())
        time.sleep(3.0)   # long enough for a crew to have logged an alert or a report for it
        assert crew_lines_on_test_incidents(copy) == []

    def test_a_healthy_minute_with_a_small_surge_is_green(self, copy):
        control = copy.control()
        first = control.surge(1.0, 30)          # emergencies per second, well below the cap of 3
        with pytest.raises(RuntimeError, match="above the cap"):
            control.surge(2.5, 10)              # 1.0 + 2.5 is over the cap: refused, never clamped
        allowed = {os.path.join(copy.data_dir, "logs", f"call-surge-{first}.jsonl")}
        assert surge_logs(copy) <= allowed, "a refused surge places no call"

        sleep_until(copy.ready_t + HEALTHY_S)
        v = check_healthy(copy, monitor_window_s=60.0)
        assert v["journeys"]["by_source"]["surge"]["n"] > 0, v["journeys"]["by_source"]
        assert check_verdict(v, impact=False) == []
        since = verdict(copy, since_t=copy.ready_t)
        assert since["recovered"], explain(since)
        assert check_verdict(since) == []
        assert since["impact"]["failed_journeys"] == 0, since["impact"]   # zero failed calls when healthy
        assert lines_above_info(copy.data_dir) == []

    def test_an_unreadable_report_is_set_aside_and_unit_sync_restarted(self, copy):
        _, green, state = break_and_heal(copy, unreadable_report, records_behind_or_double_sent,
                                         quarantine_then_restart)
        listed = [entry for entry in green["integrity"]["for_operations"] if entry.get("kind") == "set_aside"]
        assert [entry["item"] for entry in listed] == [state["item"]], green["integrity"]["for_operations"]
        assert green["integrity"]["unreadable_set_aside"] == 1 and green["integrity"]["wrongly_quarantined"] == 0

    def test_a_short_acknowledgement_timer_is_undone(self, copy):
        break_and_heal(copy, setting("dispatcher", "ack_timeout_s", 0.05), double_sent,
                       fix_with("revert_config", "dispatcher"))
        assert copy.control().snapshot()["config"]["dispatcher"]["ack_timeout_s"] == 2.0

    def test_down_leaves_no_listener_and_no_process(self, copy):
        assert bring_down(copy) == {}


# ===== the long tier, by hand: three copies =====

def on_each(platforms, work, parts):
    """Run work(platform, part) on every copy at once. Returns every problem found, in copy order."""
    def guarded(platform, part):
        try:
            return [f"port base {platform.port_base}: {p}" for p in work(platform, part)]
        except Exception as exc:   # one copy's error is reported with the others', never hides them
            return [f"port base {platform.port_base}: {type(exc).__name__}: {exc}"]
    with ThreadPoolExecutor(max_workers=len(platforms)) as pool:
        return [problem for found in pool.map(guarded, platforms, parts) for problem in found]


def back_to_primary(platform, state, green):
    """After the failover row: the link back to normal and alerting served by its primary again."""
    platform.control().link("dispatcher->alerting")
    act(platform, "failover", "alerting", {"to": "primary"})


def set_aside_listed(platform, state, green):
    listed = [entry.get("item") for entry in green["integrity"]["for_operations"] if entry.get("kind") == "set_aside"]
    assert state["item"] in listed, f"for_operations does not list report {state['item']}: {listed}"


# Spec 17.3: (name, the break through Control, the sign a red verdict shows, the fix through the adapter, what to
# check or put back afterwards).
TABLE = [
    ("kill cad", kill("cad"), not_told, fix_with("restart", "cad"), None),
    ("stop unit-sync", stop("unit-sync"), records_behind_or_double_sent, fix_with("restart", "unit-sync"), None),
    ("hang dispatcher", hang("dispatcher"), not_reached, fix_with("restart", "dispatcher"), None),
    ("hang alerting", hang("alerting"), not_reached, fix_with("restart", "alerting"), None),
    ("call-handling positions 1", setting("call-handling", "positions", 1), answered_late,
     fix_with("revert_config", "call-handling", {"key": "positions"}), None),
    ("dispatcher ack_timeout_s 0.05", setting("dispatcher", "ack_timeout_s", 0.05), double_sent,
     fix_with("revert_config", "dispatcher"), None),
    ("cad repeat_match off", setting("cad", "repeat_match", "off"), duplicates,
     fix_with("revert_config", "cad"), None),
    ("dispatcher->alerting latency 1500 ms", slow_link("dispatcher->alerting", latency_ms=1500), not_reached,
     fix_with("failover", "alerting", {"to": "standby"}), back_to_primary),
    ("incident-archive --hold-lock 600", hold_lock, not_told, fix_with("release_lock", "cad-db"), None),
    ("an unreadable report", unreadable_report, records_behind_or_double_sent, quarantine_then_restart,
     set_aside_listed),
    ("a far-future report for M3", far_future_report, records_behind_or_double_sent,
     fix_with("restart", "unit-sync"), None),
]

# Three families at the real timing: (name, the break, the labelled fix).
FAMILIES = [
    ("kill dispatcher", kill("dispatcher"), fix_with("restart", "dispatcher")),
    ("hold-lock 600", hold_lock, fix_with("release_lock", "cad-db")),
    ("unreadable report", unreadable_report, quarantine_then_restart),
]


def table_rows(platform, rows):
    """Rows of the table at the spec's pace: green first, the break, red about 35 s later, the fix, green about
    35 s after the fix."""
    problems = []
    for name, do_break, shows, fix, after in rows:
        try:
            held, v = poll_verdict(platform, time.time() + 60.0, is_green)
            if not held:
                problems.append(f"{name}: not green before the break: {explain(v)}")
                continue
            broken_t = time.time()
            state = do_break(platform)
            sleep_until(broken_t + TABLE_RED_AT_S)
            held, red = poll_verdict(platform, broken_t + TABLE_RED_AT_S + 30.0,
                                     lambda v: not v["recovered"] and shows(v))
            if not held:
                problems.append(f"{name}: not red the expected way {time.time() - broken_t:.0f} s after the break: "
                                f"{explain(red)}")
            fixed_t = time.time()
            fix(platform, state)
            sleep_until(fixed_t + GREEN_AFTER_S)
            held, green = poll_verdict(platform, fixed_t + GREEN_LIMIT_S, is_green)
            if after:
                after(platform, state, green)
            if not held:
                problems.append(f"{name}: still red {time.time() - fixed_t:.0f} s after the fix: {explain(green)}")
        except Exception as exc:
            problems.append(f"{name}: {type(exc).__name__}: {exc}")
    return problems


def without_a_fix(platform, row):
    """Break, take no action, and check the verdict 35 s and 70 s later; then put the copy back."""
    name, do_break, want_green, undo = row
    held, v = poll_verdict(platform, time.time() + 60.0, is_green)
    if not held:
        return [f"{name}: not green before the break: {explain(v)}"]
    problems = []
    broken_t = time.time()
    do_break(platform)
    try:
        for at in (TABLE_RED_AT_S, 2 * TABLE_RED_AT_S):
            sleep_until(broken_t + at)
            v = verdict(platform)
            if v["recovered"] != want_green:
                problems.append(f"{name}: {'red' if want_green else 'green'} {at:g} s after it with no action: "
                                f"{explain(v)}")
    finally:
        if undo:
            undo(platform)
    return problems


def at_real_timing(platform, family):
    """The family with no action and then with its labelled fix 5 s after the break; each verdict is taken
    125 s after the break with since_t the break. No action must be red, the fix green."""
    name, do_break, fix = family
    problems = []
    held, v = poll_verdict(platform, time.time() + 60.0, is_green)
    if not held:
        return [f"{name}: not green before the break: {explain(v)}"]
    broken_t = time.time()
    state = do_break(platform)
    sleep_until(broken_t + VERDICT_AT_S)
    v = verdict(platform, since_t=broken_t)
    if v["recovered"]:
        problems.append(f"{name}: green with no action: {explain(v)}")
    problems += [f"{name} (no action): {p}" for p in check_verdict(v)]

    fixed_t = time.time()   # heal before the second run
    fix(platform, state)
    sleep_until(fixed_t + GREEN_AFTER_S)
    held, v = poll_verdict(platform, fixed_t + GREEN_LIMIT_S, is_green)
    if not held:
        return problems + [f"{name}: still red after the fix: {explain(v)}"]

    broken_t = time.time()
    state = do_break(platform)
    sleep_until(broken_t + FIX_AT_S)
    fix(platform, state)
    sleep_until(broken_t + VERDICT_AT_S)
    v = verdict(platform, since_t=broken_t)
    if not v["recovered"]:
        problems.append(f"{name}: red with the fix applied {FIX_AT_S:g} s after the break: {explain(v)}")
    problems += [f"{name} (fixed): {p}" for p in check_verdict(v)]
    return problems


def marker_call(platform, k):
    """A call whose narrative carries the marker, placed as a caller places one, from the last surge block."""
    ani = area.surge_number(area.SURGE_BLOCKS - 1, 990 + k)
    base = f"http://127.0.0.1:{platform.port_base}"   # call-handling's port
    answer = net.post(f"{base}/dial", {"ani": ani, "test": 0}, timeout=3.5)[1]
    report = {"nature": "fall", "narrative": f"{MARKER} {k}: fell on the stairs"}
    if not answer.get("location"):   # as a caller does when the location is not read back
        x, y = area.subscriber_location(ani)
        report["location"] = {"x": x, "y": y}
    net.post(f"{base}/calls/{answer['call_id']}/report", report, timeout=2.5)


@long_tier
class TestLifecycle:
    def test_up_and_down_three_times_in_a_row(self):
        for round_ in range(1, 4):
            platform = start_copy(LONG_PORT_BASES[1], seed=round_, warmup_s=3.0)
            try:
                assert platform.running()
                check_probe(platform.adapter())
            finally:
                left = bring_down(platform)
            assert left == {}, f"round {round_}: still running after down: {left}"


@pytest.fixture(scope="class")
def copies():
    """Three copies side by side, on port bases 9600, 9700 and 9800, for the tests of one class."""
    started = []
    try:
        for seed, port_base in enumerate(LONG_PORT_BASES, start=1):
            started.append(start_copy(port_base, seed=seed))
        yield started
    finally:
        for platform in started:
            bring_down(platform)


@long_tier
class TestThreeCopies:
    def test_each_copy_keeps_the_contract_and_its_probe_passes(self, copies):
        for platform in copies:
            assert check_adapter(platform.adapter()) == [], platform.port_base
            check_probe(platform.adapter())
        time.sleep(3.0)
        assert [crew_lines_on_test_incidents(platform) for platform in copies] == [[], [], []]

    def test_three_copies_stay_healthy_side_by_side_for_five_minutes(self, copies):
        started = time.time()
        for round_ in range(1, 11):
            sleep_until(started + 30.0 * round_)
            for platform in copies:
                check_healthy(platform, monitor_window_s=30.0)
        for platform in copies:
            assert lines_above_info(platform.data_dir) == [], platform.port_base
            assert check_verdict(verdict(platform), impact=False) == []
            since = verdict(platform, since_t=platform.ready_t)
            assert since["recovered"] and check_verdict(since) == [], explain(since)

    def test_the_break_and_heal_table(self, copies):
        parts = [TABLE[k::len(copies)] for k in range(len(copies))]
        assert on_each(copies, table_rows, parts) == []

    def test_two_breaks_without_a_fix(self, copies):
        rows = [("call-handling->call-network drop_pct 1.0", slow_link("call-handling->call-network", drop_pct=1.0),
                 False, lambda platform: platform.control().link("call-handling->call-network")),
                ("deploy call-handling 5.2.1", lambda platform: platform.control().deploy("call-handling", "5.2.1"),
                 True, None)]
        assert on_each(copies[:2], without_a_fix, rows) == []

    def test_a_surge_at_the_cap_stays_green_and_a_second_is_refused(self, copies):
        platform = copies[2]
        control = platform.control()
        assert poll_verdict(platform, time.time() + 60.0, is_green)[0]
        started = time.time()
        pid = control.surge(3.0, 150, mix="medical")
        with pytest.raises(RuntimeError, match="above the cap"):
            control.surge(0.5, 60)
        allowed = {os.path.join(platform.data_dir, "logs", f"call-surge-{pid}.jsonl")}
        assert surge_logs(platform) <= allowed, "a refused surge places no call"
        for at in range(30, 161, 10):
            sleep_until(started + at)
            v = verdict(platform)
            assert v["recovered"], f"{at} s into the surge: {explain(v)}"
            if at <= 150:
                assert v["journeys"]["by_source"]["surge"]["n"] > 0, (at, v["journeys"]["by_source"])
        sleep_until(started + 150 + 15)
        assert not proc.alive(pid), "the surge helper should end within 10 s of its --seconds"

    def test_no_callers_words_numbers_or_reserved_words_reach_the_logs(self, copies):
        platform = copies[0]
        sleep_until(platform.ready_t + 300.0)   # at least five minutes of traffic
        for k in range(3):
            marker_call(platform, k)
        payload = json.dumps(fieldmsg.build(MARKER, "status", "available", None, round(time.time(), 3)))
        item = queue_report(platform, payload, MARKER)   # not on the roster: unit-sync stops on it
        stopped_on(platform, item)
        quarantine_then_restart(platform, {"item": item})
        time.sleep(3.0)
        assert [(p.port_base, leak) for p in copies for leak in leaks(p.data_dir)] == []

    def test_three_families_at_the_real_timing(self, copies):
        assert on_each(copies, at_real_timing, FAMILIES) == []
