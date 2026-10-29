"""Structured logs, one file per component.

Normal format (v1): one JSON object per line with t, level, component, event, msg.
Format v2 exists for the `log_format_v2` robustness condition: the same facts in
a different layout, so nothing can depend on exact field names.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone

LEVELS = ("INFO", "WARN", "ERROR")


class Logger:
    def __init__(self, component, path, fmt=None):
        self.component = component
        self.path = path
        self.fmt = fmt or os.environ.get("IC_LOG_FORMAT", "v1")
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, level, event, msg, **fields):
        record = {"t": round(time.time(), 3), "level": level, "component": self.component,
                  "event": event, "msg": msg, **fields}
        line = _format(record, self.fmt)
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def info(self, event, msg, **fields):
        self.write("INFO", event, msg, **fields)

    def warn(self, event, msg, **fields):
        self.write("WARN", event, msg, **fields)

    def error(self, event, msg, **fields):
        self.write("ERROR", event, msg, **fields)


def _format(record, fmt):
    if fmt == "v2":
        stamp = datetime.fromtimestamp(record["t"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        extras = {k: v for k, v in record.items() if k not in ("t", "level", "component", "event", "msg")}
        tail = " ".join(f"{k}={json.dumps(v)}" for k, v in extras.items())
        return f"{stamp} [{record['level'].lower()}] {record['component']}/{record['event']}: {record['msg']} {tail}".rstrip()
    return json.dumps(record, ensure_ascii=False)


def read(path, since_t=0.0, limit=200):
    """Read log records newer than since_t, oldest first, at most `limit` (the newest ones).

    v1 lines come back as their JSON objects. Any other line comes back as
    {"t": <parsed time or None>, "raw": <the line>}, so readers cope with format changes.
    """
    if not os.path.exists(path):
        return []
    records = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            record = _parse(line)
            t = record.get("t")
            if t is None or t >= since_t:
                records.append(record)
    return records[-limit:] if limit else records


def _parse(line):
    if line.startswith("{"):
        try:
            return json.loads(line)
        except ValueError:
            pass
    t = None
    try:
        stamp = line.split(" ", 1)[0]
        t = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, IndexError):
        pass
    return {"t": t, "raw": line}
