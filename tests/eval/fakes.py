"""Small file-backed invented system, safe to pass to Windows spawned processes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from ic.contract import empty_result
from ic.kit.net import CallError
from eval.arms import noop


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value) + "\n")


class Adapter:
    def __init__(self, folder):
        self.folder = Path(folder)

    def describe(self):
        return {"capabilities": {"max_mode": "auto", "act": True, "probe": True},
                "components": [{"name": "engine", "kind": "service", "actions": ["restart", "quarantine"]}],
                "actions": {"restart": {"est_seconds": 0}, "quarantine": {"est_seconds": 0}}}

    def observe(self, window_s=10):
        return {"components": {"engine": {"up": (self.folder / "fixed").exists()}}}

    def logs(self, component, since_s=60, limit=200):
        return []

    def probe(self, journey=None):
        return {"ok": (self.folder / "fixed").exists()}

    def act(self, action, target, params=None):
        result = {"t": time.time(), "action": action, "target": target, "params": params or {}, "ok": True, "refused": False}
        append(self.folder / "actions.jsonl", result)
        (self.folder / "fixed").touch()
        return result


class Control:
    def __init__(self, folder):
        self.folder = Path(folder)

    def paths(self):
        return {"actions": str(self.folder / "actions.jsonl"), "changes": str(self.folder / "changes.jsonl"),
                "traffic_log": str(self.folder / "customers.jsonl"), "logs": str(self.folder / "logs")}


class Platform:
    def __init__(self, system, port_base, seed, condition):
        self.folder = Path.cwd() / "runs" / f"invented-{port_base}"
        self.seed, self.condition = seed, condition

    def start(self, warmup_s=0):
        if self.folder.exists():
            shutil.rmtree(self.folder)
        (self.folder / "logs").mkdir(parents=True)
        (self.folder / "logs" / "fixture.json").write_text(json.dumps({"condition": self.condition, "seed": self.seed}))
        for name in ("actions.jsonl", "changes.jsonl", "customers.jsonl"):
            (self.folder / name).write_text("")

    def adapter(self):
        return Adapter(self.folder)

    def control(self):
        return Control(self.folder)

    def stop(self):
        (self.folder / "stopped").touch()


def platform(system, **kwargs):
    return Platform(system, **kwargs)


def inject(system, control, faults, seed, allow_sealed, t0):
    append(control.folder / "changes.jsonl", {"allow_sealed": allow_sealed, "seed": seed, "t0": t0})
    if not faults:
        (control.folder / "fixed").touch()
    return [{"target": "engine", "class": "process_down", "type": "invented", "t": time.time(), "detail": {"item": 77}} for fault in faults]


class Checker:
    def verify(self, control, *, window_s, lag_s, since_t):
        recovered = (control.folder / "fixed").exists()
        return {"recovered": recovered, "slo_ok": recovered, "journeys": {"n": 20, "ok": 20 if recovered else 0,
            "success_rate": 1 if recovered else 0, "p95_ms": 1}, "integrity": {"ok": True, "for_operations": []},
            "impact": {"breach_seconds": 0 if recovered else 5, "failed_journeys": 0 if recovered else 20},
            "since_t": since_t}


def checker(system):
    return Checker()


class RedChecker(Checker):
    def verify(self, control, **kwargs):
        result = super().verify(control, **kwargs)
        result["recovered"] = False
        return result


def red_checker(system):
    return RedChecker()


def broken_inject(system, control, faults, **kwargs):
    raise RuntimeError("invented injection error")


def fake_arm(adapter, *, budget_s, max_steps, model, seed, mode, confirm, log):
    # This strict signature detects any leakage of ids, labels or control data.
    adapter.describe()
    adapter.act("restart", "engine")
    result = empty_result("invented")
    result.update(outcome="recovered", t_start=time.time(), t_declared=time.time())
    return result


def slow_arm(adapter, **kwargs):
    time.sleep(20)
    adapter.act("restart", "engine")
    return fake_arm(adapter, **kwargs)


def transient_arm(adapter, **kwargs):
    result = empty_result("transient")
    result["outcome"] = "gave_up"
    result["calls"] = [{"status": "failed", "error": "http_429"}]
    return result


def crashed_arm(adapter, **kwargs):
    adapter.act("restart", "engine")
    os._exit(7)


class UnreadableAdapter(Adapter):
    def observe(self, window_s=10):
        raise CallError("refused", detail="invented target is offline")


class UnreadablePlatform(Platform):
    def adapter(self):
        return UnreadableAdapter(self.folder)


def unreadable_platform(system, **kwargs):
    return UnreadablePlatform(system, **kwargs)


def unreachable_arm(adapter, **kwargs):
    adapter.observe()


def bare_callerror_arm(adapter, **kwargs):
    raise CallError("refused", detail="invented arm read failed before audit")


def caught_read_arm(adapter, **kwargs):
    try:
        adapter.observe()
    except CallError:
        result = empty_result("caught_read")
        result["outcome"] = "escalated"
        result["calls"] = [{"status": "ok", "input_tokens": 3, "output_tokens": 2}]
        return result


def caught_read_then_error_arm(adapter, **kwargs):
    try:
        adapter.observe()
    except CallError:
        raise ValueError("invented later failure") from None


def interrupted_arm(adapter, **kwargs):
    raise KeyboardInterrupt


def resumed_arm(name):
    return noop


def load_arm(name):
    return {"invented": fake_arm, "noop": noop, "slow": slow_arm, "transient": transient_arm,
            "crashed": crashed_arm, "unreachable": unreachable_arm, "caught_read": caught_read_arm,
            "bare_callerror": bare_callerror_arm, "caught_read_then_error": caught_read_then_error_arm,
            "interrupted": interrupted_arm}[name]


def spawning_parent(folder):
    """A supervisor-like parent with a running child and grandchild."""
    child_code = ("import json,os,subprocess,sys,time; from pathlib import Path; "
                  "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                  "Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid])); time.sleep(60)")
    subprocess.Popen([sys.executable, "-c", child_code, str(Path(folder) / "nested-pids.json")])
    time.sleep(60)


class InterruptPlatform(Platform):
    def start(self, warmup_s=0):
        super().start(warmup_s)
        child_code = ("import json,os,subprocess,sys,time; from pathlib import Path; "
                      "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                      "Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid])); time.sleep(60)")
        subprocess.Popen([sys.executable, "-c", child_code, str(self.folder / "interrupt-pids.json")])
        time.sleep(60)


def interrupt_platform(system, **kwargs):
    return InterruptPlatform(system, **kwargs)


class ChildInterruptPlatform(Platform):
    def start(self, warmup_s=0):
        super().start(warmup_s)
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        (self.folder / "child-interrupt-pids.json").write_text(json.dumps([child.pid]))
        raise KeyboardInterrupt


def child_interrupt_platform(system, **kwargs):
    return ChildInterruptPlatform(system, **kwargs)


def case(number, *, healthy=False, condition="default"):
    return {"id": f"fixture-{number}", "input": {"system": "invented", "seed": number, "condition": condition,
        "faults": [] if healthy else [{"type": "invented"}]},
        "target": {"healthy": healthy, "must_escalate": False, "blind": False, "acceptable_secondary": [],
            "root_causes": [] if healthy else [{"target": "engine", "class": "process_down", "fix": {"action": "restart", "target": "engine", "params": {}}}]}}
