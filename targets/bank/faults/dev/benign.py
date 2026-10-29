"""Background change: something harmless that changes while a real fault is happening.

Real incidents happen on busy systems, where other people are deploying and
tuning things too. A scenario adds one or two of these next to its real
faults, so "undo every recent change" is not a winning strategy and the agent
has to show that a change actually caused the symptoms. None of these changes
hurts customers.

params: {"variant": one of VARIANTS (default: a random one), "actor": optional}
"""

import time

from targets.bank.faults.common import actor

TYPE = "benign"
CLASSES = []

VARIANTS = {
    "poll_interval": ("config", "clearing", "poll_interval_s", 0.25),
    "batch_size": ("config", "clearing", "batch_size", 60),
    "gateway_timeout": ("config", "gateway", "payments_timeout_s", 3.0),
    "cache_ttl": ("config", "gateway", "balance_cache_ttl_s", 0.4),
    "standby_release": ("deploy", "screening-standby", None, "4.1.1"),
    "standby_restart": ("restart", "screening-standby", None, None),
}


def inject(control, params, rng):
    variant = params.get("variant") or rng.choice(sorted(VARIANTS))
    kind, target, key, value = VARIANTS[variant]
    who = actor(params, rng)
    if kind == "config":
        control.set_config(target, key, value, actor=who)
    elif kind == "deploy":
        control.deploy(target, value, actor=who)
    else:
        control.stop(target, actor=who)
        control.start(target, actor=who)
    return {"type": TYPE, "target": None, "class": None,
            "detail": {"variant": variant, "component": target, "actor": who}, "t": time.time()}
