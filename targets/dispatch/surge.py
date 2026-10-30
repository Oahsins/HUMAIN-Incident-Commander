"""The call surge helper: extra emergencies on top of the everyday callers, and the only source of extra calls.

    python -m targets.dispatch.surge --data runs/dispatch-9500 --rate 2.0 --seconds 150 --seed 7 --mix normal

or control.surge(rate_per_s, seconds, seed, mix), which waits until the helper has registered or refused.

It starts emergencies at random (Poisson) times, --rate per second for --seconds, whatever call-handling does.
Each one runs people.run_emergency in its own thread, with the everyday callers' rules (redials, callbacks,
timeouts), at most 64 at once. Its callers' lines go to logs/call-surge-<pid>.jsonl in the users' log shape,
with source "surge". --mix is normal (everyday weights), medical or fire.

All helpers together start at most 3.0 emergencies per second. Before its first call a helper registers in
surge.json, under surge.lock, and it is refused, never slowed, when it would pass the cap. It also takes one of
five blocks of 1,000 made-up numbers (surge-slots/<k>, which remembers where the block got to), so a number is
not used again before its block has gone round; one run places at most 1,000 emergencies.

Every line it prints starts with "call-surge <pid>: ". A refusal is the one line
"call-surge <pid>: refused: <reason>", exit code 2, and no call placed. Otherwise it prints counts every 10 s,
and on the way out (also after an error) it leaves the registry and frees its block.
"""

import argparse
import json
import math
import os
import random
import sys
import threading
import time
from contextlib import contextmanager

from ic.kit.proc import alive
from ic.kit.store import read_json, write_json
from targets.dispatch import area, people
from targets.dispatch.control import paths_for

CAP_PER_S = 3.0              # all surges together, emergencies per second (docs/DISPATCH.md, Call surge)
MAX_EMERGENCIES = 1000       # one block of numbers: rate x seconds may not pass it
SECONDS_MIN, SECONDS_MAX = 1.0, 900.0
IN_FLIGHT_MAX = 64
GRACE_S = 10.0               # after the last start, how long calls in flight may take to finish
REPORT_EVERY_S = 10.0
LOCK_RETRY_S = 0.05
LOCK_WAIT_S = 2.0
LOCK_LEFT_S = 5.0            # a lock file this old was left by a helper that died while holding it
SAVE_AHEAD = 10              # numbers claimed ahead in the slot file, so a killed helper's successor repeats none


class Refused(Exception):
    """The helper will not run. The text is the reason it gives."""


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(f"bad arguments ({message})")


def say(pid, text):
    print(f"call-surge {pid}: {text}", flush=True)


def parse_args(argv):
    parser = _Arguments(prog="python -m targets.dispatch.surge", description="Start a call surge.")
    parser.add_argument("--data")
    parser.add_argument("--rate", default="2.0", help="emergencies per second, above 0 and at most 3.0")
    parser.add_argument("--seconds", default="150", help="1 to 900")
    parser.add_argument("--seed", default="0")
    parser.add_argument("--mix", default="normal", help="normal, medical or fire")
    args = parser.parse_args(argv)
    if not args.data:
        raise Refused("--data is required")
    if not os.path.isdir(args.data):
        raise Refused("the data folder does not exist")
    rate, seconds = _parse_number(args.rate), _parse_number(args.seconds)
    if rate is None or not 0 < rate <= CAP_PER_S:
        raise Refused(f"rate must be a number above 0 and at most {CAP_PER_S:g} (emergencies per second)")
    if seconds is None or not SECONDS_MIN <= seconds <= SECONDS_MAX:
        raise Refused(f"seconds must be a number from {SECONDS_MIN:g} to {SECONDS_MAX:g}")
    if rate * seconds > MAX_EMERGENCIES:
        raise Refused(f"rate x seconds is {rate * seconds:g} emergencies, more than the {MAX_EMERGENCIES} numbers "
                      f"of one block")
    try:
        seed = int(args.seed)
    except ValueError:
        raise Refused("seed must be a whole number") from None
    if args.mix not in people.MIXES:
        raise Refused("mix must be normal, medical or fire")
    return argparse.Namespace(data=os.path.abspath(args.data), rate=rate, seconds=seconds, seed=seed, mix=args.mix)


def call_handling_url(data_dir):
    """call-handling's address, from the copy's ports.json."""
    doc = read_json(os.path.join(data_dir, "ports.json"), None)
    ports = doc.get("ports") if isinstance(doc, dict) else None
    port = ports.get("call-handling") if isinstance(ports, dict) else None
    if not (_whole(port) and 0 < port < 65536):
        raise Refused("ports.json is missing or names no call-handling port")
    return f"http://127.0.0.1:{port}"


