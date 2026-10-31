"""Put one unreadable item into the clearing queue through the control layer."""

import time

TYPE = "poison_payment"
CLASSES = ["poison_message"]


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameter")
    if params.get("target") != "clearing" or params.get("variant") != "v1":
        raise ValueError("unsupported target or variant")
    now = time.time()
    conn = control.db("ledger")
    try:
        # No payment or posting is invented. This is a malformed work item only.
        cursor = conn.execute(
            "INSERT INTO clearing_queue "
            "(payment_id, payload_json, status, attempts, created_t, updated_t) "
            "VALUES (?, ?, 'pending', 0, ?, ?)",
            ("batch-017", "{", now, now),
        )
        conn.commit()
        item = cursor.lastrowid
    finally:
        conn.close()
    return {"type": TYPE, "target": "clearing", "class": "poison_message",
            "detail": {"item": item}, "t": now}
