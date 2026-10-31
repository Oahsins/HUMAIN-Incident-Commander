"""The independent checker: has the test dispatch centre really recovered? (docs/DISPATCH.md, The checker)

It never asks the agent or the centre's components. It reads what the agent cannot see: the users' own logs
(people.jsonl, where each caller writes one line per call and each crew writes every state it enters, plus the
surge helpers' logs/call-surge-*.jsonl) and cad-db, read-only. Two cad-db tables are written only by triggers,
never by a release: unit_history (every change of a unit record) and incident_events (every incident created,
closed, cancelled or deleted). They are the evidence of what CAD showed, and when.

A verdict taken at time T scores the calls that started in [T - lag_s - window_s, T - lag_s) (default: the 20 s
ending 10 s ago). A call ends within 9.1 s, so every counted call has written its line. A call succeeds when the
caller was told help is on the way within 3 s of answer, CAD holds an incident of the caller's own emergency
with the caller's details, and a real crew's own log has it en route within 3 s of the caller being told. The
case counts as recovered only when, over that window:

1. there are at least 20 calls, at least 99% of them succeed, answer time p90 is at most 750 ms and p95 is
   within the band around the warm-up baseline (never above 1000 ms);
2. no caller was told help is on the way without an incident of theirs in CAD (shape a), no incident a caller
   was told about was dropped with no crew ever en route (shape b), and no unit's CAD record differed from its
   crew by more than the 3 s status lag (shape c);
3. no incident duplicates an open incident of the same emergency, none had two crews en route, no unit was
   committed to two incidents at once, every incident carries its caller's details, no test alert reached a
   crew, and no readable field report has been set aside (by anyone, at any time).

Test rows (the test caller's numbers, test incidents and TEST-1) never count. Calls lost to a restart,
incidents still waiting for a crew, unreadable reports set aside and field reports waiting are counted but do
not block. Incidents dropped before the window, and every report set aside, are listed under
integrity.for_operations for a person to review.

Run: python -m targets.dispatch.checker --data runs/dispatch-9500 [--window 20] [--lag 10] [--since <unix time>]
"""

import argparse
import glob
import json
import math
import os
import sqlite3
import time
from bisect import bisect_right
from collections import Counter, defaultdict, namedtuple

from ic.kit.slo import time_to_mitigate
from ic.kit.stats import percentile
from ic.kit.store import read_json, write_json
from targets.dispatch import area, cadstore, fieldmsg
from targets.dispatch.control import paths_for

MIN_JOURNEYS = 20
SUCCESS_RATE = 0.99
ANSWER_P90_MS = 750.0       # NENA: 90% of calls answered within 15 s, at 1:20
SLO_P95_MS = 1000.0         # NENA: 95% answered within 20 s, at 1:20 (the SLO's p95_ms)
DISPATCHABLE_S = 3.0        # the caller is told help is on the way at most this long after answer
REACH_LIMIT_S = 3.0         # the first real crew is en route at most this long after the caller is told
LAG_ALLOW_S = 3.0           # a unit's CAD record may show any state its crew held this recently
CLOCK_TOL_S = 0.05          # and may lead its crew by at most this much (clock and stamping tolerance)
RECORD_SAMPLE_S = 0.1       # Rule S looks at every unit record this often
STUCK_S = 3.0               # an assignment older than this, with no crew, is no longer being worked
LOC_TOL_KM = 0.1
BUCKET_S = 5.0
IMPACT_SAMPLE_S = 0.5       # how often impact samples the unit records
FOR_OPERATIONS_CAP = 50
BASELINE_MIN_ANSWERED = 10  # fewer answered warm-up calls make no baseline: p95 is then held to the SLO
FIELD_WAIT_S = 3.0          # a field report pending longer than this is waiting (information only)

AVAILABLE = ("available", None)     # a unit before its crew's first line, and before CAD's first row
NO_LINES = ((), ())
REAL_UNITS = frozenset(area.UNIT_IDS)
SOURCES = ("normal", "surge")
CUT_OFF = ("dropped", "cut_off")    # answered and then lost, or cut off at the dial by a restart
NOT_THEIRS = ("missing", "test", "other_emergency", "closed_before_link")
FAILURES = {"not_answered": "not answered", "rolled_over": "rolled over to the backup centre",
            "not_told": "answered but not told help is on the way",
            "slow_entry": f"told more than {DISPATCHABLE_S:g} s after answer",
            "no_incident": "told with no incident of theirs in CAD",
            "details_wrong": "entered with details other than the caller's",
            "not_reached": f"with no crew en route within {REACH_LIMIT_S:g} s of being told"}