# ----- the registry (surge.json) and the number blocks (surge-slots/<k>) -----

@contextmanager
def registry_lock(data_dir):
    """surge.lock, made with O_CREAT|O_EXCL and closed at once (Windows cannot remove an open file).
    Tried every 50 ms for up to 2 s; a lock file older than 5 s was left by a helper that died, and is removed."""
    path = os.path.join(data_dir, "surge.lock")
    deadline = time.time() + LOCK_WAIT_S
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            _remove_if_left(path)
        except PermissionError:   # Windows: another helper is removing it
            pass
        if time.time() >= deadline:
            raise Refused(f"the surge registry stayed locked for {LOCK_WAIT_S:g} s")
        time.sleep(LOCK_RETRY_S)
    try:
        yield
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _remove_if_left(path):
    try:
        if time.time() - os.path.getmtime(path) > LOCK_LEFT_S:
            os.remove(path)
    except OSError:
        pass


def live_helpers(doc, now):
    """The registry's entries for helpers that are still running and still inside their --seconds."""
    helpers = doc.get("helpers") if isinstance(doc, dict) else None
    return [h for h in helpers or [] if isinstance(h, dict) and _pid(h.get("pid")) and _real(h.get("rate"))
            and _real(h.get("until_t")) and h["until_t"] > now and alive(h["pid"])]


def register(data_dir, pid, rate, until_t, now=None):
    """Join the registry and take a number block, under surge.lock and before any call is placed.

    Raises Refused when the live helpers' rates plus this one would pass the cap, or no block is free.
    Returns (block, the index of its next number)."""
    now = time.time() if now is None else now
    registry = paths_for(data_dir)["surge_registry"]
    with registry_lock(data_dir):
        helpers = live_helpers(read_json(registry, {"helpers": []}), now)
        total = sum(h["rate"] for h in helpers) + rate
        if total > CAP_PER_S + 1e-9:
            raise Refused(f"the surges together would start {total:.2f} emergencies per second, above the cap "
                          f"of {CAP_PER_S:g}")
        block, first = claim_block(data_dir, pid)
        try:
            write_json(registry, {"helpers": helpers + [{"pid": pid, "rate": rate, "until_t": round(until_t, 3)}]})
        except BaseException:
            write_json(slot_path(data_dir, block), {"pid": None, "next": first})
            raise
    return block, first


def unregister(data_dir, pid):
    """Leave the registry. When surge.lock cannot be had, the entry lapses anyway with its until_t and pid."""
    registry = paths_for(data_dir)["surge_registry"]
    try:
        with registry_lock(data_dir):
            doc = read_json(registry, {"helpers": []})
            helpers = doc.get("helpers") if isinstance(doc, dict) else None
            write_json(registry, {"helpers": [h for h in helpers or []
                                              if not (isinstance(h, dict) and h.get("pid") == pid)]})
    except Refused:
        pass


def slot_path(data_dir, block):
    return os.path.join(data_dir, "surge-slots", str(block))


def claim_block(data_dir, pid):
    """The first number block no running helper holds: a new slot file (O_EXCL), or the slot of a helper that
    has gone, continuing from where it got to. Raises Refused when all five are held."""
    os.makedirs(os.path.join(data_dir, "surge-slots"), exist_ok=True)
    for block in range(area.SURGE_BLOCKS):
        path = slot_path(data_dir, block)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            doc = _read_slot(path)
            holder = doc.get("pid")
            if _pid(holder) and holder != pid and alive(holder):
                continue
            first = doc.get("next") if _whole(doc.get("next")) and doc["next"] >= 0 else 0
            write_json(path, {"pid": pid, "next": first})
            return block, first
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"pid": pid, "next": 0}, handle)
        return block, 0
    raise Refused(f"all {area.SURGE_BLOCKS} number blocks are held by running surges")


def _read_slot(path):
    for _ in range(50):
        try:
            with open(path, encoding="utf-8") as handle:
                doc = json.load(handle)
            return doc if isinstance(doc, dict) else {}
        except PermissionError:   # Windows: its helper is saving it this moment
            time.sleep(0.02)
        except (OSError, ValueError):
            return {}
    return {}


class Block:
    """This helper's block of 1,000 numbers. While it runs, the slot file names a next number past every one it
    has used (saved ahead), so a helper killed mid-run never makes its successor repeat a number; a helper that
    ends normally saves exactly where it got to."""

    def __init__(self, data_dir, pid, block, first):
        self.path = slot_path(data_dir, block)
        self.pid = pid
        self.block = block
        self.next = self.saved = first

    def take(self):
        index = self.next
        self.next += 1
        if self.next > self.saved:
            self.saved = self.next + SAVE_AHEAD
            self.save()
        return area.surge_number(self.block, index)

    def save(self):
        write_json(self.path, {"pid": self.pid, "next": self.saved})

    def release(self):
        write_json(self.path, {"pid": None, "next": self.next})


