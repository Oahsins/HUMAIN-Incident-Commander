"""The dispatch centre's test users: the public who call 9-1-1, and the crews of the 20 units.

They run as one process (spec.py traffic_argv):

    python -m targets.dispatch.people --data runs/dispatch-9500 --port 9500 --mdt-port 9501 --seed 0

Callers arrive in an open loop, a new emergency every 0.35-0.55 s whatever the centre is doing, each in its own
thread. A call rings (POST /dial) until a call-taker answers, the caller gives the location by voice if the one
read back is missing or wrong, talks, and reports (POST /calls/<call_id>/report). A caller who is not told help
is on the way redials, as real callers do, and one told caller in ten calls back.

Crews take station alerts from both alerting inboxes, turn out, drive, work on scene and clear. One scheduler
moves all 20; their terminals report each new status, and a heartbeat every second, to CAD's /mdt.

Everything they live through goes into people.jsonl (docs/DISPATCH.md, Users), which only the checker reads:
one caller line per call, and one crew line per crew event, written before the terminal's report leaves. The
log holds ids, codes and the made-up phone numbers only: never what a caller said, never a location.
"""

import argparse
import http.client
import json
import math
import os
import random
import threading
import time
from collections import deque
from urllib.parse import quote, urlsplit

from ic.kit import net
from targets.dispatch import area, fieldmsg
from targets.dispatch.control import paths_for

# Callers (centre clock, 1:20).
ARRIVAL_GAP_S = (0.35, 0.55)    # between everyday emergencies: about 2.2 per second
DIAL_TIMEOUT_S = 3.5            # above rollover_s 2.5 plus the 0.5 s location lookup
REPORT_TIMEOUT_S = 2.0
LOCATION_TOL_KM = 0.05          # a location read back further off than this is corrected by the caller
VERBAL_S = (1.2, 2.0)           # giving the location by voice
TALK_S = (0.8, 1.6)
CALLBACK_TALK_S = (0.2, 0.3)
REDIAL_AFTER = ("refused", "cut_off", "not_answered", "dropped", "not_entered", "timeout")
REDIAL_GAP_S = (0.3, 0.6)
REDIAL_WINDOW_S = 7.0           # no redial once the emergency's first dial is this old
MAX_CALLS = 3                   # the first call and its redials
CALLBACK_SHARE = 0.10
CALLBACK_GAP_S = (0.2, 0.5)
MIXES = {"normal": area.REAL_NATURES, "medical": area.MEDICAL_NATURES, "fire": area.FIRE_NATURES}

# Crews (field clock, about 1:300).
TICK_S = 0.05
TURNOUT_S = (0.2, 0.4)
ON_SCENE_S = (0.6, 1.2)
HEARTBEAT_S = 1.0
UPLINKS = 4                     # unit k always sends through uplink k mod 4, so its reports stay in order
QUEUE_MAX = 200
REPORT_MAX_AGE_S = 2.0          # older than this when its turn comes: dropped (the next heartbeat has the state)
MDT_TIMEOUT_S = 1.0
READ_MAX = 1 << 20              # bytes of an inbox read per tick

HEADERS = {"Content-Type": "application/json", "Connection": "close"}


def clock():
    return time.time()


def pause(seconds, stop_event=None):
    """Wait. With a stop_event, return True as soon as it is set (the caller then places no further call)."""
    if stop_event is None:
        time.sleep(seconds)
        return False
    return stop_event.wait(seconds)


class Log:
    """The users' log: one JSON line per record, from any thread, each written whole and flushed at once."""

    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.lock = threading.Lock()
        self.handle = open(path, "a", encoding="utf-8")

    def write(self, record):
        line = json.dumps(record) + "\n"
        with self.lock:
            self.handle.write(line)
            self.handle.flush()

    def close(self):
        with self.lock:
            self.handle.close()


# ----- a small HTTP client that tells a refused connection from one cut off -----

