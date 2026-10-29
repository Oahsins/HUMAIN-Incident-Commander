"""The overnight reconciliation job, which faults can make misbehave.

--hold-lock S   opens a write transaction on the ledger and then stalls for S
                seconds, holding the lock: new payments cannot be posted. It
                registers itself in ledger_locks.json, as a database's session
                view would show it, so the lock holder is visible.
--cpu S         a heavy but harmless run that burns CPU for S seconds (a
                healthy distractor).

Run: python -m targets.bank.jobs.reconciliation --data runs/bank-8100 --hold-lock 600
"""

import argparse
import os
import time

import psutil

from ic.kit.store import read_json, write_json
from targets.bank import ledger


def register(data_dir, holder):
    path = ledger.locks_path(data_dir)
    doc = read_json(path, {"holders": []})
    doc["holders"] = [h for h in doc["holders"] if h["pid"] != os.getpid()] + [holder]
    write_json(path, doc)


def hold_lock(data_dir, seconds):
    conn = ledger.connect(data_dir, busy_timeout_ms=5000)
    conn.execute("BEGIN IMMEDIATE")
    register(data_dir, {"session": "reconciliation", "pid": os.getpid(), "since_t": time.time(),
                        "mode": "write", "statement": "UPDATE accounts SET ... (reconciliation batch)"})
    time.sleep(seconds)   # stuck: the batch never finishes and never commits
    conn.execute("ROLLBACK")


def burn_cpu(seconds):
    try:   # a batch job runs at low priority, so it slows nothing else down
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except (psutil.Error, OSError):
        pass
    end = time.time() + seconds
    x = 0
    while time.time() < end:
        x = (x * 31 + 7) % 1_000_003


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--hold-lock", type=float, default=0)
    parser.add_argument("--cpu", type=float, default=0)
    args = parser.parse_args()
    if args.hold_lock:
        hold_lock(args.data, args.hold_lock)
    elif args.cpu:
        burn_cpu(args.cpu)


if __name__ == "__main__":
    main()