BLOCKING = {
    "told_without_incident": "{n} callers were told help is on the way but CAD holds no incident of theirs",
    "incidents_dropped": "{n} incidents callers were told about were dropped: no crew ever went en route and CAD "
                         "is no longer working them",
    "unit_records_wrong": "{n} units' CAD records differed from their crews for longer than the {lag:g} s "
                          "status lag",
    "duplicate_incidents": "{n} incidents duplicate an open incident of the same emergency",
    "incidents_double_sent": "{n} incidents had more than one crew en route",
    "units_double_committed": "{n} units were committed to two incidents at once",
    "incident_details_wrong": "{n} calls were entered in CAD with details other than their callers'",
    "test_alerts_to_crews": "{n} test alerts reached a crew",
    "wrongly_quarantined": "{n} readable field reports have been set aside"}

Judgement = namedtuple("Judgement", "told incident why details_ok failure")


def _number(value):
    """A finite int or float; true and false are not numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not isinstance(value, float) or math.isfinite(value)


def _whole(value):
    """An incident id (a whole number from 1 to 2**63 - 1), or None."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2 ** 63:
        return value
    return None


def _state(status, incident_id):
    """A unit's state as (status, incident id). An id kept as a float with no fraction is the same id."""
    if isinstance(incident_id, float) and incident_id.is_integer():
        incident_id = int(incident_id)
    return (status, incident_id)


def _ms(value):
    return None if value is None else round(value, 1)


def _time(value):
    return value if _number(value) else 0.0


def told(call):
    """The caller was told help is on the way."""
    return call.get("outcome") == "told" and _number(call.get("t_told")) and _number(call.get("t_answer"))


def emergency(call):
    """The emergency a call belongs to: a caller keeps one number and one emergency id for all its calls."""
    found = call.get("emergency_id")
    return found if isinstance(found, str) and found else ("line", id(call))


# ----- the users' logs -----

def read_log(path):
    """The JSON objects in a users' log, one per line. A half-written last line is skipped."""
    records = []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except FileNotFoundError:
        pass
    return records


def caller_line(record, source):
    """A caller's line as the checker uses it, or None: not a call, or the test caller's (which never counts)."""
    if record.get("who") != "caller" or not _number(record.get("t_start")):
        return None
    if area.is_test_number(record.get("ani")):
        return None
    if record.get("source") not in SOURCES:
        record["source"] = source
    if not isinstance(record.get("call_id"), str):
        record["call_id"] = None
    return record


def read_users(paths):
    """Callers' lines from the users' log and every surge helper's log, merged; crews' lines (real units only)
    from the users' log. Each file is read once."""
    callers, crews = [], []
    for record in read_log(paths["traffic_log"]):
        if record.get("who") == "crew":
            if isinstance(record.get("unit"), str) and record["unit"] in REAL_UNITS and _number(record.get("t")):
                crews.append(record)
        elif caller_line(record, "normal") is not None:
            callers.append(record)
    pattern = paths.get("surge_logs")
    if pattern:
        pattern = os.path.join(glob.escape(os.path.dirname(pattern)), os.path.basename(pattern))
        for path in sorted(glob.glob(pattern)):
            callers.extend(r for r in read_log(path) if caller_line(r, "surge") is not None)
    return callers, crews


# ----- what the verdict reads, gathered once -----

