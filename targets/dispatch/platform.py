"""Start and stop one copy of the test dispatch centre (CONTRACT.md section 6, docs/DISPATCH.md).

    p = Platform(port_base=9500).start()
    adapter, control = p.adapter(), p.control()
    ...
    p.stop()
"""

from ic.kit.client import PlatformBase
from targets.dispatch import checker
from targets.dispatch.adapter import Adapter
from targets.dispatch.control import Control


class Platform(PlatformBase):
    system = "dispatch"
    adapter_cls = Adapter
    control_cls = Control
    conditions = ("default",)
    demo_faults = []   # the dispatch centre has no practice faults

    def after_warmup(self, warmup_s):
        checker.record_baseline(self.control(), window_s=warmup_s)
