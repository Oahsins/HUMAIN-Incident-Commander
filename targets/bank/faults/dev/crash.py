"""Practice fault: a service process dies (root cause: process_down).

The process is hard-killed, as an out-of-memory kill or a segfault would do,
so no change is recorded. The right fix is to restart it.

params: {"target": "payments" | "gateway" | "clearing" | "screening"} (default: payments or gateway)
"""

import time

TYPE = "crash"
CLASSES = ["process_down"]
TARGETS = ("payments", "gateway", "clearing", "screening")


def inject(control, params, rng):
    target = params.get("target") or rng.choice(TARGETS[:2])
    if target not in TARGETS:
        raise ValueError(f"crash cannot target {target}")
    control.kill(target)
    return {"type": TYPE, "target": target, "class": "process_down", "detail": {}, "t": time.time()}