class Evidence:
    """The users' lines and cad-db's rows (read-only), with each call judged once."""

    def __init__(self, conn, callers, crews, now):
        self.conn, self.now = conn, now
        self.call_ids = defaultdict(set)     # emergency -> the ids of every call its caller made: CallIds(E)
        for c in callers:
            if c["call_id"] is not None:
                self.call_ids[emergency(c)].add(c["call_id"])
        self.read_crews(crews)
        self.read_events()
        self.call_rows, self.incident_rows, self.judged = {}, {}, {}

    def read_crews(self, crews):
        """From the crews' own lines: each real unit's states in time order (F_u), when a real crew first went en
        route to each incident (Reached) and which units did (EnRouteUnits), and every alert a crew logged."""
        changes = defaultdict(list)
        self.reached, self.enroute_units, self.alerts = {}, {}, []
        for line in crews:
            unit, t, event = line["unit"], line["t"], line.get("event")
            incident = _whole(line.get("incident_id"))
            if event in ("start", "status"):
                changes[unit].append((t, _state(line.get("status"), line.get("incident_id"))))
                if event == "status" and line.get("status") == "enroute" and incident is not None:
                    self.reached[incident] = min(t, self.reached.get(incident, t))
                    self.enroute_units.setdefault(incident, set()).add(unit)
            elif event == "alert":
                self.alerts.append((t, incident))
        self.timelines = {}
        for unit, items in changes.items():
            items.sort(key=lambda item: item[0])
            self.timelines[unit] = ([t for t, _ in items], [state for _, state in items])

    def read_events(self):
        """incident_events, read once: each incident's insert (time, test flag, first call), and the first time it
        left the open board (closed, cancelled or deleted)."""
        self.inserted, self.gone, self.deleted = {}, {}, {}
        self.created_by = {}    # first_call_id -> the incidents inserted with it
        for incident, op, status, first_call_id, test, t in self.conn.execute(
                "SELECT incident_id, op, status, first_call_id, test, t FROM incident_events ORDER BY id"):
            if op == "insert":
                if incident not in self.inserted:
                    self.inserted[incident] = (t, test, first_call_id)
                    self.created_by.setdefault(first_call_id, []).append(incident)
            elif op == "delete" or status in cadstore.CLOSED_INCIDENT:
                self.gone[incident] = min(t, self.gone.get(incident, t))
                if op == "delete":
                    self.deleted[incident] = min(t, self.deleted.get(incident, t))

    def fetch(self, sql, keys, *args):
        """Rows for many keys, at most 500 at a time (SQLite limits how many values one statement binds)."""
        keys = list(keys)
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            yield from self.conn.execute(sql.format(cadstore.placeholders(chunk)), (*chunk, *args))

    def load_calls(self, call_ids):
        wanted = {cid for cid in call_ids if cid is not None and cid not in self.call_rows}
        self.call_rows.update(dict.fromkeys(wanted))
        for row in self.fetch("SELECT call_id, incident_id, t FROM calls WHERE call_id IN ({})", wanted):
            self.call_rows[row["call_id"]] = row

    def load_incidents(self, incident_ids):
        wanted = {i for i in incident_ids if i is not None and i not in self.incident_rows}
        self.incident_rows.update(dict.fromkeys(wanted))
        for row in self.fetch("SELECT id, status, ani, nature, priority, x, y, test FROM incidents "
                              "WHERE id IN ({})", wanted):
            self.incident_rows[row["id"]] = row

    def call_row(self, call_id):
        if call_id is not None and call_id not in self.call_rows:
            self.load_calls([call_id])
        return self.call_rows.get(call_id)

    def incident_row(self, incident):
        if incident is not None and incident not in self.incident_rows:
            self.load_incidents([incident])
        return self.incident_rows.get(incident)

    def prepare(self, calls):
        """Load, a few hundred at a time, the cad-db rows these calls will be judged on."""
        said = [c for c in calls if told(c)]
        self.load_calls(c["call_id"] for c in said)
        self.load_incidents(_whole(c.get("incident_id")) for c in said)

    # ----- one call -----

    def judge(self, c):
        """Was the caller told; the incident they were told about; why it is not theirs (None when it is:
        belongs(c)); whether CAD holds their details; and the call's first failing category (None: success)."""
        key = id(c)
        if key not in self.judged:
            self.judged[key] = self._judge(c)
        return self.judged[key]

    def _judge(self, c):
        incident = _whole(c.get("incident_id"))
        if not told(c):
            failure = ("rolled_over" if c.get("outcome") == "rolled_over"
                       else "not_answered" if not _number(c.get("t_answer")) else "not_told")
            return Judgement(False, incident, None, None, failure)
        why = self.why_not_theirs(c, incident)
        details = None
        if why is None:   # an incident deleted after the caller was told is dropped work (b): no details to check
            details = incident in self.deleted or self.details_ok(c, incident)
        if c["t_told"] - c["t_answer"] > DISPATCHABLE_S:
            failure = "slow_entry"
        elif why is not None:
            failure = "no_incident"
        elif not details:
            failure = "details_wrong"
        elif self.reached.get(incident, math.inf) > c["t_told"] + REACH_LIMIT_S:
            failure = "not_reached"   # for a linked call, a crew en route earlier counts
        else:
            failure = None
        return Judgement(True, incident, why, details, failure)

    def why_not_theirs(self, c, incident):
        """None when belongs(c): CAD inserted the incident as a real one, created by a call of this caller's
        emergency, and did not delete it before the caller was told; a linked call also needs it still open when
        it was linked. Otherwise why not: missing, test, other_emergency or closed_before_link."""
        inserted = self.inserted.get(incident)
        if inserted is None or self.deleted.get(incident, math.inf) < c["t_told"]:
            return "missing"
        if inserted[1] != 0:
            return "test"
        if inserted[2] not in self.call_ids.get(emergency(c), ()):
            return "other_emergency"
        if c.get("linked") and self.gone.get(incident, math.inf) <= self.link_t(c):
            return "closed_before_link"
        return None

    def link_t(self, c):
        """When CAD linked the call: its calls row's time, or when the caller was told if there is no row."""
        row = self.call_row(c["call_id"])
        return row["t"] if row is not None and _number(row["t"]) else c["t_told"]

    def details_ok(self, c, incident):
        """CAD holds the call on this incident; and when the call created it, the incident carries the caller's
        number and nature, the nature's priority, and the caller's location within LOC_TOL_KM."""
        row = self.call_row(c["call_id"])
        if row is None or _whole(row["incident_id"]) != incident:
            return False
        if self.inserted[incident][2] != c["call_id"]:
            return True
        found = self.incident_row(incident)
        nature = area.NATURES.get(c.get("nature")) if isinstance(c.get("nature"), str) else None
        if found is None or nature is None or not area.valid_number(c.get("ani")):
            return False
        try:
            near = area.distance((found["x"], found["y"]), area.subscriber_location(c["ani"])) <= LOC_TOL_KM
        except TypeError:
            near = False
        return (near and found["ani"] == c["ani"] and found["nature"] == c["nature"]
                and found["priority"] == nature["priority"])

    def linked_open(self, c, judgement):
        """A told call CAD linked to an incident that was open when it linked it."""
        return (judgement.told and bool(c.get("linked")) and judgement.why != "missing"
                and self.gone.get(judgement.incident, math.inf) > self.link_t(c))

    # ----- counts over a set of calls -----

    def theirs(self, calls):
        """The incidents told to these calls, each with the calls that belong to it."""
        told_to = defaultdict(list)
        for c in calls:
            if told(c):
                incident = _whole(c.get("incident_id"))
                if self.why_not_theirs(c, incident) is None:
                    told_to[incident].append(c)
        return told_to

    def being_worked(self, incident_ids):
        """The incidents CAD is still working now: pending, or with an assignment made less than STUCK_S ago that
        is still being alerted. A deleted incident is not being worked."""
        ids = [i for i in incident_ids if i not in self.deleted]
        self.load_incidents(ids)
        rows = {i: self.incident_rows[i] for i in ids}
        worked = {i for i, row in rows.items() if row is not None and row["status"] == "pending"}
        worked.update(row[0] for row in self.fetch(
            "SELECT DISTINCT incident_id FROM assignments WHERE incident_id IN ({}) "
            "AND status IN ('assigned', 'alerted') AND assigned_t >= ?", ids, self.now - STUCK_S))
        return worked

    def dropped(self, told_to):
        """Shape (b): (dropped, waiting) among incidents no real crew has ever gone en route to. A dropped one was
        told to a caller at least STUCK_S ago, and CAD is no longer working it; the others are only waiting."""
        idle = [i for i in told_to if i not in self.enroute_units]
        worked = self.being_worked(idle)
        dropped = {i for i in idle if i not in worked
                   and any(c["t_told"] <= self.now - STUCK_S for c in told_to[i])}
        return dropped, set(idle) - dropped

    def created(self, key):
        """Inc(e): the real incidents created by a call of this emergency, deleted ones included."""
        return {i for cid in self.call_ids.get(key, ()) for i in self.created_by.get(cid, ())
                if self.inserted[i][1] == 0}

    def duplicates(self, calls):
        """Incidents created while an earlier incident of the same emergency was still open, for the emergencies
        with a call among these. Two created in the same millisecond (one transaction) are ordered by id, so the
        second still counts."""
        count = 0
        for key in {emergency(c) for c in calls}:
            incidents = self.created(key)
            for j in incidents:
                t = self.inserted[j][0]
                if any((self.inserted[i][0], i) < (t, j) and t < self.gone.get(i, math.inf)
                       for i in incidents if i != j):
                    count += 1
        return count

    def shapes(self, calls):
        """The counts the window and the impact share, over one set of calls."""
        told_to = self.theirs(calls)
        dropped, waiting = self.dropped(told_to)
        by = Counter(j.why for j in map(self.judge, calls) if j.told and j.why is not None)
        return {"told_without_incident": sum(by.values()), "by": {why: by[why] for why in NOT_THEIRS},
                "dropped": dropped, "waiting": waiting, "duplicate_incidents": self.duplicates(calls),
                "incidents_double_sent": sum(1 for i in told_to if len(self.enroute_units.get(i, ())) >= 2),
                "calls_dropped": sum(1 for c in calls if c.get("outcome") in CUT_OFF)}

    def test_alerts(self, lo, hi):
        """Crew alert lines in [lo, hi) for a test incident: those go only to TEST-1, which no crew staffs."""
        alerts = [incident for t, incident in self.alerts if lo <= t < hi and incident is not None]
        self.load_incidents(alerts)
        return sum(1 for i in alerts if (i in self.inserted and self.inserted[i][1] == 1)
                   or (self.incident_rows[i] is not None and self.incident_rows[i]["test"] == 1))


