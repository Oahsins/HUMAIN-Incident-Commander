"""The checker keys the evaluation reads (CONTRACT.md sections 10 and 11): time to mitigate in bucket order,
and the items set aside that are not poison. Invented ledgers and customer logs; no running bank."""

import json
import time

from ic.kit.conformance import check_verdict
from ic.kit.store import write_json
from targets.bank import checker, ledger, spec

SPAN_S = 50.0   # since_t is 60 s before the verdict, so impact covers [since_t, verdict - 10 s)


class Paths:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)

    def paths(self):
        return {"data_dir": self.data_dir, "customers_log": f"{self.data_dir}/customers.jsonl",
                "checker_baseline": f"{self.data_dir}/checker_baseline.json"}


def fresh_ledger(tmp_path, receipts=False):
    ledger.create(str(tmp_path), spec.CUSTOMERS)
    if receipts:
        ledger.add_receipts(str(tmp_path))
    write_json(str(tmp_path / "checker_baseline.json"), {"p95_ms": 50})
    return ledger.connect(str(tmp_path))


def traffic(tmp_path, since_t, failures=(), quiet=()):
    """A fresh balance read every 0.5 s from since_t on, and one failed payment at each offset in failures.
    No journey starts in the [start, end) offsets in quiet."""
    lines = []
    for i in range(int(SPAN_S * 2)):
        offset = i * 0.5
        if any(start <= offset < end for start, end in quiet):
            continue
        t = since_t + offset
        lines.append({"kind": "balance", "customer": "cust-01", "t": t, "t_end": t + 0.05, "ok": True,
                      "observed_minor": ledger.CUSTOMER_START_MINOR})
    for n, offset in enumerate(failures):
        t = since_t + offset
        lines.append({"kind": "payment", "customer": "cust-02", "t_start": t, "t_end": t + 0.2,
                      "end_to_end_id": f"e2e-failed-{n}", "amount_minor": 1500, "outcome": "failed"})
    with open(tmp_path / "customers.jsonl", "w", encoding="utf-8") as handle:
        handle.writelines(json.dumps(line) + "\n" for line in lines)


def verdict(tmp_path, since_t):
    return checker.verify(Paths(tmp_path), window_s=20.0, lag_s=10.0, since_t=since_t)


def test_time_to_mitigate_follows_the_order_of_the_buckets(tmp_path):
    fresh_ledger(tmp_path)
    since_t = time.time() - 60
    traffic(tmp_path, since_t, failures=(1.2, 12.1, 27.3))   # buckets 0, 2 and 5 miss the SLO
    impact = verdict(tmp_path, since_t)["impact"]
    assert impact["breach_seconds"] == 15.0
    assert (impact["time_to_mitigate_s"], impact["mitigation_censored"]) == (30.0, False)


def test_a_failure_in_the_last_bucket_is_censored(tmp_path):
    fresh_ledger(tmp_path)
    since_t = time.time() - 60
    traffic(tmp_path, since_t, failures=(3.0, 47.6))
    impact = verdict(tmp_path, since_t)["impact"]
    assert impact["mitigation_censored"] is True
    assert abs(impact["time_to_mitigate_s"] - (impact["until_t"] - since_t)) < 0.06


def test_a_quiet_spell_after_a_missed_bucket_is_not_mitigation(tmp_path):
    fresh_ledger(tmp_path)
    since_t = time.time() - 60
    traffic(tmp_path, since_t, failures=(26.0,), quiet=((30.0, 35.0),))
    impact = verdict(tmp_path, since_t)["impact"]
    assert impact["breach_seconds"] == 5.0
    assert (impact["time_to_mitigate_s"], impact["mitigation_censored"]) == (35.0, False)


def test_a_quiet_case_has_nothing_to_mitigate(tmp_path):
    fresh_ledger(tmp_path)
    since_t = time.time() - 60
    traffic(tmp_path, since_t)
    result = verdict(tmp_path, since_t)
    assert result["recovered"], result["reasons"]
    assert (result["impact"]["time_to_mitigate_s"], result["impact"]["mitigation_censored"]) == (0.0, False)
    assert result["integrity"]["harmful_quarantines"] == 0
    assert check_verdict(result) == []
    assert check_verdict(checker.verify(Paths(tmp_path), window_s=20.0, lag_s=10.0), impact=False) == []


def post(conn, payment_id):
    conn.execute("BEGIN IMMEDIATE")
    ledger.post_payment(conn, payment_id, f"e2e-{payment_id}", "cust-01", "BANK2", "ben-1", 1500, "SAR", "1.3")
    conn.execute("COMMIT")


def test_only_healthy_items_set_aside_count_as_harmful(tmp_path):
    conn = fresh_ledger(tmp_path)
    since_t = time.time() - 60
    traffic(tmp_path, since_t)
    post(conn, "p-1")
    post(conn, "p-2")
    now = time.time()
    conn.execute("INSERT INTO clearing_queue (payment_id, payload_json, status, attempts, created_t, updated_t) "
                 "VALUES ('p-3', '{\"payment_id\": \"p-3\"', 'quarantined', 3, ?, ?)", (now, now))   # poison
    conn.execute("UPDATE clearing_queue SET status = 'quarantined' WHERE payment_id = 'p-1'")
    result = verdict(tmp_path, since_t)
    assert (result["integrity"]["wrongly_quarantined"], result["integrity"]["harmful_quarantines"]) == (1, 1)
    assert not result["recovered"]


def test_every_receipt_set_aside_counts_as_harmful(tmp_path):
    conn = fresh_ledger(tmp_path, receipts=True)
    since_t = time.time() - 60
    traffic(tmp_path, since_t)
    post(conn, "p-1")
    post(conn, "p-2")
    conn.execute("UPDATE receipt_queue SET status = 'quarantined'")
    conn.execute("UPDATE clearing_queue SET status = 'quarantined' WHERE payment_id = 'p-2'")
    result = verdict(tmp_path, since_t)
    assert (result["integrity"]["receipts_set_aside"], result["integrity"]["harmful_quarantines"]) == (2, 3)
    assert check_verdict(result) == []


def test_a_verdict_without_the_generic_keys_is_reported():
    problems = check_verdict({"recovered": True, "journeys": {"n": 3}, "integrity": {"ok": True}, "impact": {}})
    assert "verdict: slo_ok must be true or false" in problems
    assert "verdict: integrity.harmful_quarantines must be a whole number" in problems
    assert "verdict: impact.mitigation_censored must be true or false" in problems
    assert any("for_operations" in p for p in problems)
