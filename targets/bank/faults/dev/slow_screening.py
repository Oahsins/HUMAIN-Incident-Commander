"""Practice fault: the network link to the primary fraud-screening service slows down (root cause: dependency_slow).

Screening answers take longer than payments will wait, so payments fail with
"screening unavailable". Restarting screening does not help: the link is slow,
not the process. The right fix is to fail over to the standby screening service.

params: {"latency_ms": 1500, "jitter_ms": 300}
"""

import time

TYPE = "slow_screening"
CLASSES = ["dependency_slow"]


def inject(control, params, rng):
    latency = int(params.get("latency_ms", 1500))
    jitter = int(params.get("jitter_ms", 300))
    control.link("payments->screening", latency_ms=latency, jitter_ms=jitter)
    return {"type": TYPE, "target": "screening", "class": "dependency_slow",
            "detail": {"route": "payments->screening", "latency_ms": latency, "jitter_ms": jitter}, "t": time.time()}