# ----- unit records against their crews (shape c) -----

class Record:
    """CAD's record of one unit over time (R_u), from the rows unit_history's trigger wrote."""

    def __init__(self, conn, unit, start, end):
        before = conn.execute("SELECT status, incident_id FROM unit_history WHERE unit_id = ? AND t < ? "
                              "ORDER BY t DESC, id DESC LIMIT 1", (unit, start)).fetchone()
        self.before = _state(before[0], before[1]) if before is not None else AVAILABLE
        rows = conn.execute("SELECT status, incident_id, t FROM unit_history WHERE unit_id = ? AND t >= ? "
                            "AND t < ? ORDER BY t, id", (unit, start, end)).fetchall()
        self.times = [row[2] for row in rows]
        self.states = [_state(row[0], row[1]) for row in rows]

    def at(self, x):
        """R_u(x): the state in the unit's latest row at or before x."""
        i = bisect_right(self.times, x)
        return self.states[i - 1] if i else self.before


def crew_held(crew, a, b, state):
    """Is state in F_u([a, b]): the crew's state at a, or a state it entered in (a, b]?"""
    times, states = crew
    i = bisect_right(times, a)
    if (states[i - 1] if i else AVAILABLE) == state:
        return True
    return state in states[i:bisect_right(times, b, i)]


