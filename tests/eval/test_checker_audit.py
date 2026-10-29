"""Plant one defect at a time in invented records to audit the bank's checker.

These are small ledgers, not scenarios or fault plugins. The checker must
detect the planted defect without inventing a second accounting defect.
"""

import json

import pytest

from targets.bank import checker, ledger


COUNTS = (
    "unbalanced_payments", "double_postings", "ghost_payments", "lost_payments",
    "stuck_items", "wrongly_quarantined", "stale_reads",
)


class Files:
    def __init__(self, folder):
        self.folder = folder

    def paths(self):
        return {
            "data_dir": str(self.folder),
            "customers_log": str(self.folder / "customers.jsonl"),
            "checker_baseline": str(self.folder / "checker_baseline.json"),
        }


def make_records(tmp_path, monkeypatch):
    monkeypatch.setattr(checker.time, "time", lambda: 100.0)
    ledger.create(str(tmp_path), ["fixture-customer"])
    (tmp_path / "checker_baseline.json").write_text(
        json.dumps({"p95_ms": 100}), encoding="utf-8")
    # Plenty of healthy journeys inside [70, 90), without creating money flows.
    records = [
        {"kind": "balance", "t": 72 + i / 2, "t_end": 72.1 + i / 2,
         "customer": "fixture-customer", "ok": True,
         "observed_minor": ledger.CUSTOMER_START_MINOR}
        for i in range(24)
    ]
    return records


def post(tmp_path, monkeypatch, payment_id="fixture-payment", e2e="fixture-e2e", t=85):
    with monkeypatch.context() as clock:
        clock.setattr(ledger.time, "time", lambda: t)
        conn = ledger.connect(str(tmp_path))
        try:
            conn.execute("BEGIN IMMEDIATE")
            ledger.post_payment(conn, payment_id, e2e, "fixture-customer",
                                "test-network", "test-beneficiary", 100, "SAR", "fixture")
            conn.execute("UPDATE clearing_queue SET status='cleared', updated_t=?", (t + .1,))
            conn.execute("COMMIT")
        finally:
            conn.close()


def payment(e2e="fixture-e2e", start=85, end=85.1, outcome="ok"):
    return {"kind": "payment", "t_start": start, "t_end": end,
            "end_to_end_id": e2e, "customer": "fixture-customer",
            "amount_minor": 100, "outcome": outcome}


def verify(tmp_path, records):
    (tmp_path / "customers.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return checker.verify(Files(tmp_path), window_s=20, lag_s=10, since_t=70)


def only_count(verdict, expected=None):
    assert verdict["integrity"]["money_conserved"]
    assert verdict["integrity"]["balances_match_postings"]
    assert {key: verdict["integrity"][key] for key in COUNTS} == {
        key: int(key == expected) for key in COUNTS}


def test_healthy_fixture_is_green(tmp_path, monkeypatch):
    verdict = verify(tmp_path, make_records(tmp_path, monkeypatch))
    only_count(verdict)
    assert verdict["recovered"]


@pytest.mark.parametrize("defect", [
    "double_postings", "ghost_payments", "lost_payments", "stale_reads",
    "wrongly_quarantined",
])
def test_one_planted_defect_is_identified_exactly(tmp_path, monkeypatch, defect):
    records = make_records(tmp_path, monkeypatch)
    if defect in {"double_postings", "ghost_payments", "wrongly_quarantined"}:
        post(tmp_path, monkeypatch)
    if defect == "double_postings":
        post(tmp_path, monkeypatch, payment_id="fixture-duplicate")
        records.append(payment())
    elif defect == "lost_payments":
        records.append(payment())
    elif defect == "stale_reads":
        records[0]["observed_minor"] -= 1000
    elif defect == "wrongly_quarantined":
        records.append(payment())
        conn = ledger.connect(str(tmp_path))
        try:
            conn.execute("UPDATE clearing_queue SET status='quarantined'")
        finally:
            conn.close()
    verdict = verify(tmp_path, records)
    only_count(verdict, defect)
    assert not verdict["recovered"]


def test_failure_in_flight_at_horizon_is_counted_after_lag(tmp_path, monkeypatch):
    records = make_records(tmp_path, monkeypatch)
    # Starts before H=90, finishes after H, and is available at verdict H+10.
    # Filtering on completion time would miss this failed customer journey.
    records.append(payment(start=89, end=99, outcome="failed"))
    verdict = verify(tmp_path, records)
    only_count(verdict)
    assert verdict["journeys"]["n"] == 25
    assert verdict["journeys"]["ok"] == 24
    assert verdict["journeys"]["payments"] == {"n": 1, "ok": 0}
    assert verdict["impact"]["failed_journeys"] == 1
    assert not verdict["slo_ok"]
    assert not verdict["recovered"]


def test_payment_started_after_horizon_is_not_a_ghost(tmp_path, monkeypatch):
    records = make_records(tmp_path, monkeypatch)
    post(tmp_path, monkeypatch, t=95)
    # This customer has not finished at verdict time; it is outside the window.
    verdict = verify(tmp_path, records)
    only_count(verdict)
    assert verdict["recovered"]
