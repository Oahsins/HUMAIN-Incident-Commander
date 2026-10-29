"""The extra_service condition: the notifications component, its receipt queue and the checker's receipt rule
(no running bank needed; tests/bank/test_live.py runs it live)."""

import json
import random
import threading
import time

import pytest

from ic import inject
from ic.kit.store import ConfigStore, write_json
from targets.bank import checker, ledger, spec
from targets.bank.releases.notifications.v1_0 import Release


def names(components):
    return [c["name"] for c in components]


def test_extra_service_adds_notifications_after_clearing_and_nothing_else():
    bank = spec.Spec()
    default, extra = bank.components("default"), bank.components("extra_service")
    assert "notifications" not in names(default)
    assert [n for n in names(extra) if n != "notifications"] == names(default)
    assert names(extra).index("notifications") == names(extra).index("clearing") + 1
    assert "notifications" not in bank.start_order("default")
    assert bank.start_order("extra_service") == [n if n != "gateway" else "notifications"
                                                 for n in bank.start_order("default")] + ["gateway"]
    entry = spec.NOTIFICATIONS
    assert (entry["kind"], entry["depends_on"], entry["impact_weight"], entry["port_offset"]) == \
        ("worker", ["ledger"], 0.1, 8)
    assert entry["actions"] == ["restart", "rollback", "revert_config", "quarantine"]
    assert set(entry["config"]) == {"batch_size", "poll_interval_s"}
    assert {c["port_offset"] for c in default} | {8} == {c["port_offset"] for c in extra}


def fresh_ledger(tmp_path, receipts=True):
    ledger.create(str(tmp_path), spec.CUSTOMERS)
    if receipts:
        ledger.add_receipts(str(tmp_path))
    return ledger.connect(str(tmp_path))


def post(conn, payment_id, amount=1500):
    conn.execute("BEGIN IMMEDIATE")
    ledger.post_payment(conn, payment_id, f"e2e-{payment_id}", "cust-01", "BANK2", "ben-1", amount, "SAR", "1.3")
    conn.execute("COMMIT")


def test_a_posted_payment_queues_exactly_one_receipt(tmp_path):
    conn = fresh_ledger(tmp_path)
    post(conn, "p-1")
    now = time.time()
    conn.execute("INSERT INTO payments VALUES ('p-2', 'e2e-p-2', 'cust-02', 'BANK2', 'ben-1', 900, 'SAR', "
                 "'rejected', '1.3', ?, ?)", (now, now))
    rows = conn.execute("SELECT payment_id, status, created_t FROM receipt_queue").fetchall()
    created = conn.execute("SELECT created_t FROM payments WHERE id = 'p-1'").fetchone()[0]
    assert [(r["payment_id"], r["status"], r["created_t"]) for r in rows] == [("p-1", "pending", created)]
    assert ledger.queue_state(conn, "receipt_queue")["queue_depth"] == 1
    with pytest.raises(ValueError):
        ledger.queue_state(conn, "payments")


def test_the_default_ledger_has_no_receipt_queue(tmp_path):
    conn = fresh_ledger(tmp_path, receipts=False)
    post(conn, "p-1")
    assert not checker.Ledger(conn).has_receipts()
    assert ledger.queue_state(conn)["queue_depth"] == 1   # the clearing queue is unchanged


class Paths:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)

    def paths(self):
        return {"data_dir": self.data_dir, "customers_log": f"{self.data_dir}/customers.jsonl",
                "checker_baseline": f"{self.data_dir}/checker_baseline.json"}


def healthy_traffic(tmp_path, now):
    """25 fresh balance reads in the scored window, so only the receipt rule can turn the checker red."""
    with open(tmp_path / "customers.jsonl", "w", encoding="utf-8") as handle:
        for i in range(25):
            t = now - 29 + i * 0.5
            handle.write(json.dumps({"kind": "balance", "customer": "cust-01", "t": t, "t_end": t + 0.05,
                                     "ok": True, "observed_minor": ledger.CUSTOMER_START_MINOR}) + "\n")
    write_json(str(tmp_path / "checker_baseline.json"), {"p95_ms": 50})


