"""Privileged operations on a running test dispatch centre (CONTRACT.md section 5).

For the fault injector, the checker and the evaluation harness. Never given to the agent.
"""

import os
import time

from ic.kit import proc
from ic.kit.client import ControlClient
from ic.kit.store import read_json
from targets.dispatch import cadstore

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
        3.0 emergencies per second, and one burst places at most 1,000. Returns the helper's pid once it has
        registered. A burst the helper refuses (over the cap, no free number block, a bad argument) raises
        RuntimeError with the helper's reason: it is refused, never clamped, so a case never runs without it.
        """
        pid = self.spawn("call-surge", ["{python}", "-m", "targets.dispatch.surge", "--data", "{data}",
                                        "--rate", str(rate_per_s), "--seconds", str(seconds),
                                        "--seed", str(seed), "--mix", mix])
        registry = paths_for(self.data_dir)["surge_registry"]
        deadline = time.time() + SURGE_WAIT_S
        while time.time() < deadline:
            helpers = (read_json(registry, {"helpers": []}) or {}).get("helpers") or []
            if any(h.get("pid") == pid for h in helpers):
                return pid
            if not proc.alive(pid):
                raise RuntimeError(f"call surge refused: {_refusal(self.data_dir, pid)}")
            time.sleep(0.05)
        raise RuntimeError(f"call surge {pid} neither registered nor refused within {SURGE_WAIT_S:.0f} s")

    def paths(self):
        return {**super().paths(), **paths_for(self.data_dir)}


def _refusal(data_dir, pid):
    """The helper's own reason, from its one stdout line "call-surge <pid>: refused: <reason>"."""
    marker = f"call-surge {pid}: refused: "
    try:
        with open(os.path.join(data_dir, "logs", "call-surge.out"), encoding="utf-8", errors="replace") as handle:
            lines = [line.strip() for line in handle if line.startswith(marker)]
    except OSError:
        lines = []
    return lines[-1][len(marker):] if lines else "the helper exited before registering"
