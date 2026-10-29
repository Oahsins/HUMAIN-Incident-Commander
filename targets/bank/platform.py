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
    # four_faults and model_swap change the scenario and the agent, not the bank. extra_service arrives
    # with the notifications component.
    conditions = ("default", "four_faults", "log_format_v2", "model_swap")
    # `python run.py demo`: a bad transfer limit pushed by the pipeline, and slow fraud screening.
    demo_faults = [{"type": "bad_setting", "at_s": 0, "params": {"variant": "transfer_limit", "actor": "pipeline"}},
                   {"type": "slow_screening", "at_s": 0, "params": {}}]

    def after_warmup(self, warmup_s):
        checker.record_baseline(self.control(), window_s=warmup_s)
