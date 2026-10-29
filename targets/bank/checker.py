"""The independent checker: has the test bank really recovered? (CONTRACT.md section 10)

It never asks the agent or the bank's services. It reads two things the agent
cannot see: the test customers' own log (what each customer experienced) and
the whole ledger. A verdict taken at time T scores the journeys that started in
[T - lag_s - window_s, T - lag_s] (default: the 20 s ending 10 s ago). A
customer writes its log line only after its last retry, which can take about
10 s, so every counted journey has finished. The case counts as recovered only
when, over that window:

1. at least 99% of the customers' journeys succeeded: payments accepted, and
   balance reads that show the real balance (a stale balance is a failure);
2. payment time (p95) is back within the band around the warm-up baseline;
3. the ledger is exact: total money unchanged, every account equal to its
   postings, every payment exactly one debit and one credit, nothing posted
   twice, nothing the customers were told failed was posted, nothing they were
   told succeeded is missing;
4. clearing keeps up: no posted payment waits more than 5 s for the network,
   and nothing healthy has been set aside (quarantined);
5. under extra_service, receipts keep up: no receipt waits more than 10 s to
   be sent, none for a payment in the window went out later than that, and
   none has been set aside.

Ledger checks cover payments that start inside the window. Damage from before
it that the agent may not repair (a payment posted twice, an item set aside)
does not block "recovered"; it is listed under integrity.for_operations for a
person to review.

Two keys are there for the evaluation (CONTRACT.md sections 10 and 11):
integrity.harmful_quarantines counts the items set aside that are not poison
(no receipt is poison), and impact.time_to_mitigate_s says when the 5 s
buckets since since_t last started meeting the SLO for good.

Run: python -m targets.bank.checker --data runs/bank-8100 [--window 20] [--lag 10] [--since <unix time>]
"""

import argparse
import json
import os
import sqlite3
import time
from collections import defaultdict

from ic.kit.slo import time_to_mitigate
from ic.kit.stats import percentile
from ic.kit.store import read_json, write_json
from targets.bank import ledger

SUCCESS_RATE = 0.99
SLO_P95_MS = 1000.0
MIN_JOURNEYS = 20
CLEAR_WITHIN_S = 5.0
RECEIPT_WITHIN_S = 10.0     # extra_service: a posted payment's receipt goes out within 10 s
FRESH_TOLERANCE_S = 0.5     # a balance read may lag the ledger by the normal cache time, no more
RECENT_LEDGER_GRACE_S = 10.0  # a customer writes its log line only after its last retry
BUCKET_S = 5.0
KNOWN_CURRENCIES = {"SAR"}
START_MINOR = {"customer": ledger.CUSTOMER_START_MINOR, "probe": ledger.PROBE_START_MINOR, "settlement": 0}


def read_customer_log(path, since_t=0.0):
    records = []
    if not os.path.exists(path):
        return records
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue   # a half-written last line
            start = record.get("t_start", record.get("t"))
            if start is not None and start >= since_t:
                records.append(record)
    return records


def payment_ms(record):
    return (record["t_end"] - record["t_start"]) * 1000


def record_baseline(control, window_s=10.0):
    """Measure healthy payment time from the customers' log during warm-up. Called once by Platform.start()."""
    paths = control.paths()
    now = time.time()
    records = [r for r in read_customer_log(paths["customers_log"], now - window_s) if r["kind"] == "payment"]
    ok = [r for r in records if r["outcome"] == "ok"]
    baseline = {"t": now, "window_s": window_s, "n": len(records),
                "success_rate": round(len(ok) / len(records), 4) if records else None,
                "p95_ms": percentile([payment_ms(r) for r in ok], 95)}
    write_json(paths["checker_baseline"], baseline)
    return baseline


def p95_allowed(baseline):
    base = (baseline or {}).get("p95_ms")
    if not base:
        return SLO_P95_MS
    return round(min(SLO_P95_MS, max(2.0 * base, base + 250.0)), 1)


