"""Write scenarios/dev/dev.jsonl: the 32 practice scenarios (CONTRACT.md section 8).

dev-01 to dev-20 are for building and tuning; dev-21 to dev-30 are kept for the
Friday pilot only; dev-31 and dev-32 were added after the pilot for silent drops. Each case lists its real faults by hand, with the fixes in
the order to apply them (upstream first, then the most impact per second), and
gets 1 to 3 harmless background changes picked from its own seed. Run it again
and the file comes out byte for byte the same:

    python scenarios/dev/make_dev.py
"""

import json
import os
import random

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev.jsonl")
BENIGN = ("poll_interval", "batch_size", "gateway_timeout", "cache_ttl", "standby_release", "standby_restart")


def fault(type_, at_s=0, **params):
    return {"type": type_, "at_s": at_s, "params": params}


def cause(target, class_, action, fix_target=None, **params):
    return {"target": target, "class": class_,
            "fix": {"action": action, "target": fix_target or target, "params": params}}


# Root causes, one per practice fault (CONTRACT.md sections 4 and 7.2).
PAYMENTS_DOWN = cause("payments", "process_down", "restart")
GATEWAY_DOWN = cause("gateway", "process_down", "restart")
CLEARING_DOWN = cause("clearing", "process_down", "restart")
SCREENING_DOWN = cause("screening", "process_down", "restart")
BAD_RELEASE = cause("payments", "bad_release", "rollback")
LIMIT = cause("payments", "bad_config", "revert_config", key="max_transfer_minor")
SCREENING_TIMEOUT = cause("payments", "bad_config", "revert_config", key="screening_timeout_s")
BATCH = cause("clearing", "bad_config", "revert_config", key="batch_size")
LOCK = cause("ledger", "lock_held", "release_lock")
SLOW = cause("screening", "dependency_slow", "failover", to="standby")
# Nothing the agent may do fixes an outage of the external network: the right answer is to escalate.
OUTAGE = cause("network", "external_outage", "escalate")

