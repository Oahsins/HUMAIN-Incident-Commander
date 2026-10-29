"""Payments release 1.3: validates a payment, screens it, and posts it to the ledger.

The order matters and mirrors a real payments hub:
1. validate the request and the transfer limit (setting max_transfer_minor);
2. return the earlier answer if this end-to-end id was already posted (idempotency);
3. ask fraud screening (primary, or the standby after a failover);
4. post two ledger entries and a clearing item in one transaction.
"""

import sqlite3
import threading
import uuid

from ic.kit import net
from ic.kit.service import ServiceBase
from ic.kit.stats import Window
from targets.bank import ledger


class Release(ServiceBase):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.local = threading.local()
        self.ledger_errors = Window()

    def db(self):
        if not hasattr(self.local, "conn"):
            self.local.conn = ledger.connect(self.data_dir, busy_timeout_ms=1000)
        return self.local.conn

    def routes(self):
        return {("POST", "/pay"): self.pay,
                ("GET", "/balance/*"): self.balance,
                ("GET", "/payment/*"): self.payment}

    # ----- steps a later release may change -----

    def validate(self, body):
        for field in ("from_acct", "amount_minor", "currency", "beneficiary_bank", "beneficiary_acct", "end_to_end_id"):
            if field not in body:
                raise net.Reply(400, {"error": f"missing {field}"})
        amount = int(body["amount_minor"])
        if amount <= 0:
            raise net.Reply(400, {"error": "amount must be positive"})
        limit = int(self.setting("max_transfer_minor", 1_000_000))
        if amount > limit:
            self.log_every("limit", 2.0, "WARN", "limit_reject", "payment rejected: amount exceeds transfer limit",
                           limit_minor=limit, amount_minor=amount)
            raise net.Reply(422, {"error": "amount exceeds transfer limit"})
        return amount

    def find_existing(self, conn, e2e):
        row = conn.execute("SELECT id, status FROM payments WHERE end_to_end_id = ? AND status != 'rejected' "
                           "ORDER BY created_t LIMIT 1", (e2e,)).fetchone()
        return dict(row) if row else None

    def screen(self, body, amount):
        target = self.routing.active("screening")
        timeout = float(self.setting("screening_timeout_s", 1.0))
        if target == "standby":
            name, url = "screening-standby", self.url("screening-standby", "/score")
        else:
            name, url = "screening", self.url("payments->screening", "/score")
        try:
            return self.call(name, "POST", url, {"amount_minor": amount, "from_acct": body["from_acct"]}, timeout)[1]
        except net.CallError as exc:
            self.log_every(f"screening:{exc.kind}", 2.0, "ERROR", "screening_failed",
                           f"fraud screening {exc.kind} via {target}", target=target, timeout_s=timeout)
            raise net.Reply(503, {"error": f"screening unavailable ({exc.kind})"})

    # ----- endpoints -----

    def pay(self, request):
        body = request["body"]
        amount = self.validate(body)
        conn = self.db()
        existing = self.find_existing(conn, body["end_to_end_id"])
        if existing:
            return {"payment_id": existing["id"], "status": existing["status"], "replayed": True}
        verdict = self.screen(body, amount)
        if verdict.get("decision") != "pass":
            raise net.Reply(422, {"error": "held for fraud review"})
        payment_id = uuid.uuid4().hex[:16]
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = self.find_existing(conn, body["end_to_end_id"])
            if existing:
                conn.execute("ROLLBACK")
                return {"payment_id": existing["id"], "status": existing["status"], "replayed": True}
            balance = conn.execute("SELECT balance_minor FROM accounts WHERE id = ?", (body["from_acct"],)).fetchone()
            if balance is None:
                conn.execute("ROLLBACK")
                raise net.Reply(404, {"error": "unknown account"})
            if balance[0] < amount:
                conn.execute("ROLLBACK")
                raise net.Reply(422, {"error": "insufficient funds"})
            ledger.post_payment(conn, payment_id, body["end_to_end_id"], body["from_acct"], body["beneficiary_bank"],
                                body["beneficiary_acct"], amount, body["currency"], self.version)
            conn.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            self.ledger_errors.add(0.0, "error")
            self.log_every("ledger_busy", 2.0, "ERROR", "ledger_write_failed", f"ledger write failed: {exc}")
            raise net.Reply(503, {"error": "ledger busy"})
        return {"payment_id": payment_id, "status": "posted", "replayed": False}

    def balance(self, request):
        row = self.db().execute("SELECT balance_minor FROM accounts WHERE id = ?", (request["tail"],)).fetchone()
        if row is None:
            raise net.Reply(404, {"error": "unknown account"})
        return {"account": request["tail"], "balance_minor": row[0]}

    def payment(self, request):
        conn = self.db()
        row = conn.execute("SELECT id, end_to_end_id, status, amount_minor FROM payments WHERE id = ?",
                           (request["tail"],)).fetchone()
        if row is None:
            raise net.Reply(404, {"error": "unknown payment"})
        postings = conn.execute("SELECT COUNT(*), COALESCE(SUM(amount_minor), 0) FROM postings WHERE payment_id = ?",
                                (row["id"],)).fetchone()
        return {**dict(row), "postings": postings[0], "postings_sum_minor": postings[1]}

    def extra_metrics(self, window_s):
        return {"ledger_write_errors": self.ledger_errors.summary(window_s)["n"]}