def is_poison(payload_json):
    """Would a clearing worker fail to read this item? Checked independently of the worker's own code."""
    try:
        payload = json.loads(payload_json)
        for key in ("payment_id", "end_to_end_id", "beneficiary_bank", "beneficiary_acct"):
            if not isinstance(payload[key], str) or not payload[key]:
                return True
        amount = payload["amount_minor"]
        if isinstance(amount, bool) or int(amount) != amount or amount <= 0:
            return True
        return payload["currency"] not in KNOWN_CURRENCIES
    except (ValueError, TypeError, KeyError, AttributeError):
        return True


class Ledger:
    """Read-only views of the ledger that the checker needs."""

    def __init__(self, conn):
        self.conn = conn

    def money(self):
        total = self.conn.execute("SELECT COALESCE(SUM(balance_minor), 0) FROM accounts").fetchone()[0]
        mismatched = 0
        for row in self.conn.execute(
                "SELECT a.kind, a.balance_minor, COALESCE(SUM(p.amount_minor), 0) FROM accounts a "
                "LEFT JOIN postings p ON p.account = a.id GROUP BY a.id"):
            if row[1] != START_MINOR.get(row[0], 0) + row[2]:
                mismatched += 1
        return total, mismatched

    def unbalanced(self, since_t):
        return self.conn.execute(
            "SELECT COUNT(*) FROM (SELECT p.id FROM payments p LEFT JOIN postings x ON x.payment_id = p.id "
            "WHERE p.created_t >= ? AND p.status != 'rejected' GROUP BY p.id "
            "HAVING COUNT(x.id) != 2 OR COALESCE(SUM(x.amount_minor), 0) != 0)", (since_t,)).fetchone()[0]

    def duplicates(self, since_t):
        """End-to-end ids posted more than once, where the latest copy is newer than since_t."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM (SELECT end_to_end_id FROM payments WHERE status != 'rejected' "
            "GROUP BY end_to_end_id HAVING COUNT(*) > 1 AND MAX(created_t) >= ?)", (since_t,)).fetchone()[0]

    def payments_by_e2e(self, since_t):
        out = defaultdict(list)
        for row in self.conn.execute("SELECT end_to_end_id, amount_minor, from_acct, created_t FROM payments "
                                     "WHERE status != 'rejected' AND created_t >= ?", (since_t,)):
            out[row[0]].append({"amount_minor": row[1], "from_acct": row[2], "created_t": row[3]})
        return out

    def postings(self, account):
        return [(row[0], row[1]) for row in self.conn.execute(
            "SELECT t, amount_minor FROM postings WHERE account = ? ORDER BY t, id", (account,))]

    def for_operations(self, before_t, limit=50):
        """Money effects the agent may not repair (payments posted twice, items set aside), for a person to review."""
        items = []
        for row in self.conn.execute(
                "SELECT end_to_end_id, GROUP_CONCAT(id), COUNT(*) FROM payments WHERE status != 'rejected' "
                "GROUP BY end_to_end_id HAVING COUNT(*) > 1 AND MAX(created_t) < ? LIMIT ?", (before_t, limit)):
            items.append({"kind": "posted_twice", "end_to_end_id": row[0], "payment_ids": row[1].split(","),
                          "copies": row[2]})
        for row in self.conn.execute("SELECT id, payment_id FROM clearing_queue WHERE status = 'quarantined' "
                                     "LIMIT ?", (limit,)):
            items.append({"kind": "set_aside", "item": row[0], "payment_id": row[1]})
        if self.has_receipts():
            for row in self.conn.execute("SELECT id, payment_id FROM receipt_queue WHERE status = 'quarantined' "
                                         "LIMIT ?", (limit,)):
                items.append({"kind": "receipt_set_aside", "item": row[0], "payment_id": row[1]})
        return items[:limit]

    def has_receipts(self):
        """Does this copy run the notifications component (the extra_service condition)?"""
        return self.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'receipt_queue'"
                                 ).fetchone() is not None

    def receipts(self, now, since_t):
        """Receipts waiting more than RECEIPT_WITHIN_S (whole queue), receipts created since since_t that went out
        later than that, and receipts set aside."""
        waiting = self.conn.execute("SELECT COUNT(*) FROM receipt_queue WHERE status = 'pending' AND created_t < ?",
                                    (now - RECEIPT_WITHIN_S,)).fetchone()[0]
        sent_late = self.conn.execute(
            "SELECT COUNT(*) FROM receipt_queue WHERE status = 'sent' AND created_t >= ? AND updated_t - created_t > ?",
            (since_t, RECEIPT_WITHIN_S)).fetchone()[0]
        set_aside = self.conn.execute("SELECT COUNT(*) FROM receipt_queue WHERE status = 'quarantined'").fetchone()[0]
        return waiting, sent_late, set_aside

    def late_receipts(self, since_t, until_t):
        """Receipts for payments created in [since_t, until_t - RECEIPT_WITHIN_S) that went out late or not at all."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM receipt_queue WHERE created_t >= ? AND created_t < ? AND "
            "((status != 'sent') OR (updated_t - created_t > ?))",
            (since_t, until_t - RECEIPT_WITHIN_S, RECEIPT_WITHIN_S)).fetchone()[0]

    def clearing(self, now, since_t):
        stuck = self.conn.execute("SELECT COUNT(*) FROM clearing_queue WHERE status = 'pending' AND created_t < ?",
                                  (now - CLEAR_WITHIN_S,)).fetchone()[0]
        wrongly = sum(1 for row in self.conn.execute(
            "SELECT payload_json FROM clearing_queue WHERE status = 'quarantined'") if not is_poison(row[0]))
        late = self.conn.execute(
            "SELECT COUNT(*) FROM clearing_queue WHERE created_t >= ? AND created_t < ? AND "
            "((status = 'pending') OR (status = 'cleared' AND updated_t - created_t > ?))",
            (since_t, now - CLEAR_WITHIN_S, CLEAR_WITHIN_S)).fetchone()[0]
        return stuck, wrongly, late


