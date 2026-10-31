"""Make the external service stop answering until its operator restores it."""

import time

TYPE = "sealed_3"
CLASSES = ["external_outage"]


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameter")
    if params.get("target") != "network" or params.get("variant") != "v1":
        raise ValueError("unsupported target or variant")
    answer = control.admin("network", "hang")
    if not answer.get("ok"):
        raise RuntimeError("service operation did not complete")
    return {"type": TYPE, "target": "network", "class": "external_outage",
            "detail": {}, "t": time.time()}