def post_json(url, payload, timeout):
    """POST a JSON body and return (status, body). Raises net.CallError, classified by exception type: refused
    (no connection could be made), reset (the connection broke after it was made, as when the other side
    restarts), timeout, bad_response (not HTTP, or not JSON) or http (a 4xx or 5xx answer)."""
    parts = urlsplit(url)
    deadline = time.monotonic() + timeout
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)
    try:
        try:
            conn.connect()
        except TimeoutError:
            raise net.CallError("timeout", detail=f"no answer within {timeout}s") from None
        except OSError as exc:
            raise net.CallError("refused", detail=type(exc).__name__) from None
        try:
            conn.sock.settimeout(_left(deadline))
            conn.request("POST", parts.path, body=json.dumps(payload).encode("utf-8"), headers=HEADERS)
            conn.sock.settimeout(_left(deadline))
            response = conn.getresponse()
            status, raw = response.status, response.read()
        except TimeoutError:
            raise net.CallError("timeout", detail=f"no answer within {timeout}s") from None
        except (ConnectionError, http.client.IncompleteRead) as exc:   # reset, aborted, broken pipe, hung up
            raise net.CallError("reset", detail=type(exc).__name__) from None
        except http.client.HTTPException as exc:
            raise net.CallError("bad_response", detail=type(exc).__name__) from None
        except OSError as exc:
            raise net.CallError("reset", detail=type(exc).__name__) from None
    finally:
        conn.close()
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = None
    if 200 <= status < 300:
        if body is None:
            raise net.CallError("bad_response", status, detail="answer was not JSON")
        return status, body
    body = body if isinstance(body, dict) else {}
    raise net.CallError("http", status, body, str(body.get("error", ""))[:200])


def _left(deadline):
    return max(0.001, deadline - time.monotonic())


# ----- callers -----

def dial_outcome(exc):
    """(outcome, status) for a dial that failed with net.CallError exc (docs/DISPATCH.md, caller outcomes)."""
    if exc.kind == "http":
        status = exc.status or 0
        if status == 503 and isinstance(exc.body, dict) and exc.body.get("error") == "rolled over":
            return "rolled_over", status
        return ("not_answered" if status >= 500 else "rejected"), status
    if exc.kind == "refused":
        return "refused", "refused"
    if exc.kind == "reset":
        return "cut_off", "reset"
    if exc.kind == "timeout":
        return "timeout", "timeout"
    return "not_answered", exc.kind      # bad_response: nobody really answered


def report_outcome(exc):
    """(outcome, status) for a report that failed with net.CallError exc, after the call was answered."""
    if exc.kind == "http":
        status = exc.status or 0
        if status == 404:
            return "dropped", status
        return ("not_entered" if status >= 500 else "rejected"), status
    if exc.kind in ("refused", "reset"):
        return "dropped", exc.kind
    if exc.kind == "timeout":
        return "timeout", "timeout"
    return "not_entered", exc.kind       # bad_response: the caller was not told


def place_call(post, base_url, rng, source, emergency_id, kind, attempt, ani, nature, narrative):
    """One call from ring to end, as a caller lives it. Returns its caller line (docs/DISPATCH.md, Users)."""
    line = {"who": "caller", "source": source, "emergency_id": emergency_id, "kind": kind, "attempt": attempt,
            "call_id": None, "ani": ani, "nature": nature, "t_start": round(clock(), 3), "t_answer": None,
            "answer_ms": None, "location": None, "t_told": None, "incident_id": None, "linked": None,
            "outcome": None, "status": None, "t_end": None}
    started = time.perf_counter()
    try:
        _, answer = post(f"{base_url}/dial", {"ani": ani, "test": 0}, DIAL_TIMEOUT_S)
    except net.CallError as exc:
        return _ended(line, *dial_outcome(exc))
    call_id = answer.get("call_id") if isinstance(answer, dict) else None
    if not (isinstance(call_id, str) and 0 < len(call_id) <= 64):
        return _ended(line, "not_answered", "bad_response")
    line.update(call_id=call_id, t_answer=round(clock(), 3),
                answer_ms=round((time.perf_counter() - started) * 1000, 1))
    where = area.subscriber_location(ani)
    report = {"nature": nature, "narrative": narrative}
    if _near(answer.get("location"), where):
        line["location"] = "ali"
    else:   # the location read back is missing or wrong: the caller says where they are
        line["location"] = "verbal"
        pause(rng.uniform(*VERBAL_S))
        report["location"] = {"x": where[0], "y": where[1]}
    pause(rng.uniform(*(CALLBACK_TALK_S if kind == "callback" else TALK_S)))
    try:
        status, told = post(f"{base_url}/calls/{quote(call_id, safe='')}/report", report, REPORT_TIMEOUT_S)
    except net.CallError as exc:
        return _ended(line, *report_outcome(exc))
    incident_id = told.get("incident_id") if isinstance(told, dict) else None
    if not (isinstance(told, dict) and told.get("told") is True and _incident_id(incident_id)):
        return _ended(line, "not_entered", "bad_response")
    line.update(t_told=round(clock(), 3), incident_id=incident_id, linked=told.get("linked") is True)
    return _ended(line, "told", status)


