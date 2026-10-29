"""Practice fault: a faulty release goes out (root cause: bad_release).

The deployment pipeline ships payments 1.4, whose new fee preview divides by
zero for payments over 300.00 SAR, so about four in ten payments fail with an
error. The deploy appears in the change log. The right fix is to roll back.

params: {"target": "payments", "release": "1.4"}
"""

import time

from targets.bank.faults.common import actor

TYPE = "bad_update"
CLASSES = ["bad_release"]
BAD_RELEASES = {"payments": "1.4"}


def inject(control, params, rng):
    target = params.get("target", "payments")
    release = params.get("release", BAD_RELEASES.get(target))
    if not release:
        raise ValueError(f"no faulty release is defined for {target}")
    healthy = control.deploy(target, release, actor=actor(params, rng))
    return {"type": TYPE, "target": target, "class": "bad_release",
            "detail": {"release": release, "answering": healthy}, "t": time.time()}
