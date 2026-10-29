"""Privileged operations on a running test bank (CONTRACT.md section 5).

For the fault injector, the checker and the evaluation harness. Never given to the agent.
"""

import os

from ic.kit.client import ControlClient
from targets.bank import ledger


class Control(ControlClient):
    def db(self, name=None):
        """A direct connection to a datastore (the bank has one: the ledger). Writers wait up to 5 s for a lock."""
        if name not in (None, "ledger"):
            raise KeyError(f"the bank has no datastore named {name!r}")
        return ledger.connect(self.data_dir, busy_timeout_ms=5000)

    def paths(self):
        d = self.data_dir
        customers = os.path.join(d, "customers.jsonl")
        return {**super().paths(), "traffic_log": customers, "customers_log": customers,
                "datastores": {"ledger": ledger.path(d)}, "ledger": ledger.path(d),
                "checker_baseline": os.path.join(d, "checker_baseline.json")}
