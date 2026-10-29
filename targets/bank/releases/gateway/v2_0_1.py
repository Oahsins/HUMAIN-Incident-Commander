"""Gateway release 2.0.1: a harmless release that only adds a build label to answers.

Used by the `noise` fault as a healthy distractor: a deploy that changes nothing important.
"""

from targets.bank.releases.gateway.v2_0 import Release as Base


class Release(Base):
    def pay(self, request):
        return {**super().pay(request), "gateway_build": "2.0.1"}