def add_receipt(conn, status, created_ago, sent_after=None):
    now = time.time()
    created = now - created_ago
    updated = created + sent_after if sent_after is not None else created
    conn.execute("INSERT INTO receipt_queue (payment_id, status, attempts, created_t, updated_t) "
                 "VALUES ('p-x', ?, 0, ?, ?)", (status, created, updated))


def verdict(tmp_path):
    return checker.verify(Paths(tmp_path), window_s=20.0, lag_s=10.0)


def test_receipts_that_keep_up_leave_the_checker_green(tmp_path):
    conn = fresh_ledger(tmp_path)
    healthy_traffic(tmp_path, time.time())
    add_receipt(conn, "sent", created_ago=25, sent_after=0.3)
    add_receipt(conn, "pending", created_ago=2)
    result = verdict(tmp_path)
    assert result["recovered"], result["reasons"]
    assert (result["integrity"]["waiting_receipts"], result["integrity"]["late_receipts"],
            result["integrity"]["receipts_set_aside"]) == (0, 0, 0)


@pytest.mark.parametrize("status,created_ago,sent_after,reason", [
    ("pending", 15, None, "1 receipts waiting more than 10 s to be sent"),
    ("sent", 25, 12, "1 receipts sent more than 10 s after the payment"),
    ("quarantined", 200, None, "1 receipts set aside"),
])
def test_each_receipt_failure_turns_the_checker_red(tmp_path, status, created_ago, sent_after, reason):
    conn = fresh_ledger(tmp_path)
    healthy_traffic(tmp_path, time.time())
    add_receipt(conn, status, created_ago, sent_after)
    result = verdict(tmp_path)
    assert not result["recovered"] and not result["integrity"]["ok"]
    assert result["reasons"] == [reason]


def test_a_receipt_sent_late_before_the_window_does_not_count(tmp_path):
    conn = fresh_ledger(tmp_path)
    healthy_traffic(tmp_path, time.time())
    add_receipt(conn, "sent", created_ago=120, sent_after=90)   # the backlog from an outage, since sent
    assert verdict(tmp_path)["recovered"]
    assert checker.Ledger(conn).late_receipts(time.time() - 200, time.time()) == 1


def test_the_default_verdict_has_no_receipt_keys(tmp_path):
    fresh_ledger(tmp_path, receipts=False)
    healthy_traffic(tmp_path, time.time())
    result = verdict(tmp_path)
    assert result["recovered"], result["reasons"]
    assert not any("receipt" in key for key in result["integrity"])


def worker(tmp_path, **settings):
    ConfigStore(str(tmp_path), "notifications").init({"poll_interval_s": 0.2, "batch_size": 50, **settings})
    return Release({"component": "notifications", "version": "1.0", "port": 0, "data_dir": str(tmp_path),
                    "ports": {}})


def test_the_worker_uses_only_settings_it_can_use(tmp_path):
    assert worker(tmp_path).settings() == (50, 0.2)
    for bad in ({"batch_size": 0}, {"batch_size": -1}, {"batch_size": "many"}, {"poll_interval_s": 0},
                {"poll_interval_s": -2}, {"poll_interval_s": None}, {"poll_interval_s": float("nan")}):
        assert worker(tmp_path, **bad).settings() is None, bad
    assert worker(tmp_path, poll_interval_s=600).settings() == (50, 600.0)


def test_a_corrected_setting_ends_the_wait_between_polls(tmp_path):
    release = worker(tmp_path, poll_interval_s=600)
    threading.Timer(0.4, lambda: ConfigStore(str(tmp_path), "notifications").set("poll_interval_s", 0.2,
                                                                                  "operator")).start()
    started = time.time()
    release.wait(600)
    assert time.time() - started < 3


