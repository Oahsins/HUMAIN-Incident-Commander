"""Practice fault: a maintenance script stops the clearing worker and never starts it again (root cause: process_down).

Payments are still accepted and posted, but nothing reaches the payment
network: the clearing queue grows. The stop appears in the change log. The
right fix is to start (restart) the worker.

params: {"target": "clearing" (default), or "notifications" under extra_service,
         "actor": <optional; default a random actor from the pool>}
"""

import time

from targets.bank.faults.common import actor, check_target

TYPE = "stopped_worker"
CLASSES = ["process_down"]


def inject(control, params, rng):
    target = params.get("target", "clearing")
    check_target(control, target)
    control.stop(target, actor=actor(params, rng))
    return {"type": TYPE, "target": target, "class": "process_down", "detail": {}, "t": time.time()}
