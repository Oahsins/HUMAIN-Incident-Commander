"""The unrecorded_payments practice fault: its release answers some payments without writing them, and nothing else changes."""

import inspect
import os
import random
import shutil
import sqlite3
import uuid

import pytest

from ic import inject
from ic.kit import net, run_service
from ic.kit.store import Releases
from targets.bank import checker, ledger

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAULT = inject.load("bank", "unrecorded_payments")
BANNED = ("fault", "inject", "sealed", "heldout", "exam", "poison", "stale", "chaos", "crash", "unrecorded",
          "bad_update", "bad_setting", "locked_ledger", "stopped_worker", "slow_screening", "noise",
          "network_outage", "benign", "double_posting", "process_down", "bad_release", "bad_config", "lock_held",
          "dependency_slow", "external_outage", "resource_exhaustion")


def release_module(data_dir, version="1.3.1"):
    """Register the fault's release in a copy the way Control.deploy does, and load it the way a service does."""
    copy = os.path.join(str(data_dir), "releases", "payments", "v" + version.replace(".", "_") + ".py")
    os.makedirs(os.path.dirname(copy), exist_ok=True)
    shutil.copyfile(FAULT.MODULE, copy)
    Releases(str(data_dir)).init({"payments": "1.3"})
    Releases(str(data_dir)).deploy("payments", version, module_path=copy)
    return copy, run_service.load_release("bank", "payments", "payments", version, str(data_dir))


@pytest.fixture()
def release(tmp_path, monkeypatch):
    ledger.create(str(tmp_path), ["cust-01"])
    _, cls = release_module(tmp_path)
    rel = cls({"component": "payments", "version": "1.3.1", "port": 0, "data_dir": str(tmp_path), "ports": {}})
    monkeypatch.setattr(rel, "screen", lambda body, amount: {"decision": "pass"})
    return rel


def skipped(release, wanted, account="cust-01"):
    module = inspect.getmodule(type(release))
    return next(f"{account}-{n:06d}" for n in range(1, 1000) if module.skips_write(f"{account}-{n:06d}") == wanted)


def body(end_to_end_id, **changes):
    return {"from_acct": "cust-01", "amount_minor": 1500, "currency": "SAR", "beneficiary_bank": "BANK-A",
            "beneficiary_acct": "ben-001", "end_to_end_id": end_to_end_id, **changes}


def rows(tmp_path):
    conn = sqlite3.connect(ledger.path(str(tmp_path)))
    try:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("payments", "postings", "clearing_queue"))
    finally:
        conn.close()


def test_a_skipped_payment_is_answered_as_posted_but_never_written(release, tmp_path):
    answer = release.pay({"body": body(skipped(release, True))})
    assert answer["status"] == "posted" and len(answer["payment_id"]) == 16 and answer["replayed"] is False
    assert rows(tmp_path) == (0, 0, 0)
    with pytest.raises(net.Reply) as looked_up:
        release.payment({"tail": answer["payment_id"]})
    assert looked_up.value.status == 404 and looked_up.value.body == {"error": "unknown payment"}


def test_a_retry_of_a_skipped_payment_is_skipped_again(release, tmp_path):
    e2e = skipped(release, True)
    first, second = release.pay({"body": body(e2e)}), release.pay({"body": body(e2e)})
    assert first["payment_id"] != second["payment_id"] and second["replayed"] is False
    assert rows(tmp_path) == (0, 0, 0)


def test_a_skipped_payment_is_still_checked_like_any_other(release, tmp_path):
    conn = sqlite3.connect(ledger.path(str(tmp_path)))
    conn.execute("INSERT INTO accounts VALUES ('cust-02', 'customer', 100)")
    conn.commit()
    conn.close()
    for changes, status, error in (({"from_acct": "nobody"}, 404, "unknown account"),
                                   ({"from_acct": "cust-02"}, 422, "insufficient funds"),
                                   ({"amount_minor": 10 ** 12}, 422, "amount exceeds transfer limit"),
                                   ({"amount_minor": 0}, 400, "amount must be positive")):
        with pytest.raises(net.Reply) as refused:
            release.pay({"body": body(skipped(release, True, changes.get("from_acct", "cust-01")), **changes)})
        assert (refused.value.status, refused.value.body) == (status, {"error": error}), changes
    assert rows(tmp_path) == (0, 0, 0)


def test_other_payments_post_as_in_1_3(release, tmp_path):
    answer = release.pay({"body": body(skipped(release, False))})
    assert rows(tmp_path) == (1, 2, 1)
    info = release.payment({"tail": answer["payment_id"]})
    assert info["postings"] == 2 and info["postings_sum_minor"] == 0


def test_about_half_of_customer_and_probe_payments_are_skipped(release):
    module = inspect.getmodule(type(release))
    customers = [f"cust-{c:02d}-{n:06d}" for c in range(1, 21) for n in range(1, 201)]
    probes = [f"probe-{n:05d}-{uuid.UUID(int=random.Random(n).getrandbits(128)).hex[:4]}" for n in range(1, 3001)]
    for ids in (customers, probes):
        assert 0.45 < sum(map(module.skips_write, ids)) / len(ids) < 0.55


def test_the_checker_counts_a_skipped_payment_as_lost_only_inside_the_window():
    told = [{"kind": "payment", "t_start": 5.0, "t_end": 5.1, "end_to_end_id": "cust-01-000001",
             "amount_minor": 1500, "outcome": "ok"}]
    assert checker.match_customers(told, {}, 0.0, 10.0) == (0, 1)
    assert checker.match_customers(told, {}, 6.0, 26.0) == (0, 0)


def test_the_fault_deploys_its_own_module_under_a_label_no_release_folder_has(tmp_path):
    calls = []

    class FakeControl:
        def deploy(self, component, release, module_path=None, actor="pipeline"):
            calls.append((component, release, module_path, actor))
            return True

    entry = FAULT.inject(FakeControl(), {}, random.Random(1))
    (component, label, module_path, actor), = calls
    assert (component, entry["target"], entry["class"]) == ("payments", "payments", "bad_release")
    assert module_path == FAULT.MODULE and os.path.basename(module_path).startswith("_")
    assert actor in ("pipeline", "operator", "ops-maintenance", "scheduler")
    built_in = os.path.join(ROOT, "targets", "bank", "releases", "payments", "v" + label.replace(".", "_") + ".py")
    assert not os.path.exists(built_in)
    assert "_unrecorded_release" not in inject.available("bank", allow_sealed=False)


def test_without_the_fault_the_label_resolves_to_nothing(tmp_path):
    Releases(str(tmp_path)).init({"payments": "1.3"})
    with pytest.raises(SystemExit):
        run_service.load_release("bank", "payments", "payments", FAULT.RELEASE, str(tmp_path))


def test_rolling_back_returns_to_the_release_before_it(tmp_path):
    release_module(tmp_path)
    assert Releases(str(tmp_path)).rollback("payments") == ("1.3.1", "1.3")
    assert Releases(str(tmp_path)).current("payments") == "1.3"


def test_nothing_the_agent_can_see_names_the_fault():
    source = open(FAULT.MODULE, encoding="utf-8").read()
    code = source.split('"""', 2)[2].lower()      # everything after the module docstring
    assert not [w for w in BANNED if w in code]
    assert not [w for w in BANNED if w in FAULT.RELEASE.lower()]
