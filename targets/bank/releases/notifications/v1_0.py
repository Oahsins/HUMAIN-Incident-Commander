"""Notifications worker release 1.0: sends each customer a receipt for every posted payment.

Only the extra_service condition runs it. A trigger in the ledger queues one
receipt per posted payment in the same transaction as the postings (table
receipt_queue). The worker takes up to batch_size of the oldest pending
receipts, hands them to the customers' inbox (receipts.jsonl in the copy's
data folder) and marks them sent; no receipt can stop it. It re-reads its
settings while it waits between polls, so a corrected value applies at once.
A value it cannot use (batch_size below 1 or above 10,000, poll_interval_s not
above 0, or not a number) leaves the queue alone and is logged as an error
until someone changes it.
"""

import json
import os
import sqlite3
import time

from ic.kit.service import ServiceBase
from ic.kit.stats import Window
from targets.bank import ledger

MAX_BATCH = 10_000


class Release(ServiceBase):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.sent = Window()
        self.conn = None
        self.inbox = os.path.join(self.data_dir, "receipts.jsonl")

    def settings(self):
        """(batch_size, poll_interval_s), or None when either value is unusable."""
        try:
            batch = int(self.setting("batch_size", 50))
            interval = float(self.setting("poll_interval_s", 0.2))
        except (TypeError, ValueError, OverflowError):
            return None
        if not 1 <= batch <= MAX_BATCH or not interval > 0:
            return None
        return batch, interval

    def wait(self, seconds):
        """Sleep between polls, waking early when a setting changes."""
        _, version = self.config.values()
        end = time.time() + seconds
        while time.time() < end:
            time.sleep(min(0.25, max(0.0, end - time.time())))
            if self.config.values()[1] != version:
                return

    def background(self):
        self.conn = ledger.connect(self.data_dir, busy_timeout_ms=2000)
        while True:
            settings = self.settings()
            if settings is None:
                self.log_every("settings", 5.0, "ERROR", "settings_unusable",
                               "cannot use the batch_size or poll_interval_s setting; receipts are not being sent",
                               batch_size=self.setting("batch_size"), poll_interval_s=self.setting("poll_interval_s"))
                self.wait(1.0)
                continue
            batch, interval = settings
            try:
                items = self.conn.execute(
                    "SELECT q.id, q.payment_id, p.end_to_end_id, p.from_acct, p.amount_minor, p.currency "
                    "FROM receipt_queue q LEFT JOIN payments p ON p.id = q.payment_id WHERE q.status = 'pending' "
                    "ORDER BY q.id LIMIT ?", (batch,)).fetchall()
            except sqlite3.OperationalError as exc:
                self.log_every("queue_read", 2.0, "WARN", "queue_read_failed", f"could not read queue: {exc}")
                self.wait(interval)
                continue
            if items:
                self.send(items)
            self.wait(interval)

    def send(self, items):
        now = time.time()
        with open(self.inbox, "a", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps({"t": now, "receipt": item["id"], "payment_id": item["payment_id"],
                                         "to": item["from_acct"], "end_to_end_id": item["end_to_end_id"],
                                         "amount_minor": item["amount_minor"], "currency": item["currency"]},
                                        default=str) + "\n")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.executemany("UPDATE receipt_queue SET status = 'sent', updated_t = ? "
                                  "WHERE id = ? AND status = 'pending'", [(now, item["id"]) for item in items])
            self.conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            self.log_every("ledger_busy", 2.0, "WARN", "ledger_write_failed", f"could not mark receipts sent: {exc}")
            return
        for _ in items:
            self.sent.add(0.0, "ok")

    def extra_metrics(self, window_s):
        # Queue depth and the oldest receipt come from the ledger through observe(), as for clearing.
        return {"processed_per_s": self.sent.summary(window_s)["rps"]}