def test_the_worker_sends_the_oldest_receipts_and_marks_them(tmp_path):
    conn = fresh_ledger(tmp_path)
    for i in range(3):
        post(conn, f"p-{i}")
    release = worker(tmp_path, batch_size=2)
    release.conn = ledger.connect(str(tmp_path))
    items = release.conn.execute(
        "SELECT q.id, q.payment_id, p.end_to_end_id, p.from_acct, p.amount_minor, p.currency FROM receipt_queue q "
        "JOIN payments p ON p.id = q.payment_id WHERE q.status = 'pending' ORDER BY q.id LIMIT 2").fetchall()
    release.send(items)
    sent = [json.loads(line) for line in open(tmp_path / "receipts.jsonl", encoding="utf-8")]
    assert [r["payment_id"] for r in sent] == ["p-0", "p-1"] and sent[0]["to"] == "cust-01"
    assert {row[0]: row[1] for row in conn.execute("SELECT payment_id, status FROM receipt_queue")} == \
        {"p-0": "sent", "p-1": "sent", "p-2": "pending"}


class Control:
    """A fake Control for a copy that does (or does not) run notifications."""

    def __init__(self, runs_notifications):
        self.processes = {"payments": True, "clearing": True, **({"notifications": True} if runs_notifications else {})}
        self.calls = []

    def snapshot(self):
        return {"processes": self.processes}

    def __getattr__(self, name):
        if name not in ("kill", "stop", "set_config"):
            raise AttributeError(name)
        return lambda *args, **kwargs: self.calls.append((name, args)) or True


FAULTS = [("crash", {"target": "notifications"}, "kill"),
          ("stopped_worker", {"target": "notifications"}, "stop"),
          ("bad_setting", {"target": "notifications", "key": "batch_size", "value": 0}, "set_config")]


@pytest.mark.parametrize("fault_type,params,call", FAULTS)
def test_faults_on_notifications_need_a_copy_that_runs_it(fault_type, params, call):
    module = inject.load("bank", fault_type)
    with pytest.raises(ValueError, match="extra_service"):
        module.inject(Control(False), dict(params), random.Random(1))
    control = Control(True)
    entry = module.inject(control, dict(params), random.Random(1))
    assert entry["target"] == "notifications" and entry["class"] in module.CLASSES
    assert [c[0] for c in control.calls] == [call] and control.calls[0][1][0] == "notifications"


def test_faults_elsewhere_never_ask_for_a_snapshot():
    class NoSnapshot(Control):
        def snapshot(self):
            raise AssertionError("only a fault on notifications checks the copy")
    for fault_type, params in (("crash", {}), ("stopped_worker", {}), ("bad_setting", {"variant": "clearing_batch"})):
        inject.load("bank", fault_type).inject(NoSnapshot(False), params, random.Random(1))


def test_quarantine_reaches_the_right_queue(tmp_path):
    conn = fresh_ledger(tmp_path)
    post(conn, "p-1")

    class Sup:
        data_dir = str(tmp_path)
        changes = type("Changes", (), {"add": lambda self, *a, **k: None})()

    bank = spec.Spec()
    receipt = conn.execute("SELECT id FROM receipt_queue").fetchone()[0]
    item = conn.execute("SELECT id FROM clearing_queue").fetchone()[0]
    assert bank.act(Sup(), "quarantine", "notifications", {"item": receipt}, "operator") == \
        (True, f"notifications item {receipt} set aside for the operations team")
    assert bank.act(Sup(), "quarantine", "clearing", {"item": item}, "operator") == \
        (True, f"clearing item {item} set aside for the operations team")
    assert bank.act(Sup(), "quarantine", "clearing", {"item": item}, "operator") == \
        (False, f"no pending clearing item {item}")
    assert conn.execute("SELECT status FROM receipt_queue").fetchone()[0] == "quarantined"
    assert conn.execute("SELECT status FROM clearing_queue").fetchone()[0] == "quarantined"
