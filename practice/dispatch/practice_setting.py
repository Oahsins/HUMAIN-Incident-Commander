"""Dispatch practice fault: an operator sets a harmful value (root cause: bad_config).

Public practice for trying the agent on dispatch from the console. It is not part of
any exam. The change is versioned and appears in the change log, so the right fix
is to revert the component's last setting change.

params: {"variant": name} for one of VARIANTS (default: slow_dispatch)
"""

import time

TYPE = "practice_setting"
CLASSES = ["bad_config"]

VARIANTS = {
    # the dispatcher looks for new incidents every 30 s instead of every 0.2 s: units go out late
    "slow_dispatch": {"target": "dispatcher", "key": "poll_interval_s", "value": 30},
}


def inject(control, params, rng):
    change = VARIANTS[params.get("variant") or "slow_dispatch"]
    control.set_config(change["target"], change["key"], change["value"], actor=params.get("actor", "operator"))
    return {"type": TYPE, "target": change["target"], "class": "bad_config",
            "detail": {"key": change["key"], "value": change["value"]}, "t": time.time()}
