"""The bank's adapter: the five functions the incident commander may use (CONTRACT.md section 3).

The bank runs behind the generic control plane, so its adapter is the generic
HTTP one. An adapter for a system the agent has never seen (one an organiser
supplies, say) implements the same five methods against that system's own
metrics, logs and runbook actions instead.
"""

from ic.kit.client import OpsAdapter


class Adapter(OpsAdapter):
    pass
