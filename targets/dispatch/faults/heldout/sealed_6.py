import time

from targets.dispatch.releases.unit_sync.v4_0 import Release as Base


class Release(Base):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.started_at = time.monotonic()

    def apply_unit(self, conn, msg):
        elapsed = max(0.0, time.monotonic() - self.started_at)
        count = min(4, 1 + int(elapsed // 20.0))
        if msg.unit in ("M1", "E1", "M2", "E2")[:count]:
            msg = msg._replace(status="outofservice", incident_id=None)
        return super().apply_unit(conn, msg)
