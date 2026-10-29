"""Healthy distractor: things change, but nothing is broken (no root cause).

A harmless gateway release goes out (2.0.1 only adds a build label) and a
heavy but harmless reconciliation run burns CPU. Customers are fine. The
right response is to check, find nothing wrong, and take no action.

params: {"variant": "deploy" | "cpu" | "both", "cpu_s": 120}
"""

import time

from targets.bank.faults.common import actor

TYPE = "noise"
CLASSES = []


def inject(control, params, rng):
    variant = params.get("variant", "both")
    detail = {"variant": variant}
    if variant in ("deploy", "both"):
        detail["answering"] = control.deploy("gateway", "2.0.1", actor=actor(params, rng))
    if variant in ("cpu", "both"):
        detail["job_pid"] = control.spawn("reconciliation", [
            "{python}", "-m", "targets.bank.jobs.reconciliation", "--data", "{data}",
            "--cpu", str(float(params.get("cpu_s", 120)))])
    return {"type": TYPE, "target": None, "class": None, "detail": detail, "t": time.time()}
