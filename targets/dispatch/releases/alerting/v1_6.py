"""Alerting release 1.6: the station alerting controller.

The dispatcher posts each station alert here (POST /alert), and the controller tones out the unit's station: the
alert goes as one JSON line onto this controller's station inbox, <data>/alerts-<component>.jsonl, which the
crews read. The same release runs as alerting (the county network) and as alerting-backup (the radio tone path);
each writes its own inbox.
"""

import json
import os
import threading
import time

from ic.kit import net
from ic.kit.service import ServiceBase


class Release(ServiceBase):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.inbox = os.path.join(self.data_dir, f"alerts-{self.component}.jsonl")
        self.inbox_lock = threading.Lock()

    def routes(self):
        return {("POST", "/alert"): self.alert}

    def alert(self, request):
        body = request["body"]
        if not isinstance(body, dict):
            raise net.Reply(400, {"error": "body: not an object"})
        if not isinstance(body.get("unit"), str):
            raise net.Reply(400, {"error": "unit: missing or not text"})
        return self.deliver(body)

    def deliver(self, alert):
        """One whole line per alert, so a crew reading the inbox never sees half of one."""
        line = json.dumps({"t": time.time(), **alert}) + "\n"
        with self.inbox_lock:
            with open(self.inbox, "a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
        return {"delivered": True}