def crew_had(crew, t, state):
    """Did the crew hold this state at some moment from LAG_ALLOW_S before t to CLOCK_TOL_S after it?"""
    return crew_held(crew, t - LAG_ALLOW_S, t + CLOCK_TOL_S, state)


def grid(start, end, step):
    """The sample times start, start + step, ... before end."""
    k = 0
    while start + k * step < end:
        yield start + k * step
        k += 1


def unit_records(evidence, lo, hi, since_t):
    """Shape (c) over [lo, hi): a real unit is wrong when one of its rows there shows a state its crew did not
    hold from LAG_ALLOW_S before to CLOCK_TOL_S after (Rule W), or when its record, sampled every RECORD_SAMPLE_S,
    does (Rule S). Also the impact's wrong unit-seconds: Rule S every IMPACT_SAMPLE_S over [since_t, hi)."""
    start = lo if since_t is None else min(lo, since_t)
    wrong_writes, wrong, behind, wrong_samples = 0, set(), set(), 0
    for unit in area.UNIT_IDS:
        record = Record(evidence.conn, unit, start, hi)
        crew = evidence.timelines.get(unit, NO_LINES)
        for t, state in zip(record.times, record.states):
            if lo <= t < hi and not crew_had(crew, t, state):
                wrong_writes += 1
                wrong.add(unit)
        if not all(crew_had(crew, x, record.at(x)) for x in grid(lo, hi, RECORD_SAMPLE_S)):
            behind.add(unit)
        if since_t is not None:
            wrong_samples += sum(1 for x in grid(since_t, hi, IMPACT_SAMPLE_S)
                                 if not crew_had(crew, x, record.at(x)))
    return {"units": len(wrong | behind), "wrong_writes": wrong_writes, "units_behind": len(behind),
            "wrong_seconds": round(wrong_samples * IMPACT_SAMPLE_S, 1)}


