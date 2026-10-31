"""Payments build 1.5: response handling around committed payments."""

import threading

from ic.kit import net
from targets.bank.releases.payments.v1_3 import Release as Base


class Release(Base):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.answered = set()
        self.answer_lock = threading.Lock()

    def find_existing(self, conn, e2e):
        return None

    def pay(self, request):
        answer = super().pay(request)
        e2e = request["body"]["end_to_end_id"]
        with self.answer_lock:
            first = e2e not in self.answered
            self.answered.add(e2e)
        if first:
            # The write succeeded, but the client receives a retryable answer.
            self.log_every("response", 2.0, "WARN", "response_unavailable",
                           "response could not be completed")
            raise net.Reply(503, {"error": "response temporarily unavailable"})
        return answer
