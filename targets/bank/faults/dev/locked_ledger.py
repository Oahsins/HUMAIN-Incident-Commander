"""Practice fault: a stuck reconciliation batch holds the ledger's write lock (root cause: lock_held).

New payments wait for the lock, time out and fail with "ledger busy"; the
clearing worker cannot mark payments cleared. The lock holder shows in the
ledger's lock view. The right fix is to end the session holding the lock.

params: {"hold_s": 600}
"""

import os
import time

from ic.kit.store import read_json
from targets.bank import ledger

TYPE = "locked_ledger"
CLASSES = ["lock_held"]


def inject(control, params, rng):
    hold_s = float(params.get("hold_s", 600))
    pid = control.spawn("reconciliation", ["{python}", "-m", "targets.bank.jobs.reconciliation",
                                           "--data", "{data}", "--hold-lock", str(hold_s)])
    path = ledger.locks_path(control.paths()["data_dir"])
    deadline = time.time() + 5
    while time.time() < deadline:   # wait until the job really holds the lock
        if any(h["pid"] == pid for h in read_json(path, {"holders": []})["holders"]):
            break
        time.sleep(0.05)
    return {"type": TYPE, "target": "ledger", "class": "lock_held",
            "detail": {"holder_pid": pid, "hold_s": hold_s, "holding": os.path.exists(path)}, "t": time.time()}