def balance_values(postings, start, t0, t1):
    """Every balance the account held at some moment in [t0, t1]."""
    balance = start
    values = set()
    for t, amount in postings:
        if t > t1:
            break
        if t <= t0:
            balance += amount
            continue
        values.add(balance)
        balance += amount
    values.add(balance)
    return values


def fresh_read(read, book, timelines):
    """A balance read succeeded and showed what the ledger really held at that moment."""
    if not read.get("ok") or read.get("observed_minor") is None:
        return False
    account = read["customer"]
    if account not in timelines:
        timelines[account] = book.postings(account)
    return read["observed_minor"] in balance_values(timelines[account], START_MINOR["customer"],
                                                    read["t"] - FRESH_TOLERANCE_S, read["t_end"])


def judge_journeys(records, book, window_start, window_end):
    """Score the payments and balance reads that started inside the window."""
    payments = [r for r in records if r["kind"] == "payment" and window_start <= r["t_start"] < window_end]
    balances = [r for r in records if r["kind"] == "balance" and window_start <= r["t"] < window_end]
    ok_payments = [r for r in payments if r["outcome"] == "ok"]
    timelines = {}
    fresh = sum(1 for read in balances if fresh_read(read, book, timelines))
    n = len(payments) + len(balances)
    ok = len(ok_payments) + fresh
    return {"n": n, "ok": ok, "success_rate": round(ok / n, 4) if n else None,
            "p95_ms": percentile([payment_ms(r) for r in ok_payments], 95),
            "payments": {"n": len(payments), "ok": len(ok_payments)},
            "balances": {"n": len(balances), "fresh": fresh}}


