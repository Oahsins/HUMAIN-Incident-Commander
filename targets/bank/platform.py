"""Start and stop one copy of the test bank (CONTRACT.md section 6).

    p = Platform(port_base=8100).start()
    adapter, control = p.adapter(), p.control()
    ...
    p.stop()
"""

from ic.kit.client import PlatformBase
from targets.bank import checker
from targets.bank.adapter import Adapter
from targets.bank.control import Control


class Platform(PlatformBase):
    system = "bank"
    adapter_cls = Adapter
    control_cls = Control
    # four_faults and cheap_model change the scenario and the agent, not the bank. extra_service arrives
    # with the notifications component.
    conditions = ("default", "four_faults", "log_format_v2", "cheap_model")

    def after_warmup(self, warmup_s):
        checker.record_baseline(self.control(), window_s=warmup_s)