# ----- the surge itself -----

class Tally(people.Log):
    """The surge callers' log, counting calls as their lines are written."""

    def __init__(self, path):
        super().__init__(path)
        self.calls = 0
        self.told = 0

    def write(self, record):
        super().write(record)
        with self.lock:
            self.calls += 1
            self.told += record.get("outcome") == "told"


class Surge:
    def __init__(self, args, pid, base_url, block):
        self.args = args
        self.pid = pid
        self.base_url = base_url
        self.block = block
        self.log = Tally(os.path.join(paths_for(args.data)["logs"], f"call-surge-{pid}.jsonl"))
        self.stop = threading.Event()
        self.room = threading.BoundedSemaphore(IN_FLIGHT_MAX)
        self.lock = threading.Lock()
        self.started = 0
        self.finished = 0
        self.callers = []
        self.report_t = None

    def run(self):
        args = self.args
        rng = random.Random(args.seed)
        begun = time.time()
        end_t = begun + args.seconds
        self.report_t = begun + REPORT_EVERY_S
        say(self.pid, f"started: {args.rate:g} emergencies per second for {args.seconds:g} s, mix {args.mix}, "
                      f"number block {self.block.block}")
        due = begun
        try:
            while True:
                due += rng.expovariate(args.rate)
                if due >= end_t:
                    break
                self.wait_until(due)
                if not self.make_room(end_t):
                    break
                nature = people.pick_nature(rng, args.mix)
                caller = threading.Thread(
                    target=self.emergency, name=f"surge-{self.started + 1}", daemon=True,
                    args=(random.Random(rng.getrandbits(64)), f"E-S{self.pid}-{self.started + 1:06d}",
                          self.block.take(), nature, people.pick_narrative(rng, nature)))
                with self.lock:
                    self.started += 1
                    self.callers = [c for c in self.callers if c.is_alive()] + [caller]
                caller.start()
            self.wait_until(end_t)
        finally:
            self.stop.set()   # calls in flight finish; no new call starts
            deadline = time.time() + GRACE_S
            for caller in list(self.callers):
                caller.join(max(0.0, deadline - time.time()))
        say(self.pid, f"finished after {time.time() - begun:.0f} s: {self.counts()}")

    def emergency(self, rng, emergency_id, ani, nature, narrative):
        try:
            people.run_emergency(self.log, self.base_url, rng, "surge", emergency_id, ani, nature, narrative,
                                 self.stop)
        except Exception as exc:   # a bug: say so without any caller detail
            say(self.pid, f"an emergency stopped on {type(exc).__name__}")
        finally:
            with self.lock:
                self.finished += 1
            self.room.release()

    def make_room(self, end_t):
        """Wait for one of the 64 places for an emergency in progress. False when --seconds ran out first."""
        while True:
            left = end_t - time.time()
            if left <= 0:
                return False
            if self.room.acquire(timeout=min(left, 1.0)):
                return True
            self.wait_until(time.time())   # keep the counts coming while every place is taken

    def wait_until(self, t):
        """Sleep until t, printing the counts (and saving the block's place) every 10 s on the way."""
        while True:
            now = time.time()
            if now >= self.report_t:
                say(self.pid, self.counts())
                self.block.save()
                self.report_t += REPORT_EVERY_S
            if now >= t:
                return
            time.sleep(max(0.0, min(t, self.report_t) - now))

    def counts(self):
        with self.lock:
            started, finished = self.started, self.finished
        with self.log.lock:
            calls, told = self.log.calls, self.log.told
        return (f"{started} emergencies started, {started - finished} in progress; {calls} calls ended, "
                f"{told} told")


def main(argv=None):
    pid = os.getpid()
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        base_url = call_handling_url(args.data)
        number_block, first = register(args.data, pid, args.rate, time.time() + args.seconds)
    except Refused as exc:
        say(pid, f"refused: {exc}")
        return 2
    block = Block(args.data, pid, number_block, first)
    code = 0
    try:
        Surge(args, pid, base_url, block).run()
    except Exception as exc:
        say(pid, f"stopped on {type(exc).__name__}")
        code = 1
    except KeyboardInterrupt:
        say(pid, "stopped")
        code = 1
    finally:
        try:
            block.release()
        except OSError:
            pass
        unregister(args.data, pid)
    return code


# ----- small helpers -----

def _parse_number(text):
    try:
        value = float(text)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _pid(value):
    return _whole(value) and value > 0


def _real(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


if __name__ == "__main__":
    sys.exit(main())