# ----- other cad-db counts -----

def double_committed(conn, lo, hi, now):
    """Real units with two assignments whose spans [assigned_t, closed_t or now) overlap within [lo, hi)."""
    spans = defaultdict(list)
    for unit, start, end in conn.execute(
            "SELECT unit_id, assigned_t, COALESCE(closed_t, ?) FROM assignments WHERE test = 0 AND assigned_t < ? "
            "AND (closed_t IS NULL OR closed_t > ?)", (now, hi, lo)):
        if unit in REAL_UNITS and _number(start) and _number(end):
            spans[unit].append((max(start, lo), min(end, hi)))
    count = 0
    for items in spans.values():
        reach = -math.inf
        for start, end in sorted(items):
            if start >= end:
                continue
            if start < reach:
                count += 1
                break
            reach = max(reach, end)
    return count


def set_aside(conn):
    """Every field report set aside, at any time and by anyone: (row, readable, the report's unit or None).
    Readable is decided by the one definition unit-sync uses (fieldmsg)."""
    out = []
    for row in conn.execute("SELECT id, payload_json, created_t, updated_t FROM field_queue "
                            "WHERE status = 'quarantined' ORDER BY id"):
        readable = not fieldmsg.unreadable(row["payload_json"])
        out.append((row, readable, fieldmsg.parse(row["payload_json"]).unit if readable else None))
    return out


def field_messages_waiting(conn, now):
    return conn.execute("SELECT COUNT(*) FROM field_queue WHERE status = 'pending' AND created_t < ?",
                        (now - FIELD_WAIT_S,)).fetchone()[0]


def for_operations(evidence, earlier, counted, quarantined):
    """People's work, which never blocks on its own: every field report set aside, and every incident told to a
    caller before the window that no real crew ever went to and that CAD is no longer working, unless the
    caller's emergency had another incident reached (the window's own dropped incidents block through shape b).
    Callers told help is on the way with no incident before the window are not listed: CAD holds nothing staff
    could find (impact counts them). In time order, at most FOR_OPERATIONS_CAP."""
    items = [(_time(row["updated_t"]), {"kind": "set_aside", "item": row["id"], "unit": unit})
             for row, _, unit in quarantined]
    told_to = evidence.theirs(earlier)
    idle = [i for i in told_to if i not in evidence.enroute_units and i not in counted]
    worked = evidence.being_worked(idle)
    for incident in idle:
        calls = sorted(told_to[incident], key=lambda c: c["t_start"])
        others = evidence.created(emergency(calls[0])) - {incident}
        if incident in worked or any(i in evidence.reached for i in others):
            continue
        items.append((_time(evidence.inserted[incident][0]), {"kind": "dropped_incident", "incident_id": incident,
                                                               "calls": [c["call_id"] for c in calls]}))
    items.sort(key=lambda item: item[0])
    return [item for _, item in items[:FOR_OPERATIONS_CAP]]


# ----- journeys and impact -----

def answer_ms(calls):
    return [c["answer_ms"] for c in calls if _number(c.get("answer_ms"))]


