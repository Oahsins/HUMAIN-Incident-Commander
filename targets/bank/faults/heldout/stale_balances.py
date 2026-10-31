"""Extend the gateway's balance cache beyond its safe freshness window."""

import time

from targets.bank.faults.common import ACTORS

TYPE = "stale_balances"
CLASSES = ["bad_config"]


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameter")
    if params.get("target") != "gateway" or params.get("variant") != "v1":
        raise ValueError("unsupported target or variant")
    if not control.set_config("gateway", "balance_cache_ttl_s", 600.0, actor=rng.choice(ACTORS)):
        raise RuntimeError("setting change did not complete")
    return {"type": TYPE, "target": "gateway", "class": "bad_config",
            "detail": {"key": "balance_cache_ttl_s"}, "t": time.time()}
