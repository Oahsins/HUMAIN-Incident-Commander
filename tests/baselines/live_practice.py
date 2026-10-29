"""Manual six-fault smoke check on the reserved live-test copy (port base 8700).

Run with: python -m tests.baselines.live_practice
This is practice evidence, not an exam run or an independent recovery verdict.
"""

import json
from pathlib import Path
import time

from baselines.runbook import run_incident
from ic import inject, systems
from ic.guard import Guard


CASES = [
    ("crash", {"target": "payments"}, "restart", "payments"),
    ("bad_update", {}, "rollback", "payments"),
    ("bad_setting", {"variant": "transfer_limit"}, "revert_config", "payments"),
    ("locked_ledger", {}, "release_lock", "ledger"),
    ("stopped_worker", {}, "restart", "clearing"),
    ("slow_screening", {}, "failover", "screening"),
]


def main():
    evidence = []
    out = Path("runs/c2-practice.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    for index, (fault, params, action, target) in enumerate(CASES, 1):
        platform = systems.platform("bank", port_base=8700, seed=index)
        try:
            platform.start(warmup_s=10.0)
            inject.apply("bank", platform.control(), [{"type": fault, "at_s": 0, "params": params}],
                         seed=index, allow_sealed=False)
            time.sleep(5.0)
            result = run_incident(Guard(platform.adapter(), max_steps=40,
                                        audit_path=f"runs/audit/c2-{fault}.jsonl"))
            seen = [(a["action"], a["target"]) for a in result["actions"] if a["sent"]]
            passed = seen == [(action, target)] and result["outcome"] == "recovered"
            evidence.append({"practice_fault": fault, "result": result, "expected_action": [action, target],
                             "smoke_passed": passed, "checker_tested": False})
            print(json.dumps({"practice_fault": fault, "outcome": result["outcome"],
                              "actions": seen, "smoke_passed": passed}), flush=True)
        finally:
            platform.stop()
            out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return 0 if all(row["smoke_passed"] for row in evidence) else 1


if __name__ == "__main__":
    raise SystemExit(main())
