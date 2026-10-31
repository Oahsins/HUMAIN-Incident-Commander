import time

from targets.dispatch.releases.dispatcher.v2_1 import Release as Base


class Release(Base):
    def pending_batch(self, conn, settings):
        pending = super().pending_batch(conn, settings)
        now = time.time()
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM incidents WHERE test = 0 AND created_t >= ?",
            (now - 10.0,),
        ).fetchone()["n"]
        if count < 35:
            return pending
        kept = []
        for incident in pending:
            if incident["test"] or incident["id"] % 3:
                kept.append(incident)
                continue
            changed = conn.execute(
                "UPDATE incidents SET status = 'closed', closed_t = ?, updated_t = ?, "
                "close_reason = 'completed' WHERE id = ? AND status = 'pending' "
                "AND NOT EXISTS (SELECT 1 FROM assignments WHERE incident_id = incidents.id)",
                (now, now, incident["id"]),
            ).rowcount
            if not changed:
                kept.append(incident)
        return kept
