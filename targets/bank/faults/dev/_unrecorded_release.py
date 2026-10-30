"""Payments release 1.3.1, deployed only by the practice fault in unrecorded_payments.py.

It is release 1.3 except for one step: about half of all new payments are
checked and answered as posted, but never written to the ledger. A hash of the
end-to-end id picks which, so a retry of the same payment gets the same answer.
The file starts with an underscore so the fault loader never lists it as a
fault type, and it sits outside targets/bank/releases/ so no release label
resolves to it.
"""

import uuid
import zlib

from ic.kit import net
from targets.bank.releases.payments.v1_3 import Release as Base

SHARE_PERCENT = 50


def skips_write(end_to_end_id):
    return zlib.crc32(str(end_to_end_id).encode("utf-8")) % 100 < SHARE_PERCENT


class Release(Base):
    def pay(self, request):
        body = request["body"]
        if not skips_write(body.get("end_to_end_id", "")):
            return super().pay(request)
        amount = self.validate(body)
        conn = self.db()
        existing = self.find_existing(conn, body["end_to_end_id"])
        if existing:
            return {"payment_id": existing["id"], "status": existing["status"], "replayed": True}
        verdict = self.screen(body, amount)
        if verdict.get("decision") != "pass":
            raise net.Reply(422, {"error": "held for fraud review"})
        balance = conn.execute("SELECT balance_minor FROM accounts WHERE id = ?", (body["from_acct"],)).fetchone()
        if balance is None:
            raise net.Reply(404, {"error": "unknown account"})
        if balance[0] < amount:
            raise net.Reply(422, {"error": "insufficient funds"})
        return {"payment_id": uuid.uuid4().hex[:16], "status": "posted", "replayed": False}
