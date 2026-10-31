"""The dispatch centre's adapter: the five functions the incident commander may use (CONTRACT.md section 3).

Like the bank, the dispatch centre runs behind the generic control plane, so its adapter is the generic
HTTP one. Nothing here knows about calls, units or incidents: the same agent drives both systems.
"""

from ic.kit.client import OpsAdapter


class Adapter(OpsAdapter):
    pass