def _ended(line, outcome, status):
    line.update(outcome=outcome, status=status, t_end=round(clock(), 3))
    return line


def run_emergency(log, base_url, rng, source, emergency_id, ani, nature, narrative, stop_event=None, post=None):
    """One emergency from its first ring to the end: the first call, any redials, and sometimes a callback.

    A caller who is not told redials (same number, new call) 0.3-0.6 s after refused, cut_off, not_answered,
    dropped, not_entered or timeout, while the emergency's first dial is under 7.0 s old and it has made fewer
    than 3 calls; never after rolled_over (the backup centre has the call), rejected, or being told. One told
    emergency in ten calls back 0.2-0.5 s later with nothing new to say. Once stop_event is set no further call
    starts; the call in progress finishes. Writes one caller line per call and returns the outcomes in order.
    """
    post = post or post_json
    outcomes = []
    first_dial_t = clock()
    kind = "first"
    while True:
        line = place_call(post, base_url, rng, source, emergency_id, kind, len(outcomes) + 1, ani, nature,
                          narrative)
        log.write(line)
        outcomes.append(line["outcome"])
        if line["outcome"] not in REDIAL_AFTER or len(outcomes) >= MAX_CALLS:
            break
        if pause(rng.uniform(*REDIAL_GAP_S), stop_event) or clock() - first_dial_t >= REDIAL_WINDOW_S:
            break
        kind = "redial"
    if outcomes[-1] == "told" and rng.random() < CALLBACK_SHARE:
        if not pause(rng.uniform(*CALLBACK_GAP_S), stop_event):
            line = place_call(post, base_url, rng, source, emergency_id, "callback", len(outcomes) + 1, ani,
                              nature, "")
            log.write(line)
            outcomes.append(line["outcome"])
    return outcomes


def pick_nature(rng, mix="normal"):
    codes = MIXES[mix]
    return rng.choices(codes, weights=[area.NATURES[code]["weight"] for code in codes])[0]


def pick_narrative(rng, nature):
    return rng.choice(area.NATURES[nature]["narratives"])


def caller_loop(log, base_url, seed, stop):
    """Everyday callers: a new emergency every 0.35-0.55 s, each in its own thread, whatever the centre does."""
    rng = random.Random(seed)
    n = 0
    due = time.time()
    while not stop.is_set():
        n += 1
        nature = pick_nature(rng)
        args = (log, base_url, random.Random(rng.getrandbits(64)), "normal", f"E-N-{n:06d}",
                area.normal_number(n - 1), nature, pick_narrative(rng, nature), stop)
        threading.Thread(target=_guarded, args=("a caller", run_emergency, *args), name=f"caller-{n}",
                         daemon=True).start()
        due += rng.uniform(*ARRIVAL_GAP_S)
        now = time.time()
        if due < now - 1.0:   # this process stalled: carry on from now, rather than start the missed ones at once
            due = now
        stop.wait(max(0.0, due - now))


# ----- crews -----

class Inbox:
    """One station inbox (an alerting side's file of alerts), read a whole line at a time from where we left off.
    A crew coming on shift acts only on alerts that arrive after it."""

    def __init__(self, path, via):
        self.path = path
        self.via = via
        self.offset = _size(path)

    def new_alerts(self):
        size = _size(self.path)
        if size < self.offset:   # the file was replaced: start again from its beginning
            self.offset = 0
        if size == self.offset:
            return []
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read(min(size - self.offset, READ_MAX))
        except OSError:
            return []
        end = chunk.rfind(b"\n")
        if end < 0:
            if len(chunk) >= READ_MAX:   # one line longer than any alert: skip it
                self.offset += len(chunk)
            return []
        self.offset += end + 1
        alerts = []
        for raw in chunk[:end].split(b"\n"):
            try:
                alert = json.loads(raw)
            except ValueError:
                continue
            if isinstance(alert, dict):
                alerts.append(alert)
        return alerts


