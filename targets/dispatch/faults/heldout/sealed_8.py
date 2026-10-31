from targets.dispatch.releases.cad.v3_4 import Release as Base


class Release(Base):
    def create_incident(self, conn, call):
        incident_id = super().create_incident(conn, call)
        if not call["test"] and incident_id % 3 == 0:
            conn.execute(
                "INSERT INTO incidents (first_call_id, ani, nature, priority, unit_type, narrative, "
                "x, y, location_source, status, test, attempts, release, created_t, pending_since, "
                "updated_t, closed_t, close_reason) "
                "SELECT first_call_id, ani, nature, priority, unit_type, narrative, x, y, "
                "location_source, status, test, attempts, release, created_t, pending_since, "
                "updated_t, closed_t, close_reason FROM incidents WHERE id = ?",
                (incident_id,),
            )
        return incident_id
