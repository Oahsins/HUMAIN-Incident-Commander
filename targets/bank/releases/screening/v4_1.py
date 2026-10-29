"""Fraud screening release 4.1: scores each payment before it is posted.

The primary and the standby run the same release on different ports. Payments
calls the primary through a network link that faults can slow down; the
standby is reached directly.
"""

import random
import time

from ic.kit.service import ServiceBase


class Release(ServiceBase):
    def routes(self):
        return {("POST", "/score"): self.score}

    def score(self, request):
        body = request["body"]
        time.sleep(random.uniform(0.004, 0.015))   # the work of scoring
        amount = int(body.get("amount_minor", 0))
        risk = min(0.99, amount / 100_000_000)     # bigger payments carry more risk
        return {"score": round(risk, 4), "decision": "pass" if risk < 0.9 else "review",
                "screened_by": self.component}
