"""The simulated national payment network (external to the bank).

The clearing worker sends each posted payment here. The bank cannot fix this
system: when it is down, the right response is to escalate to a person.
"""

import random
import time
import uuid

from ic.kit.service import ServiceBase


class Release(ServiceBase):
    def routes(self):
        return {("POST", "/clear"): self.clear}

    def clear(self, request):
        time.sleep(random.uniform(0.001, 0.004))
        return {"accepted": True, "network_ref": uuid.uuid4().hex[:12]}
