"""Dispatch practice fault: a component's process dies (root cause: process_down).

Public practice for trying the agent on dispatch from the console. It is not part of
any exam: the transfer exam's faults are sealed and were written by another builder.
The process is hard-killed, so no change is recorded. The right fix is to restart it.

params: {"target": "dispatcher" | "cad" | "call-handling"} (default: dispatcher)
"""

import time

TYPE = "practice_crash"
CLASSES = ["process_down"]
TARGETS = ("dispatcher", "cad", "call-handling")


def inject(control, params, rng):
    target = params.get("target") or "dispatcher"
    if target not in TARGETS:
        raise ValueError(f"practice_crash cannot target {target}")
    control.kill(target)
    return {"type": TYPE, "target": target, "class": "process_down", "detail": {}, "t": time.time()}
