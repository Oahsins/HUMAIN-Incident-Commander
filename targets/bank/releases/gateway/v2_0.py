"""Gateway release 2.0: the front door for the test customers' apps.

It forwards payments to the payments service and caches balance reads for a
short time (setting balance_cache_ttl_s), as many banking gateways do to keep
load off the core.
"""

import threading
import time

from ic.kit import net
from ic.kit.service import ServiceBase


class Release(ServiceBase):
    COMPONENT = "gateway"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.cache = {}
        self.cache_lock = threading.Lock()

    def routes(self):
        return {("POST", "/pay"): self.pay,
                ("GET", "/balance/*"): self.balance,
                ("GET", "/payment/*"): self.payment}

    def forward(self, method, path, payload=None):
        timeout = float(self.setting("payments_timeout_s", 2.5))
        try:
            return self.call("payments", method, self.url("payments", path), payload, timeout)[1]
        except net.CallError as exc:
            if exc.kind == "http":
                raise net.Reply(exc.status, exc.body)
            if exc.kind == "timeout":
                self.log_every("payments_timeout", 2.0, "ERROR", "upstream_timeout",
                               f"payments did not answer within {timeout}s", path=path)
                raise net.Reply(504, {"error": "payments timeout"})
            self.log_every("payments_unreachable", 2.0, "ERROR", "upstream_unreachable",
                           "payments refused the connection", path=path, detail=exc.detail)
            raise net.Reply(502, {"error": "payments unreachable"})

    def pay(self, request):
        return self.forward("POST", "/pay", request["body"])

    def balance(self, request):
        account = request["tail"]
        ttl = float(self.setting("balance_cache_ttl_s", 0.5))
        with self.cache_lock:
            hit = self.cache.get(account)
        if hit and time.time() - hit[0] < ttl:
            return {**hit[1], "cached": True}
        body = self.forward("GET", f"/balance/{account}")
        with self.cache_lock:
            self.cache[account] = (time.time(), body)
        return {**body, "cached": False}

    def payment(self, request):
        return self.forward("GET", f"/payment/{request['tail']}")
