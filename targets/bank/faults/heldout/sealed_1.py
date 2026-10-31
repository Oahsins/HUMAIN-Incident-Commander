"""Restart the unused standby as an ordinary maintenance change."""

import time

from targets.bank.faults.common import ACTORS

TYPE = "sealed_1"
CLASSES = []


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameter")
    if params.get("target") != "screening-standby" or params.get("variant") != "v1":
        raise ValueError("unsupported target or variant")
    actor = rng.choice(ACTORS)
    control.stop("screening-standby", actor=actor)
    if not control.start("screening-standby", actor=actor):
        raise RuntimeError("service did not become available")
    return {"type": TYPE, "target": None, "class": None, "detail": {}, "t": time.time()}