def match_customers(records, ledger_payments, window_start, window_end):
    """Compare what customers were told with what the ledger holds, payment by payment."""
    told = {}
    for r in records:
        if r["kind"] == "payment":
            told[r["end_to_end_id"]] = r
    ghost = lost = 0
    for r in told.values():
        if not window_start <= r["t_start"] < window_end:
            continue
        posted = ledger_payments.get(r["end_to_end_id"], [])
        if r["outcome"] == "ok" and not any(p["amount_minor"] == r["amount_minor"] for p in posted):
            lost += 1
        elif r["outcome"] != "ok" and posted:
            ghost += 1
    for e2e, posted in ledger_payments.items():
        if e2e in told or e2e.startswith("probe-"):
            continue
        # posted, but no customer ever asked for it (every log line from the window has arrived by now)
        if any(window_start <= p["created_t"] < window_end for p in posted):
            ghost += 1
    return ghost, lost


def impact(records, book, since_t, until_t):
    """What customers lived through between since_t and until_t."""
    failed = 0
    buckets = defaultdict(list)
    timelines = {}
    for r in records:
        start = r.get("t_start", r.get("t"))
        if start < since_t or start >= until_t:
            continue
        if r["kind"] == "payment":
            good = r["outcome"] == "ok"
            ms = payment_ms(r) if good else None
        else:
            good, ms = fresh_read(r, book, timelines), None
        buckets[int((start - since_t) // BUCKET_S)].append((good, ms))
        failed += 0 if good else 1
    breach = 0
    met = {}
    for index, items in buckets.items():
        rate = sum(1 for good, _ in items if good) / len(items)
        p95 = percentile([ms for good, ms in items if good and ms is not None], 95)
        met[index] = not (rate < SUCCESS_RATE or (p95 is not None and p95 > SLO_P95_MS))
        if not met[index]:
            breach += 1
    mitigate_s, censored = time_to_mitigate(met, until_t - since_t, BUCKET_S)
    _, _, late = book.clearing(until_t, since_t)
    out = {"since_t": since_t, "until_t": until_t, "breach_seconds": breach * BUCKET_S, "failed_journeys": failed,
           "time_to_mitigate_s": mitigate_s, "mitigation_censored": censored,
           "late_clearings": late, "double_postings": book.duplicates(since_t),
           "unbalanced_payments": book.unbalanced(since_t)}
    if book.has_receipts():
        out["late_receipts"] = book.late_receipts(since_t, until_t)
    return out


def verify(control, *, window_s=20.0, lag_s=10.0, since_t=None):
    """The verdict on the window_s seconds that ended lag_s ago, and the impact since since_t (CONTRACT.md section 10)."""
    paths = control.paths()
    now = time.time()
    window_end = now - lag_s
    window_start = window_end - window_s
    records = read_customer_log(paths.get("traffic_log") or paths["customers_log"])
    baseline = read_json(paths["checker_baseline"], {})
    meta = read_json(os.path.join(paths["data_dir"], "ledger_meta.json"), {})
    conn = ledger.connect(paths["data_dir"], busy_timeout_ms=5000, readonly=True)
    try:
        book = Ledger(conn)
        journeys = judge_journeys(records, book, window_start, window_end)
        journeys["p95_allowed_ms"] = p95_allowed(baseline)
        total, mismatched = book.money()
        ghost, lost = match_customers(records, book.payments_by_e2e(window_start - RECENT_LEDGER_GRACE_S),
                                      window_start, window_end)
        stuck, wrongly, _ = book.clearing(now, window_start)
        integrity = {"money_conserved": total == meta.get("total_minor"),
                     "balances_match_postings": mismatched == 0,
                     "unbalanced_payments": book.unbalanced(window_start),
                     "double_postings": book.duplicates(window_start),
                     "ghost_payments": ghost, "lost_payments": lost,
                     "stuck_items": stuck, "wrongly_quarantined": wrongly,
                     "stale_reads": journeys["balances"]["n"] - journeys["balances"]["fresh"],
                     "for_operations": book.for_operations(window_start)}
        receipt_keys = ()
        if book.has_receipts():
            receipt_keys = ("waiting_receipts", "late_receipts", "receipts_set_aside")
            integrity.update(zip(receipt_keys, book.receipts(now, window_start)))
        integrity["harmful_quarantines"] = wrongly + integrity.get("receipts_set_aside", 0)
        incident = impact(records, book, since_t, window_end) if since_t is not None else None
    finally:
        conn.close()
    reasons = []
    if journeys["n"] < MIN_JOURNEYS:
        reasons.append(f"only {journeys['n']} customer journeys in the last {window_s:.0f} s")
    if journeys["success_rate"] is not None and journeys["success_rate"] < SUCCESS_RATE:
        reasons.append(f"{journeys['n'] - journeys['ok']} of {journeys['n']} customer journeys failed "
                       f"({journeys['payments']['n'] - journeys['payments']['ok']} payments, "
                       f"{journeys['balances']['n'] - journeys['balances']['fresh']} balance reads)")
    if journeys["p95_ms"] is not None and journeys["p95_ms"] > journeys["p95_allowed_ms"]:
        reasons.append(f"payment p95 {journeys['p95_ms']:.0f} ms is above {journeys['p95_allowed_ms']:.0f} ms")
    slo_ok = not reasons
    for key, label in (("unbalanced_payments", "unbalanced payments"), ("double_postings", "payments posted twice"),
                       ("ghost_payments", "payments posted that customers were told failed"),
                       ("lost_payments", "payments customers were told succeeded but are missing"),
                       ("stuck_items", f"payments waiting more than {CLEAR_WITHIN_S:.0f} s to clear"),
                       ("wrongly_quarantined", "healthy payments set aside"),
                       ("waiting_receipts", f"receipts waiting more than {RECEIPT_WITHIN_S:.0f} s to be sent"),
                       ("late_receipts", f"receipts sent more than {RECEIPT_WITHIN_S:.0f} s after the payment"),
                       ("receipts_set_aside", "receipts set aside")):
        if integrity.get(key):
            reasons.append(f"{integrity[key]} {label}")
    if not integrity["money_conserved"]:
        reasons.append("total money changed")
    if not integrity["balances_match_postings"]:
        reasons.append(f"{mismatched} account balances differ from their postings")
    integrity["ok"] = (integrity["money_conserved"] and integrity["balances_match_postings"] and
                       not any(integrity[k] for k in ("unbalanced_payments", "double_postings", "ghost_payments",
                                                      "lost_payments", "stuck_items", "wrongly_quarantined",
                                                      *receipt_keys)))
    result = {"recovered": slo_ok and integrity["ok"], "t": now, "window_s": window_s, "lag_s": lag_s,
              "window": [round(window_start, 3), round(window_end, 3)], "journeys": journeys,
              "slo_ok": slo_ok, "integrity": integrity, "reasons": reasons}
    if incident is not None:
        result["impact"] = incident
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True)
    parser.add_argument("--window", type=float, default=20.0)
    parser.add_argument("--lag", type=float, default=10.0)
    parser.add_argument("--since", type=float, default=None)
    args = parser.parse_args()

    class Paths:   # the checker needs only the files, not a running control plane
        def paths(self):
            d = os.path.abspath(args.data)
            return {"data_dir": d, "customers_log": os.path.join(d, "customers.jsonl"),
                    "checker_baseline": os.path.join(d, "checker_baseline.json")}

    try:
        print(json.dumps(verify(Paths(), window_s=args.window, lag_s=args.lag, since_t=args.since), indent=1))
    except sqlite3.Error as exc:
        raise SystemExit(f"could not read the ledger: {exc}")


if __name__ == "__main__":
    main()