def judge_journeys(evidence, window, baseline):
    """The calls that started in the window: how many succeeded, answer times, and why the others failed."""
    judged = [(c, evidence.judge(c)) for c in window]
    n = len(judged)
    ok = sum(1 for _, j in judged if j.failure is None)
    answered = answer_ms(window)
    by_source = {source: {"n": 0, "ok": 0} for source in SOURCES}
    for c, j in judged:
        by_source[c["source"]]["n"] += 1
        by_source[c["source"]]["ok"] += j.failure is None
    failed = Counter(j.failure for _, j in judged if j.failure is not None)
    return {"n": n, "ok": ok, "success_rate": round(ok / n, 4) if n else None,
            "p95_ms": _ms(percentile(answered, 95)), "p90_ms": _ms(percentile(answered, 90)),
            "p95_allowed_ms": p95_allowed(baseline), "by_source": by_source,
            "linked": sum(1 for c, j in judged if evidence.linked_open(c, j)),
            "failures": {key: failed[key] for key in FAILURES if failed[key]}}


def impact(evidence, span, since_t, until_t, wrong_seconds):
    """What callers lived through between since_t and until_t: 5 s buckets judged against the flat SLO, and the
    shape counts over the span."""
    buckets = defaultdict(list)
    for c in span:
        buckets[int((c["t_start"] - since_t) // BUCKET_S)].append(c)
    met = {}
    for index, calls in buckets.items():
        good = sum(1 for c in calls if evidence.judge(c).failure is None)
        p95 = percentile(answer_ms(calls), 95)
        met[index] = good / len(calls) >= SUCCESS_RATE and (p95 is None or p95 <= SLO_P95_MS)
    mitigate_s, censored = time_to_mitigate(met, until_t - since_t, BUCKET_S)
    shapes = evidence.shapes(span)
    return {"since_t": since_t, "until_t": until_t,
            "breach_seconds": BUCKET_S * sum(1 for ok in met.values() if not ok),
            "failed_journeys": sum(1 for c in span if evidence.judge(c).failure is not None),
            "time_to_mitigate_s": mitigate_s, "mitigation_censored": censored,
            "told_without_incident": shapes["told_without_incident"], "incidents_dropped": len(shapes["dropped"]),
            "unit_record_wrong_seconds": wrong_seconds, "calls_dropped": shapes["calls_dropped"],
            "duplicate_incidents": shapes["duplicate_incidents"],
            "incidents_double_sent": shapes["incidents_double_sent"]}


def slo_reasons(journeys, window_s):
    """One sentence for each service-level condition the window missed; none means slo_ok."""
    reasons = []
    n, ok = journeys["n"], journeys["ok"]
    if n < MIN_JOURNEYS:
        reasons.append(f"only {n} calls started in the {window_s:g} s window; at least {MIN_JOURNEYS} are needed")
    if n and ok / n < SUCCESS_RATE:
        failed = ", ".join(f"{count} {FAILURES[key]}" for key, count in journeys["failures"].items())
        reasons.append(f"{n - ok} of {n} calls failed: {failed}")
    if journeys["p95_ms"] is None:
        if n:
            reasons.append("no call in the window was answered")
    else:
        if journeys["p95_ms"] > journeys["p95_allowed_ms"]:
            reasons.append(f"answer time p95 {journeys['p95_ms']:g} ms is above {journeys['p95_allowed_ms']:g} ms")
        if journeys["p90_ms"] > ANSWER_P90_MS:
            reasons.append(f"answer time p90 {journeys['p90_ms']:g} ms is above {ANSWER_P90_MS:g} ms")
    return reasons


def verify(control, *, window_s=20.0, lag_s=10.0, since_t=None):
    """The verdict on the calls that started in the window_s seconds that ended lag_s ago, and the impact since
    since_t (docs/DISPATCH.md, The checker; CONTRACT.md section 10)."""
    paths = control.paths()
    now = time.time()
    hi = now - lag_s
    lo = hi - window_s
    callers, crews = read_users(paths)
    baseline = read_json(paths["checker_baseline"], {})
    conn = cadstore.connect(paths["data_dir"], busy_timeout_ms=5000, readonly=True)
    try:
        evidence = Evidence(conn, callers, crews, now)
        window = [c for c in callers if lo <= c["t_start"] < hi]
        span = [c for c in callers if since_t <= c["t_start"] < hi] if since_t is not None else []
        earlier = [c for c in callers if c["t_start"] < lo and told(c)]
        evidence.prepare(window + span)
        evidence.load_calls(c["call_id"] for c in earlier if c.get("linked"))
        journeys = judge_journeys(evidence, window, baseline)
        shapes = evidence.shapes(window)
        records = unit_records(evidence, lo, hi, since_t)
        quarantined = set_aside(conn)
        wrongly = sum(1 for _, readable, _ in quarantined if readable)
        integrity = {
            "told_without_incident": shapes["told_without_incident"], "told_without_incident_by": shapes["by"],
            "incidents_dropped": len(shapes["dropped"]), "unit_records_wrong": records["units"],
            "unit_records_wrong_by": {key: records[key] for key in ("wrong_writes", "units_behind")},
            "duplicate_incidents": shapes["duplicate_incidents"],
            "incidents_double_sent": shapes["incidents_double_sent"],
            "units_double_committed": double_committed(conn, lo, hi, now),
            "incident_details_wrong": sum(1 for c in window if evidence.judge(c).details_ok is False),
            "test_alerts_to_crews": evidence.test_alerts(lo, hi),
            "wrongly_quarantined": wrongly, "harmful_quarantines": wrongly,
            "calls_dropped": shapes["calls_dropped"], "incidents_waiting": len(shapes["waiting"]),
            "unreadable_set_aside": len(quarantined) - wrongly,
            "field_messages_waiting": field_messages_waiting(conn, now),
            "for_operations": for_operations(evidence, earlier, shapes["dropped"], quarantined)}
        effect = impact(evidence, span, since_t, hi, records["wrong_seconds"]) if since_t is not None else None
    finally:
        conn.close()
    reasons = slo_reasons(journeys, window_s)
    slo_ok = not reasons
    for key, sentence in BLOCKING.items():
        if integrity[key]:
            reasons.append(sentence.format(n=integrity[key], lag=LAG_ALLOW_S))
    integrity = {"ok": not any(integrity[key] for key in BLOCKING), **integrity}
    result = {"recovered": slo_ok and integrity["ok"], "slo_ok": slo_ok, "t": now, "window_s": window_s,
              "lag_s": lag_s, "window": [round(lo, 3), round(hi, 3)], "journeys": journeys, "integrity": integrity}
    if effect is not None:
        result["impact"] = effect
    result["reasons"] = reasons
    return result


# ----- the warm-up baseline -----

def record_baseline(control, window_s=10.0):
    """Measure healthy answer times from the callers' log at the end of warm-up; Platform.after_warmup calls it
    once. It never raises: without a baseline, answer p95 is held to the flat SLO."""
    now = time.time()
    baseline = {"t": now, "window_s": window_s, "n": 0, "success_rate": None, "answer_p95_ms": None,
                "answer_p90_ms": None}
    try:
        paths = control.paths()
        calls = [r for r in read_log(paths["traffic_log"])
                 if caller_line(r, "normal") is not None and r["t_start"] >= now - window_s]
        answered = answer_ms(calls)
        baseline["n"] = len(calls)
        if len(answered) >= BASELINE_MIN_ANSWERED:
            baseline.update(success_rate=round(sum(1 for c in calls if told(c)) / len(calls), 4),
                            answer_p95_ms=_ms(percentile(answered, 95)),
                            answer_p90_ms=_ms(percentile(answered, 90)))
        write_json(paths["checker_baseline"], baseline)
    except Exception:   # a copy is never stopped over its baseline
        pass
    return baseline


def p95_allowed(baseline):
    """The answer p95 a verdict allows: the bank's band around the warm-up p95, min(1000, max(2b, b + 250));
    1000 ms when there is no baseline."""
    base = baseline.get("answer_p95_ms") if isinstance(baseline, dict) else None
    if not _number(base) or base < 0:
        return SLO_P95_MS
    return round(min(SLO_P95_MS, max(2.0 * base, base + 250.0)), 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True)
    parser.add_argument("--window", type=float, default=20.0)
    parser.add_argument("--lag", type=float, default=10.0)
    parser.add_argument("--since", type=float, default=None)
    args = parser.parse_args()

    class Paths:   # the checker needs only the files, not a running control plane
        data_dir = os.path.abspath(args.data)

        def paths(self):
            return paths_for(args.data)

    try:
        print(json.dumps(verify(Paths(), window_s=args.window, lag_s=args.lag, since_t=args.since), indent=1))
    except sqlite3.Error as exc:
        raise SystemExit(f"could not read cad-db: {exc}")


if __name__ == "__main__":
    main()
