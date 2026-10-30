"""Call handling release 5.2: the call-taker positions of the 9-1-1 centre (CPE and ACD).

1. A 9-1-1 call (POST /dial) waits, in the order it rang, for a free call-taker position (the ACD). When none
   comes free within rollover_s, the call rolls over to the backup centre.
2. Once a position answers, the caller's location comes from the call network's ALI database. When the call
   network cannot say, the call-taker asks the caller where they are.
3. The caller's report (POST /calls/<call_id>/report) is entered in CAD, and the caller is told help is on the
   way only once CAD holds the incident. The position is then free for the next call.

Calls are held in memory only, as on the call-taker's screen: a restart cuts off every call between its answer
and its report, and those callers must redial. Logs carry ids, never what a caller said or where they are.
"""

import math
import secrets
import threading
import time
from collections import deque

from ic.kit import net
from ic.kit.service import ServiceBase
from ic.kit.stats import Window
from targets.dispatch import area
from targets.dispatch.worker import check_settings

IDLE_S = 15.0           # a position held this long by a call that never reported is freed (the caller hung up)
NARRATIVE_MAX = 500
UNAVAILABLE = {"error": "call handling unavailable (settings)", "at": "call-handling"}


class Release(ServiceBase):
    SETTINGS = {"positions": ("int", 1, 64), "rollover_s": ("num", 0, 10), "ali_timeout_s": ("num", 0, 5),
                "cad_timeout_s": ("num", 0, 5)}

    def __init__(self, ctx):
        super().__init__(ctx)
        self.acd = threading.Condition()
        self.ringing = deque()      # (token, ring time) for each call waiting for a position, oldest first
        self.seats = {}             # position number -> call_id of the call it is answering
        self.calls = {}             # call_id -> {call_id, ani, test, answered_t, position, location}
        self.answered = Window()

    def routes(self):
        return {("POST", "/dial"): self.dial, ("POST", "/calls/*"): self.report}

    # ----- a 9-1-1 call rings -----

    def dial(self, request):
        self._settings()
        body = request["body"]
        if not isinstance(body, dict):
            raise net.Reply(400, {"error": "body: not an object"})
        ani, test = body.get("ani"), body.get("test")
        if not valid_number(ani):
            raise net.Reply(400, {"error": "ani: not a valid number"})
        if not _flag(test):
            raise net.Reply(400, {"error": "test: not 0 or 1"})
        call = {"call_id": "C-" + secrets.token_hex(4), "ani": ani, "test": test, "answered_t": None,
                "position": None, "location": None}
        self.take_position(call)
        try:
            call["location"] = self.lookup_location(ani)
        except BaseException:
            self.release_position(call)   # nobody was answered, so nothing may keep the position
            raise
        self.log.info("call_answered", f"call {call['call_id']} answered at position {call['position']}",
                      call_id=call["call_id"], position=call["position"],
                      ali="verified" if call["location"] else "unavailable")
        return {"call_id": call["call_id"], "location": call["location"], "position": call["position"]}

    def take_position(self, call):
        """The ACD: the call waits, in ring order, for a free position, and rolls over after rollover_s."""
        settings = self._settings()
        positions = settings["positions"]
        deadline = time.monotonic() + settings["rollover_s"]
        ring = (object(), time.monotonic())
        with self.acd:
            self.ringing.append(ring)
        try:
            while True:
                positions = self._positions(positions)   # staffing can change while the call rings
                with self.acd:
                    if self.ringing[0] is ring and len(self.seats) < positions:
                        seat = min(n for n in range(1, positions + 1) if n not in self.seats)
                        call["position"], call["answered_t"] = seat, time.time()
                        self.seats[seat] = call["call_id"]
                        self.calls[call["call_id"]] = call
                        self.answered.add(0.0, "ok")
                        return seat
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    self.acd.wait(min(left, 0.25))
        finally:
            with self.acd:
                self.ringing.remove(ring)
                self.acd.notify_all()
        self.log_every("rolled_over", 2.0, "WARN", "call_rolled_over",
                       "no call-taker position came free in time; the call rolled over to the backup centre",
                       call_id=call["call_id"])
        raise net.Reply(503, {"error": "rolled over", "at": "call-handling"})

    def lookup_location(self, ani):
        """Where the call network's ALI database puts the number, as {x, y}; None when it cannot say."""
        timeout = self._settings()["ali_timeout_s"]
        try:
            _, body = self.call("call-network", "POST", self.url("call-handling->call-network", "/ali"),
                                {"ani": ani}, timeout=timeout)
        except net.CallError as exc:
            return self._unlocated(exc.kind, exc.status)
        found = _point(body)
        return found if found is not None else self._unlocated("bad_response", None)

    def _unlocated(self, kind, status):
        self.log_every(f"ali_failed:{kind}", 2.0, "WARN", "ali_failed",
                       f"the call network's ALI gave no answer ({kind}); the call-taker asks the caller instead",
                       kind=kind, status=status)
        return None

    # ----- the caller reports the emergency -----

    def report(self, request):
        call_id, _, rest = request["tail"].partition("/")
        if rest != "report":
            raise net.Reply(404, {"error": "no such endpoint"})
        with self.acd:
            call = self.calls.pop(call_id, None)
        if call is None:
            raise net.Reply(404, {"error": "no such call"})
        try:
            self._settings()
            return self.enter_incident(call, self._report_fields(call, request["body"]))
        finally:
            self.release_position(call)

    def _report_fields(self, call, body):
        """The nature, narrative and spoken location, checked; a 400 names the first field that is wrong."""
        if not isinstance(body, dict):
            raise net.Reply(400, {"error": "body: not an object"})
        nature = body.get("nature")
        if not isinstance(nature, str) or nature not in area.NATURES:
            raise net.Reply(400, {"error": "nature: not a known nature"})
        if nature == "test" and call["test"] != 1:
            raise net.Reply(400, {"error": "nature: test is only for test calls"})
        if not _text(body.get("narrative"), NARRATIVE_MAX):
            raise net.Reply(400, {"error": f"narrative: not text of at most {NARRATIVE_MAX} characters"})
        spoken = None
        if body.get("location") is not None:
            spoken = _point(body["location"])
            if spoken is None:
                raise net.Reply(400, {"error": "location: not {x, y} finite numbers"})
        elif call["location"] is None:
            raise net.Reply(400, {"error": "location: required when the call network gave none"})
        return {"nature": nature, "narrative": body["narrative"], "location": spoken}

    def enter_incident(self, call, body):
        """Enter the call in CAD. The caller is told help is on the way only once CAD holds the incident."""
        timeout = self._settings()["cad_timeout_s"]
        spoken = body.get("location")
        entry = {"call_id": call["call_id"], "ani": call["ani"], "nature": body["nature"],
                 "narrative": body["narrative"], "location": spoken or call["location"],
                 "location_source": "verbal" if spoken else "ali", "test": call["test"]}
        try:
            status, answer = self.call("cad", "POST", self.url("cad", "/calls"), entry, timeout=timeout)
        except net.CallError as exc:
            self._not_entered(call, exc.kind, exc.status)
            if exc.kind == "http" and 400 <= (exc.status or 0) < 500:
                raise net.Reply(exc.status, exc.body)   # CAD refused the call: pass the refusal on as it is
            if exc.kind == "timeout":
                raise net.Reply(504, {"error": "cad timed out", "at": "cad"})
            raise net.Reply(502, {"error": f"cad unavailable ({exc.kind})", "at": "cad"})
        incident_id = answer.get("incident_id") if isinstance(answer, dict) else None
        if status not in (200, 201) or not _whole(incident_id):
            self._not_entered(call, "bad_response", status)
            raise net.Reply(502, {"error": "cad unavailable (bad_response)", "at": "cad"})
        linked = bool(answer.get("linked"))
        self.log.info("call_entered", f"call {call['call_id']} entered as incident {incident_id}",
                      call_id=call["call_id"], incident_id=incident_id, linked=linked)
        return {"told": True, "incident_id": incident_id, "linked": linked}

    def _not_entered(self, call, kind, status):
        self.log_every(f"call_not_entered:{kind}", 2.0, "ERROR", "call_not_entered",
                       f"call {call['call_id']} was not entered in CAD ({kind}); the caller was not told",
                       call_id=call["call_id"], kind=kind, status=status)

    def release_position(self, call):
        """The call is over: its position is free for the next ringing call."""
        with self.acd:
            if self.calls.get(call["call_id"]) is call:
                del self.calls[call["call_id"]]
            if call.get("position") is not None and self.seats.get(call["position"]) == call["call_id"]:
                del self.seats[call["position"]]
            self.acd.notify_all()

    # ----- housekeeping and the wallboard -----

    def background(self):
        """Once a second: name a setting that cannot be used, and free the positions of calls nobody finished."""
        while True:
            self.server.gate.wait()
            self._usable()
            self._free_idle(time.time())
            time.sleep(1.0)

    def _free_idle(self, now):
        with self.acd:
            idle = [c for c in self.calls.values()
                    if c["answered_t"] is not None and now - c["answered_t"] > IDLE_S]
            for call in idle:
                del self.calls[call["call_id"]]
                if self.seats.get(call["position"]) == call["call_id"]:
                    del self.seats[call["position"]]
            if idle:
                self.acd.notify_all()
        if idle:
            self.log_every("position_freed_idle", 2.0, "WARN", "position_freed_idle",
                           f"{len(idle)} position(s) freed: no report came {IDLE_S:.0f} s after the answer",
                           calls=len(idle), call_id=idle[0]["call_id"])
        return len(idle)

    def extra_metrics(self, window_s):
        """The ACD wallboard: calls ringing now, the longest current ring, calls answered per second."""
        now = time.monotonic()
        with self.acd:
            depth = len(self.ringing)
            oldest = now - self.ringing[0][1] if self.ringing else 0.0
        return {"queue_depth": depth, "oldest_pending_s": round(max(0.0, oldest), 2),
                "processed_per_s": self.answered.summary(window_s)["rps"]}

    # ----- settings -----

    def _usable(self):
        """The settings in force, or None once a value cannot be used (logged by its key, never its value)."""
        settings, bad_key = check_settings(self.config.values()[0], self.SETTINGS)
        if settings is None:
            self.log_every("settings_unusable", 2.0, "ERROR", "settings_unusable",
                           f"setting {bad_key} cannot be used; calls are not answered until it changes",
                           key=bad_key)
        return settings

    def _settings(self):
        settings = self._usable()
        if settings is None:
            raise net.Reply(503, dict(UNAVAILABLE))
        return settings

    def _positions(self, last):
        settings, _ = check_settings(self.config.values()[0], self.SETTINGS)
        return settings["positions"] if settings else last


def valid_number(ani):
    """A number of the shape 0PP-555-01NN, in ASCII digits with nothing after it."""
    return area.valid_number(ani) and len(ani) == 12 and ani.isascii()


def _flag(value):
    return isinstance(value, int) and not isinstance(value, bool) and value in (0, 1)


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value, limit):
    """A str of at most `limit` characters that the database can store."""
    if not isinstance(value, str) or len(value) > limit:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _point(value):
    """{x, y} as two finite floats, or None."""
    if not isinstance(value, dict):
        return None
    xy = []
    for key in ("x", "y"):
        v = value.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        try:
            v = float(v)
        except OverflowError:
            return None
        if not math.isfinite(v):
            return None
        xy.append(v)
    return {"x": xy[0], "y": xy[1]}
