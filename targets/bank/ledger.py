"""The test bank's double-entry ledger, kept in one SQLite file.

Every payment has exactly two postings that sum to zero: a debit on the
customer's account and a credit on the settlement account for the national
payment network. Balances live on the accounts table and change in the same
transaction as the postings, so total money never changes.

Amounts are whole halalas ("minor units"): 100 = 1.00 SAR.
"""

import json
import os
import sqlite3
import time

SETTLEMENT = "settlement:network"
PROBE = "probe-01"
CUSTOMER_START_MINOR = 1_000_000_000      # 10,000,000.00 SAR each, so test customers never run dry
PROBE_START_MINOR = 100_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, balance_minor INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY, end_to_end_id TEXT NOT NULL, from_acct TEXT NOT NULL,
    beneficiary_bank TEXT NOT NULL, beneficiary_acct TEXT NOT NULL,
    amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
    release TEXT, created_t REAL NOT NULL, updated_t REAL NOT NULL);
CREATE INDEX IF NOT EXISTS payments_e2e ON payments(end_to_end_id);
CREATE TABLE IF NOT EXISTS postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT NOT NULL, account TEXT NOT NULL,
    amount_minor INTEGER NOT NULL, t REAL NOT NULL);
CREATE INDEX IF NOT EXISTS postings_payment ON postings(payment_id);
CREATE INDEX IF NOT EXISTS postings_account ON postings(account, t);
CREATE TABLE IF NOT EXISTS clearing_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT NOT NULL, payload_json TEXT NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_t REAL NOT NULL, updated_t REAL NOT NULL);
CREATE INDEX IF NOT EXISTS queue_status ON clearing_queue(status, id);
"""


def path(data_dir):
    return os.path.join(data_dir, "ledger.db")


def connect(data_dir, busy_timeout_ms=1000, readonly=False):
    """Open the ledger. Writers wait up to busy_timeout_ms for a lock, then fail with 'database is locked'."""
    if readonly:
        uri = "file:" + path(data_dir).replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=busy_timeout_ms / 1000, isolation_level=None,
                               check_same_thread=False)
    else:
        conn = sqlite3.connect(path(data_dir), timeout=busy_timeout_ms / 1000, isolation_level=None,
                               check_same_thread=False)
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.row_factory = sqlite3.Row
    return conn


def create(data_dir, customers):
    """Make a fresh ledger with the test customers, the probe account and the settlement account."""
    conn = sqlite3.connect(path(data_dir), isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    rows = [(c, "customer", CUSTOMER_START_MINOR) for c in customers]
    rows += [(PROBE, "probe", PROBE_START_MINOR), (SETTLEMENT, "settlement", 0)]
    conn.executemany("INSERT INTO accounts VALUES (?, ?, ?)", rows)
    conn.close()
    total = CUSTOMER_START_MINOR * len(customers) + PROBE_START_MINOR
    with open(os.path.join(data_dir, "ledger_meta.json"), "w", encoding="utf-8") as handle:
        json.dump({"total_minor": total, "created_t": time.time()}, handle)
    return total


def post_payment(conn, payment_id, e2e, from_acct, bank, beneficiary, amount, currency, release):
    """Post one payment: two postings, two balance updates and a clearing item, all or nothing.

    The caller holds a write transaction (BEGIN IMMEDIATE).
    """
    now = time.time()
    conn.execute("INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?, ?, 'posted', ?, ?, ?)",
                 (payment_id, e2e, from_acct, bank, beneficiary, amount, currency, release, now, now))
    conn.execute("INSERT INTO postings (payment_id, account, amount_minor, t) VALUES (?, ?, ?, ?)",
                 (payment_id, from_acct, -amount, now))
    conn.execute("INSERT INTO postings (payment_id, account, amount_minor, t) VALUES (?, ?, ?, ?)",
                 (payment_id, SETTLEMENT, amount, now))
    conn.execute("UPDATE accounts SET balance_minor = balance_minor - ? WHERE id = ?", (amount, from_acct))
    conn.execute("UPDATE accounts SET balance_minor = balance_minor + ? WHERE id = ?", (amount, SETTLEMENT))
    payload = {"payment_id": payment_id, "end_to_end_id": e2e, "amount_minor": amount, "currency": currency,
               "beneficiary_bank": bank, "beneficiary_acct": beneficiary}
    conn.execute("INSERT INTO clearing_queue (payment_id, payload_json, status, attempts, created_t, updated_t) "
                 "VALUES (?, ?, 'pending', 0, ?, ?)", (payment_id, json.dumps(payload), now, now))


def integrity(conn, since_s=600.0):
    """Figures a bank's reconciliation monitor would watch, over recent payments."""
    cutoff = time.time() - since_s
    unbalanced = conn.execute(
        "SELECT COUNT(*) FROM (SELECT p.id FROM payments p LEFT JOIN postings x ON x.payment_id = p.id "
        "WHERE p.created_t >= ? AND p.status != 'rejected' GROUP BY p.id "
        "HAVING COUNT(x.id) != 2 OR COALESCE(SUM(x.amount_minor), 0) != 0)", (cutoff,)).fetchone()[0]
    duplicates = conn.execute(
        "SELECT COUNT(*) FROM (SELECT end_to_end_id FROM payments WHERE created_t >= ? AND status != 'rejected' "
        "GROUP BY end_to_end_id HAVING COUNT(*) > 1)", (cutoff,)).fetchone()[0]
    return {"unbalanced_payments": unbalanced, "duplicate_payments": duplicates}


def queue_state(conn):
    """The clearing queue as the operations team sees it: depth, oldest item, the item at the head, items set aside."""
    pending = conn.execute("SELECT COUNT(*), MIN(created_t) FROM clearing_queue WHERE status = 'pending'").fetchone()
    head = conn.execute("SELECT id, created_t, attempts FROM clearing_queue WHERE status = 'pending' "
                        "ORDER BY id LIMIT 1").fetchone()
    quarantined = conn.execute("SELECT COUNT(*) FROM clearing_queue WHERE status = 'quarantined'").fetchone()[0]
    now = time.time()
    return {"queue_depth": pending[0],
            "oldest_pending_s": round(now - pending[1], 1) if pending[1] else 0.0,
            "head_item": ({"id": head[0], "age_s": round(now - head[1], 1), "attempts": head[2]} if head else None),
            "quarantined_items": quarantined}


def locks_path(data_dir):
    return os.path.join(data_dir, "ledger_locks.json")