class Crew:
    """One unit's crew: its state as it last logged it, what it is doing, and when its next step is due."""

    def __init__(self, unit, index, now):
        self.unit = unit
        self.index = index
        self.base = area.station_xy(area.UNIT_BY_ID[unit]["station"])
        self.status = "available"
        self.incident_id = None
        self.step = None           # turnout, enroute or onscene while busy; None when free
        self.due = None            # when the next step is due
        self.job = None            # the incident taken
        self.drive = 0.0
        self.last_t = 0.0
        self.heartbeat_at = now + HEARTBEAT_S * index / len(area.UNITS)   # staggered over the second
        self.alerts_seen = set()   # assignment ids
        self.served = set()        # incidents this crew has taken

    def stamp(self, now):
        """The time of this crew's next line or report: now, but always at least 1 ms after the last one."""
        self.last_t = round(max(now, self.last_t + 0.001), 3)
        return self.last_t


class Crews:
    """The 20 crews, moved by one scheduler. Every transition and heartbeat happens on its tick, and each new
    status is logged before its report is handed to the terminal, with the same time, so a report's state and
    time always match the crew's own log."""

    def __init__(self, inboxes, log, rng, send, now):
        self.inboxes = inboxes
        self.log = log
        self.rng = rng
        self.send = send           # send(unit index, report): hand a report to that unit's terminal uplink
        self.crews = {u["id"]: Crew(u["id"], k, now) for k, u in enumerate(area.UNITS)}

    def start(self, now):
        for crew in self.crews.values():
            self.log.write({"who": "crew", "event": "start", "unit": crew.unit, "status": crew.status,
                            "incident_id": None, "t": crew.stamp(now)})

    def tick(self, now):
        for crew in self.crews.values():
            if crew.step is not None and now >= crew.due:
                self.advance(crew, now)
            if now >= crew.heartbeat_at:
                self.report(crew, "heartbeat", crew.stamp(now))
                crew.heartbeat_at += HEARTBEAT_S
                if crew.heartbeat_at <= now:   # the scheduler fell behind: no burst of heartbeats
                    crew.heartbeat_at = now + HEARTBEAT_S
        for inbox in self.inboxes:
            for alert in inbox.new_alerts():
                self.on_alert(inbox.via, alert, now)

    def on_alert(self, via, alert, now):
        unit = alert.get("unit")
        crew = self.crews.get(unit) if isinstance(unit, str) else None
        incident_id = alert.get("incident_id")
        if crew is None or not _incident_id(incident_id):   # not one of ours (TEST-1 has no crew), or no incident
            return
        assignment_id = alert.get("assignment_id")
        if isinstance(assignment_id, bool) or not isinstance(assignment_id, (int, str)):
            assignment_id = None
        if assignment_id is not None:
            if assignment_id in crew.alerts_seen:
                return
            crew.alerts_seen.add(assignment_id)
        if incident_id in crew.served:
            return
        taken = crew.step is None   # a busy crew does not respond, as from an empty station
        self.log.write({"who": "crew", "event": "alert", "unit": crew.unit, "incident_id": incident_id,
                        "assignment_id": assignment_id, "via": via, "t": crew.stamp(now), "taken": taken})
        if taken:
            crew.served.add(incident_id)
            crew.job = incident_id
            scene = _point(alert)
            crew.drive = area.drive_s(area.distance(crew.base, scene) if scene else math.inf)
            crew.step, crew.due = "turnout", crew.last_t + self.rng.uniform(*TURNOUT_S)

    def advance(self, crew, now):
        if crew.step == "turnout":
            self.move(crew, "enroute", crew.job, now)
            crew.step, crew.due = "enroute", crew.last_t + crew.drive
        elif crew.step == "enroute":
            self.move(crew, "onscene", crew.job, now)
            crew.step, crew.due = "onscene", crew.last_t + self.rng.uniform(*ON_SCENE_S)
        else:
            self.move(crew, "available", None, now)
            crew.step, crew.due, crew.job = None, None, None

    def move(self, crew, status, incident_id, now):
        t = crew.stamp(now)
        crew.status, crew.incident_id = status, incident_id
        self.log.write({"who": "crew", "event": "status", "unit": crew.unit, "status": status,
                        "incident_id": incident_id, "t": t})
        self.report(crew, "status", t)

    def report(self, crew, kind, t):
        self.send(crew.index, fieldmsg.build(crew.unit, kind, crew.status, crew.incident_id, t))


