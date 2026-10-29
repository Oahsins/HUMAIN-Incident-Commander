"""What every bank fault plugin shares.

A fault picks who appears to make its change from the same pool every change
uses, so the actor never gives away the fault type. Nothing a fault writes
(release labels, session names, log messages, change details) may name a fault
type or a root-cause class.
"""

ACTORS = ("pipeline", "operator", "ops-maintenance", "scheduler")


def actor(params, rng):
    return params.get("actor") or rng.choice(ACTORS)
