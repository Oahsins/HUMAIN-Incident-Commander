"""Practice fault: an operator changes a setting to a harmful value (root cause: bad_config).

The change is versioned and appears in the change log. The right fix is to
revert the component's last setting change.

params: {"target": ..., "key": ..., "value": ...}, or {"variant": name} for one of VARIANTS.
Under extra_service the target may be notifications (batch_size, poll_interval_s).
"""

import time

from targets.bank.faults.common import actor, check_target

TYPE = "bad_setting"
CLASSES = ["bad_config"]

VARIANTS = {
    # the transfer limit drops to 50.00 SAR: most payments are rejected
    "transfer_limit": {"target": "payments", "key": "max_transfer_minor", "value": 5_000},
    # fraud screening is given 2 ms to answer: every payment fails with "screening unavailable"
    "screening_timeout": {"target": "payments", "key": "screening_timeout_s", "value": 0.002},
    # the clearing worker is told to take no items at a time: nothing reaches the network
    "clearing_batch": {"target": "clearing", "key": "batch_size", "value": 0},
}


def inject(control, params, rng):
    if "key" in params:
        change = {"target": params.get("target", "payments"), "key": params["key"], "value": params["value"]}
    else:
        change = VARIANTS[params.get("variant") or rng.choice(sorted(VARIANTS))]
    check_target(control, change["target"])
    control.set_config(change["target"], change["key"], change["value"], actor=actor(params, rng))
    return {"type": TYPE, "target": change["target"], "class": "bad_config",
            "detail": {"key": change["key"], "value": change["value"]}, "t": time.time()}
