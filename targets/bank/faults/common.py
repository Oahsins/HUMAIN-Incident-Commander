"""What every bank fault plugin shares.

A fault picks who appears to make its change from the same pool every change
uses, so the actor never gives away the fault type. Nothing a fault writes
(release labels, session names, log messages, change details) may name a fault
type or a root-cause class.
"""

ACTORS = ("pipeline", "operator", "ops-maintenance", "scheduler")
EXTRA_SERVICE_ONLY = ("notifications",)


def actor(params, rng):
    return params.get("actor") or rng.choice(ACTORS)


def check_target(control, target):
    """A fault on notifications in a copy that does not run it would do nothing: refuse it instead."""
    if target in EXTRA_SERVICE_ONLY and target not in control.snapshot()["processes"]:
        raise ValueError(f"{target} runs only under the extra_service condition")
