"""Clearing worker release 3.2: sends posted payments to the national payment network.

It takes the oldest pending items from the clearing queue, sends each one to
the network, and marks it cleared. Items it cannot send stay pending and are
retried. An item it cannot even read is a programming error: the worker
crashes, exactly as a real worker without a dead-letter guard would, and it
will crash again on the same item after a restart until someone sets the item
aside (quarantine).
"""

import json
import sqlite3
import time

from ic.kit import net
from ic.kit.service import ServiceBase
from ic.kit.stats import Window
from targets.bank import ledger

NETWORK_FEES_MINOR = {"SAR": 0}   # per-currency network fee; this network only clears riyals


class Release(ServiceBase):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.cleared = Window()
        self.conn = None

    def background(self):
        self.conn = ledger.connect(self.data_dir, busy_timeout_ms=2000)
        while True:
            interval = float(self.setting("poll_interval_s", 0.2))
            batch = int(self.setting("batch_size", 50))
            try:
                items = self.conn.execute(
                    "SELECT id, payment_id, payload_json, attempts FROM clearing_queue WHERE status = 'pending' "
                    "ORDER BY id LIMIT ?", (batch,)).fetchall()
            except sqlite3.OperationalError as exc:
                self.log_every("queue_read", 2.0, "WARN", "queue_read_failed", f"could not read queue: {exc}")
                time.sleep(interval)
                continue
            for item in items:
                if not self.clear_one(item):
                    break   # the network is struggling: back off before trying the rest
            time.sleep(interval)

    def parse(self, item):
        payload = json.loads(item["payload_json"])
        fee = NETWORK_FEES_MINOR[payload["currency"]]
        return {"payment_id": payload["payment_id"], "end_to_end_id": payload["end_to_end_id"],
                "amount_minor": int(payload["amount_minor"]) + fee,
                "beneficiary_bank": payload["beneficiary_bank"], "beneficiary_acct": payload["beneficiary_acct"]}

    def clear_one(self, item):
        try:
            message = self.parse(item)
        except Exception as exc:
            self.crash(exc, item_id=item["id"], payment_id=item["payment_id"])
        timeout = float(self.setting("network_timeout_s", 2.0))
        try:
            self.call("network", "POST", self.url("clearing->network", "/clear"), message, timeout)
        except net.CallError as exc:
            self.conn.execute("UPDATE clearing_queue SET attempts = attempts + 1, updated_t = ? WHERE id = ?",
                              (time.time(), item["id"]))
            self.log_every(f"network:{exc.kind}", 2.0, "WARN", "network_send_failed",
                           f"payment network {exc.kind}; item stays pending", item_id=item["id"])
            return False
        now = time.time()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("UPDATE clearing_queue SET status = 'cleared', updated_t = ? WHERE id = ?",
                              (now, item["id"]))
            self.conn.execute("UPDATE payments SET status = 'cleared', updated_t = ? WHERE id = ?",
                              (now, item["payment_id"]))
            self.conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            self.log_every("ledger_busy", 2.0, "WARN", "ledger_write_failed", f"could not mark cleared: {exc}")
            return False
        self.cleared.add(0.0, "ok")
        return True

    def extra_metrics(self, window_s):
        # Queue depth and the oldest item come from the ledger through observe(), so they show even when
        # this worker is down. The worker itself reports only how fast it clears.
        return {"processed_per_s": self.cleared.summary(window_s)["rps"]}
