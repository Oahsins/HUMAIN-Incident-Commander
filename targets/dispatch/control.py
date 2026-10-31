"""Privileged operations on a running test dispatch centre (CONTRACT.md section 5).

For the fault injector, the checker and the evaluation harness. Never given to the agent.
"""

import os
import re
import time

from ic.kit import proc
from ic.kit.client import ControlClient
from ic.kit.store import read_json
from targets.dispatch import cadstore
from targets.dispatch.spec import process_tree, started_as

SURGE_WAIT_S = 5.0   # how long surge() waits for the helper to register or refuse


def paths_for(data_dir):
    """Every file the checker and the harness read, from the data folder alone. Control.paths() and the
    checker's command line both use this, so they cannot drift apart."""
    d = os.path.abspath(data_dir)
    people = os.path.join(d, "people.jsonl")
    return {"data_dir": d, "logs": os.path.join(d, "logs"),
            "actions": os.path.join(d, "actions.jsonl"), "changes": os.path.join(d, "changes.jsonl"),
            "traffic_log": people, "users_log": people,
            "surge_logs": os.path.join(d, "logs", "call-surge-*.jsonl"),
            "datastores": {"cad-db": cadstore.path(d)}, "cad_db": cadstore.path(d),
            "locks": cadstore.locks_path(d), "surge_registry": os.path.join(d, "surge.json"),
            "alert_inboxes": {"alerting": os.path.join(d, "alerts-alerting.jsonl"),
                              "alerting-backup": os.path.join(d, "alerts-alerting-backup.jsonl")},
            "checker_baseline": os.path.join(d, "checker_baseline.json")}


class Control(ControlClient):
    def db(self, name=None):
        """A direct connection to a datastore (the centre has one: cad-db). Writers wait up to 5 s for a lock."""
        if name not in (None, "cad-db"):
            raise KeyError("dispatch has one datastore, cad-db")
        return cadstore.connect(self.data_dir, busy_timeout_ms=5000)

    def surge(self, rate_per_s, seconds, seed=0, mix="normal"):
        """Start a burst of extra emergencies, the only source of extra calls (docs/DISPATCH.md, Call surge).

        rate_per_s is emergencies per second; each makes about 1.1 calls. All bursts together are capped at
        3.0 emergencies per second, and one burst places at most 1,000. Returns the helper's own pid (the one in
        its log lines and file names) once it has registered. A burst the helper refuses (over the cap, no free
        number block, a bad argument) raises RuntimeError with the helper's reason: it is refused, never clamped,
        so a case never runs without it.
        """
        out = os.path.join(paths_for(self.data_dir)["logs"], "call-surge.out")
        offset = _size(out)
        pid = self.spawn("call-surge", ["{python}", "-m", "targets.dispatch.surge", "--data", "{data}",
                                        "--rate", str(rate_per_s), "--seconds", str(seconds),
                                        "--seed", str(seed), "--mix", mix])
        registry = paths_for(self.data_dir)["surge_registry"]
        deadline = time.time() + SURGE_WAIT_S
        while time.time() < deadline:
            mine = set(process_tree(pid))   # on Windows a venv's python.exe is a launcher: the helper is its child
            helpers = (read_json(registry, {"helpers": []}) or {}).get("helpers") or []
            for helper in helpers:   # its entry: a pid of this process tree, still the process that wrote it
                if (isinstance(helper, dict) and isinstance(helper.get("pid"), int) and helper["pid"] in mine
                        and started_as(helper["pid"], helper.get("started_t"))):
                    return helper["pid"]
            if not proc.alive(pid):
                raise RuntimeError(f"call surge refused: {_refusal(out, offset)}")
            time.sleep(0.05)
        raise RuntimeError(f"call surge {pid} neither registered nor refused within {SURGE_WAIT_S:.0f} s")

    def paths(self):
        return {**super().paths(), **paths_for(self.data_dir)}


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


REFUSED = re.compile(r"call-surge \d+: refused: (.*)")


def _refusal(out, offset):
    """The helper's own reason: the last line "call-surge <pid>: refused: <reason>" written to call-surge.out
    since this surge was spawned (its pid may be a venv launcher's child, so the line is found by place)."""
    try:
        with open(out, "rb") as handle:
            handle.seek(offset)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        text = ""
    reasons = [match.group(1).strip() for match in map(REFUSED.match, text.splitlines()) if match]
    return reasons[-1] if reasons else "the helper exited before registering"