class Uplink:
    """One of the terminals' uplinks to CAD's /mdt: a bounded queue of reports, sent oldest first.

    When the queue is full the oldest heartbeat goes first (the oldest report when there is none). A report
    older than 2.0 s when its turn comes is dropped, since the next heartbeat carries the state. A failed post
    is not retried."""

    def __init__(self, url, post=None, capacity=QUEUE_MAX):
        self.url = url
        self.post = post or post_json
        self.capacity = capacity
        self.queue = deque()
        self.ready = threading.Condition()

    def put(self, report):
        with self.ready:
            if len(self.queue) >= self.capacity:
                self._make_room()
            self.queue.append(report)
            self.ready.notify()

    def _make_room(self):
        for i, queued in enumerate(self.queue):
            if queued["kind"] == "heartbeat":
                del self.queue[i]
                return
        self.queue.popleft()

    def take(self, wait_s):
        with self.ready:
            if not self.queue:
                self.ready.wait(wait_s)
            return self.queue.popleft() if self.queue else None

    def send(self, report, now):
        """Post one report. False when it was too old to send, or the post failed."""
        if now - report["t"] > REPORT_MAX_AGE_S:
            return False
        try:
            self.post(self.url, report, MDT_TIMEOUT_S)
        except net.CallError:
            return False
        return True

    def run(self, stop):
        while not stop.is_set():
            try:
                report = self.take(0.5)
                if report is not None:
                    self.send(report, clock())
            except Exception as exc:   # a bug: say so and keep the uplink going
                note("an uplink", exc)


def run_crews(crews, stop):
    """The crews' scheduler: one tick every 0.05 s."""
    due = time.time()
    while not stop.is_set():
        try:
            crews.tick(clock())
        except Exception as exc:   # a bug: say so and keep the crews going
            note("the crews", exc)
        due += TICK_S
        now = time.time()
        if due < now:
            due = now
        stop.wait(due - now)


# ----- small helpers -----

def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _incident_id(value):
    """An incident id a unit report can carry (fieldmsg's rule)."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < fieldmsg.MAX_ID


def _number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:   # a whole number too large for a float
        return False


def _point(alert):
    x, y = alert.get("x"), alert.get("y")
    return (float(x), float(y)) if _number(x) and _number(y) else None


def _near(location, where):
    """Is the location read back to the caller within 0.05 km of where they really are?"""
    try:
        return math.hypot(float(location["x"]) - where[0], float(location["y"]) - where[1]) <= LOCATION_TOL_KM
    except (TypeError, KeyError, ValueError, OverflowError):
        return False


_noted = {}
_noted_lock = threading.Lock()


def note(where, exc):
    """Say that something stopped on an error: its type only, never its text, at most every 10 s per place."""
    now = time.time()
    with _noted_lock:
        if now - _noted.get(where, 0.0) < 10.0:
            return
        _noted[where] = now
    print(f"people: {where} stopped on {type(exc).__name__}", flush=True)


def _guarded(where, fn, *args):
    try:
        fn(*args)
    except Exception as exc:
        note(where, exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the dispatch centre's test callers and crews.")
    parser.add_argument("--data", required=True)
    parser.add_argument("--port", type=int, required=True, help="call-handling's port")
    parser.add_argument("--mdt-port", type=int, required=True, help="cad's port (unit terminals post to /mdt)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    paths = paths_for(args.data)
    log = Log(paths["traffic_log"])
    stop = threading.Event()
    uplinks = [Uplink(f"http://127.0.0.1:{args.mdt_port}/mdt") for _ in range(UPLINKS)]
    inboxes = [Inbox(path, via) for via, path in paths["alert_inboxes"].items()]
    crews = Crews(inboxes, log, random.Random(f"crews-{args.seed}"),
                  lambda index, report: uplinks[index % UPLINKS].put(report), clock())
    crews.start(clock())
    for k, uplink in enumerate(uplinks):
        threading.Thread(target=uplink.run, args=(stop,), name=f"uplink-{k}", daemon=True).start()
    threading.Thread(target=run_crews, args=(crews, stop), name="crews", daemon=True).start()
    print(f"people: {len(crews.crews)} crews on shift, {UPLINKS} terminal uplinks; callers start now", flush=True)
    try:
        caller_loop(log, f"http://127.0.0.1:{args.port}", args.seed, stop)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
