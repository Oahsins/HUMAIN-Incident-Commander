"""The 9-1-1 call network provider's location service (ALI), run by another organisation.

Call handling asks it where a caller's number is (POST /ali). It answers from the phone company's records: a
fixed point for every number in its pools, and 404 for a number it has no record of. The centre cannot change
this system: when it fails, calls go on with the location the caller gives, and the right response is to
escalate to the provider.
"""

import random
import time

from ic.kit import net
from ic.kit.service import ServiceBase
from targets.dispatch import area


class Release(ServiceBase):
    def routes(self):
        return {("POST", "/ali"): self.ali}

    def ali(self, request):
        body = request["body"]
        ani = body.get("ani") if isinstance(body, dict) else None
        if not (area.valid_number(ani) and len(ani) == 12 and ani.isascii()):
            raise net.Reply(400, {"error": "ani: not a valid number"})
        if not area.known_number(ani):
            raise net.Reply(404, {"error": "ani: unknown"})
        time.sleep(random.uniform(0.001, 0.004))   # the records lookup
        x, y = self.locate(ani)
        return {"x": x, "y": y}

    def locate(self, ani):
        return area.subscriber_location(ani)
