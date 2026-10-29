"""Rolling request statistics: how many, how fast, how many failed.

Each service keeps one Window for the requests it serves and one per
dependency it calls, so the agent can compare "my side" with "their side".
"""

import threading
import time
from collections import deque


def percentile(values, q):
    """The q-th percentile (0-100) of a list, or None when it is empty."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q / 100 * (len(ordered) - 1)))))
    return ordered[index]


class Window:
    """Thread-safe record of recent outcomes: (time, milliseconds, outcome).

    outcome is "ok", "reject" (a 4xx answer: the request was refused) or
    "error" (a 5xx answer, a timeout or a refused connection).
    """

    def __init__(self, keep_s=900):
        self.keep_s = keep_s
        self.items = deque()
        self.lock = threading.Lock()
        self.total = {"ok": 0, "reject": 0, "error": 0}

    def add(self, ms, outcome, t=None):
        t = time.time() if t is None else t
        with self.lock:
            self.items.append((t, ms, outcome))
            self.total[outcome] = self.total.get(outcome, 0) + 1
            while self.items and self.items[0][0] < t - self.keep_s:
                self.items.popleft()

    def summary(self, window_s=10.0, now=None):
        """Rate, p95 latency, error and reject rates over the last window_s seconds."""
        now = time.time() if now is None else now
        with self.lock:
            recent = [item for item in self.items if item[0] >= now - window_s]
        n = len(recent)
        errors = sum(1 for _, _, o in recent if o == "error")
        rejects = sum(1 for _, _, o in recent if o == "reject")
        return {
            "n": n,
            "rps": round(n / window_s, 2) if window_s else None,
            "p95_ms": _round(percentile([ms for _, ms, _ in recent], 95)),
            "error_rate": round(errors / n, 4) if n else None,
            "reject_rate": round(rejects / n, 4) if n else None,
        }


def _round(value):
    return None if value is None else round(value, 1)
