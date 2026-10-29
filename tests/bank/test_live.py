"""One live copy of the test bank, end to end (about a minute; runs when IC_SLOW=1, as CI does).

A bad payments setting and slow screening at once. Failing screening over and
then undoing the setting must restore the limit and keep the standby serving:
undoing a setting never undoes a failover.
"""

import os
import time

import pytest

from ic import contract, inject, systems
from ic.kit.conformance import check_adapter

pytestmark = pytest.mark.skipif(os.environ.get("IC_SLOW") != "1", reason="starts a live copy of the test bank; set IC_SLOW=1")


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
    snapshot = control.snapshot()
    assert snapshot["routing"] == {"screening": "standby"}
    assert snapshot["config"]["payments"]["max_transfer_minor"] == 1_000_000
    assert adapter.observe(5)["components"]["screening"]["extra"]["active"] == "standby"
