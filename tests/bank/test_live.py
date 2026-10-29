"""Live copies of the test bank, end to end (about three minutes; runs when IC_SLOW=1, as CI does).

A bad payments setting and slow screening at once. Failing screening over and
then undoing the setting must restore the limit and keep the standby serving:
undoing a setting never undoes a failover. Then the extra_service condition: a
stopped notifications worker and a harmful notifications setting each turn the
checker red through late receipts, and restarting or undoing fixes them.
"""

import os
import time

import pytest

from ic import contract, inject, systems
from ic.kit.conformance import check_adapter, check_verdict

pytestmark = pytest.mark.skipif(os.environ.get("IC_SLOW") != "1", reason="starts live copies of the test bank; set IC_SLOW=1")


@pytest.fixture()
def bank():
    platform = systems.platform("bank", port_base=8700, seed=1)
    platform.start(warmup_s=8)
    try:
        yield platform
    finally:
        platform.stop()


def test_bank_adapter_keeps_the_contract(bank):
    assert check_adapter(bank.adapter()) == []


def test_two_faults_fixed_with_failover_then_revert(bank):
    adapter, control = bank.adapter(), bank.control()
    checker = systems.checker("bank")
    t_fault = time.time()
    inject.apply("bank", control, [{"type": "bad_setting", "at_s": 0, "params": {"variant": "transfer_limit"}},
                                   {"type": "slow_screening", "at_s": 0, "params": {}}], seed=1)
    time.sleep(6)

    seen = adapter.observe(5)["components"]["payments"]
    assert seen["reject_rate"] > 0.02                                          # the limit refuses payments
    assert seen["extra"]["dependencies"]["screening"]["p95_ms"] > 500          # screening answers slowly
    assert not checker.verify(control, window_s=5, lag_s=0)["recovered"]

    assert adapter.act("failover", "screening", {"to": "standby"})["ok"]
    assert adapter.act("revert_config", "payments", {})["ok"]
    time.sleep(contract.CHECK_WINDOW_S + contract.CHECK_LAG_S + 2)

    verdict = checker.verify(control, window_s=contract.CHECK_WINDOW_S, lag_s=contract.CHECK_LAG_S, since_t=t_fault)
    assert verdict["recovered"], verdict["reasons"]
    assert check_verdict(verdict) == []
    assert verdict["impact"]["time_to_mitigate_s"] >= 5        # the first bucket refused most payments
    assert verdict["integrity"]["harmful_quarantines"] == 0
    snapshot = control.snapshot()
    assert snapshot["routing"] == {"screening": "standby"}
    assert snapshot["config"]["payments"]["max_transfer_minor"] == 1_000_000
    assert adapter.observe(5)["components"]["screening"]["extra"]["active"] == "standby"


@pytest.fixture()
def bank_with_notifications():
    platform = systems.platform("bank", port_base=8700, seed=2, condition="extra_service")
    platform.start(warmup_s=8)
    try:
        yield platform
    finally:
        platform.stop()


def receipts_flow(control, timeout_s=30):
    """Until receipts are going out and none has waited more than 2 s."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        conn = control.db()
        try:
            sent, oldest = conn.execute("SELECT SUM(status = 'sent'), MIN(CASE WHEN status = 'pending' "
                                        "THEN created_t END) FROM receipt_queue").fetchone()
        finally:
            conn.close()
        if sent and (oldest is None or time.time() - oldest < 2):
            return True
        time.sleep(1)
    return False


def test_notifications_faults_turn_the_checker_red_until_fixed(bank_with_notifications):
    bank = bank_with_notifications
    adapter, control = bank.adapter(), bank.control()
    checker = systems.checker("bank")
    assert check_adapter(adapter) == []
    assert "notifications" in [c["name"] for c in adapter.describe()["components"]]
    assert receipts_flow(control), "receipts should flow on a healthy copy"
    assert control.snapshot()["receipts"].get("sent")

    for fault, fix in (({"type": "stopped_worker", "at_s": 0, "params": {"target": "notifications"}},
                        ("restart", {})),
                       ({"type": "bad_setting", "at_s": 0,
                         "params": {"target": "notifications", "key": "poll_interval_s", "value": 600}},
                        ("revert_config", {}))):
        inject.apply("bank", control, [fault], seed=2)
        time.sleep(14)
        seen = adapter.observe(5)["components"]["notifications"]
        assert seen["extra"]["queue_depth"] > 0 and seen["extra"]["oldest_pending_s"] > 10, seen
        verdict = checker.verify(control, window_s=5, lag_s=0)
        assert not verdict["recovered"] and verdict["integrity"]["waiting_receipts"] > 0, verdict["reasons"]

        assert adapter.act(fix[0], "notifications", fix[1])["ok"]
        time.sleep(contract.CHECK_WINDOW_S + contract.CHECK_LAG_S + 2)
        verdict = checker.verify(control, window_s=contract.CHECK_WINDOW_S, lag_s=contract.CHECK_LAG_S)
        assert verdict["recovered"], (fault["type"], verdict["reasons"])
        assert check_verdict(verdict, impact=False) == []