# (faults, root causes in fix order, notes)
CASES = [
    # dev-01 to dev-20: building and tuning
    ([fault("crash", target="payments")], [PAYMENTS_DOWN], "single: payments process killed"),
    ([fault("bad_update")], [BAD_RELEASE], "single: payments 1.4 fails on larger payments"),
    ([fault("bad_setting", variant="transfer_limit")], [LIMIT], "single: rejects, not errors"),
    ([fault("locked_ledger")], [LOCK], "single: the job holding the lock is not the target"),
    ([fault("stopped_worker")], [CLEARING_DOWN], "single: backlog grows, payments still accepted"),
    ([fault("slow_screening")], [SLOW], "single: slow dependency with a standby"),
    ([fault("bad_setting", target="payments", key="max_transfer_minor", value=5000),
      fault("stopped_worker", at_s=4, target="clearing")],
     [LIMIT, CLEARING_DOWN], "confusable: rejects vs backlog"),
    ([fault("crash", target="gateway")], [GATEWAY_DOWN], "single: the entry point is down"),
    ([fault("noise", variant="both")], [], "healthy: a harmless deploy and a busy job"),
    ([fault("network_outage")], [OUTAGE], "must escalate: the external network drops connections"),
    ([fault("bad_setting", variant="screening_timeout")], [SCREENING_TIMEOUT],
     "confusable: looks like a screening outage, the setting is on payments"),
    ([fault("crash", target="screening")], [SCREENING_DOWN], "single: a dependency process killed"),
    ([fault("bad_setting", variant="transfer_limit"), fault("slow_screening", at_s=3)],
     [SLOW, LIMIT], "double: failover first, then undo the limit; the failover must survive"),
    ([fault("locked_ledger"), fault("crash", at_s=5, target="payments")],
     [LOCK, PAYMENTS_DOWN], "double: upstream lock first, then the crashed caller"),
    ([fault("bad_update"), fault("slow_screening", at_s=2)],
     [SLOW, BAD_RELEASE], "double: errors from the release and slowness from the dependency"),
    ([fault("noise", variant="deploy"), fault("bad_setting", at_s=3, variant="clearing_batch")],
     [BATCH], "distractor: the gateway deploy is harmless; the batch size stops clearing"),
    ([fault("bad_setting", variant="screening_timeout"), fault("stopped_worker", at_s=6)],
     [SCREENING_TIMEOUT, CLEARING_DOWN], "double: two unrelated components"),
    ([fault("noise", variant="cpu", cpu_s=150)], [], "healthy: a busy job that is not a fault"),
    ([fault("slow_screening", latency_ms=900, jitter_ms=200)], [SLOW], "single: milder slowness"),
    ([fault("crash", target="payments"), fault("bad_setting", at_s=4, variant="clearing_batch"),
      fault("slow_screening", at_s=7)],
     [SLOW, BATCH, PAYMENTS_DOWN], "triple: upstream first, then the most impact per second"),
    # dev-21 to dev-30: the Friday pilot only
    ([fault("bad_update")], [BAD_RELEASE], "single: payments 1.4"),
    ([fault("locked_ledger"), fault("bad_setting", at_s=5, variant="transfer_limit")],
     [LOCK, LIMIT], "double: upstream lock first, then the limit"),
    ([fault("stopped_worker")], [CLEARING_DOWN], "single: clearing stopped"),
    ([fault("noise", variant="both")], [], "healthy"),
    ([fault("network_outage", drop_pct=1.0)], [OUTAGE], "must escalate"),
    ([fault("crash", target="gateway"), fault("slow_screening", at_s=4)],
     [SLOW, GATEWAY_DOWN], "double: screening is upstream of the gateway through payments"),
    ([fault("bad_setting", variant="clearing_batch")], [BATCH], "single: clearing takes nothing"),
    ([fault("crash", target="clearing")], [CLEARING_DOWN], "single: clearing killed"),
    ([fault("bad_setting", variant="screening_timeout"), fault("locked_ledger", at_s=3)],
     [LOCK, SCREENING_TIMEOUT], "double: the ledger is upstream of payments"),
    ([fault("bad_update"), fault("noise", at_s=2, variant="deploy"), fault("stopped_worker", at_s=5)],
     [CLEARING_DOWN, BAD_RELEASE], "double with a distractor: rollback only payments"),
    # dev-31 and dev-32: added before freeze-1 for silent drops (payments answered but never written)
    ([fault("unrecorded_payments")], [BAD_RELEASE],
     "single: about half of payments are answered as posted but never reach the ledger; nothing errors"),
    ([fault("unrecorded_payments"), fault("stopped_worker", at_s=4)],
     [BAD_RELEASE, CLEARING_DOWN],
     "double: the stopped worker is loud, the unwritten payments are not; roll back first, since an unwritten "
     "payment is lost for good while the clearing backlog only waits"),
]


def background(n, faults):
    """1 to 3 harmless changes at seeded offsets inside the fault window (0 to 8 s)."""
    rng = random.Random(1000 + n)
    allowed = list(BENIGN)
    if any(f["params"].get("variant") == "clearing_batch" or f["params"].get("key") == "batch_size" for f in faults):
        allowed.remove("batch_size")     # it would set the same key and hide the fault
    picked = rng.sample(allowed, rng.randint(1, 3))
    return [fault("benign", at_s=rng.randrange(0, 17) / 2, variant=v) for v in picked]


def case(n, faults, causes, notes):
    every = sorted(faults + background(n, faults), key=lambda f: f["at_s"])
    return {"id": f"dev-{n:02d}",
            "input": {"system": "bank", "seed": n, "condition": "default", "faults": every},
            "target": {"root_causes": causes, "healthy": not causes,
                       "must_escalate": any(c["fix"]["action"] == "escalate" for c in causes),
                       "blind": False, "acceptable_secondary": [], "notes": notes}}


def main():
    with open(OUT, "w", encoding="utf-8", newline="\n") as out:
        for n, (faults, causes, notes) in enumerate(CASES, 1):
            out.write(json.dumps(case(n, faults, causes, notes)) + "\n")
    print(f"wrote {len(CASES)} cases to {OUT}")


if __name__ == "__main__":
    main()
