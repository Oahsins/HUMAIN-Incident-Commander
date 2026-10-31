"""Exercise a running service that no longer answers requests."""

import time

TYPE = "blind_1"
CLASSES = ["process_down"]


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameter")
    if params.get("target") != "gateway" or params.get("variant") != "v1":
        raise ValueError("unsupported target or variant")
    answer = control.admin("gateway", "hang")
    if not answer.get("ok"):
        raise RuntimeError("service operation did not complete")
    return {"type": TYPE, "target": "gateway", "class": "process_down",
            "detail": {}, "t": time.time()}
