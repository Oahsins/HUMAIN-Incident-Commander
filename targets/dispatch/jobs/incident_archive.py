"""The incident archive job: exports closed incidents from cad-db to the records system (RMS).

    python -m targets.dispatch.jobs.incident_archive --data runs/dispatch-9500 --export

It runs in exactly one mode:
--export        the normal run, about a second. Copies closed real incidents not yet exported into rms_export,
                at most 50 rows per short transaction. It never changes or removes an incident and holds no
                long lock, so it does not register as a lock holder.
--hold-lock S   opens a write transaction on cad-db and then stalls for S seconds, holding the write lock: no
                call can be entered and no unit record written meanwhile, while readers carry on. It registers
                in cad_locks.json, as a database's session view would show it, so the holder is visible and
                release_lock on cad-db ends it.
--cpu S         a heavy but harmless run that keeps one CPU busy for S seconds, at low priority.

It prints one line when it starts and one when it ends, with counts only.
"""

import argparse
import math
import os
import sqlite3
import sys
import time

import psutil

from ic.kit.proc import alive
from ic.kit.store import write_json
from targets.dispatch import cadstore

BATCH_ROWS = 50
BATCH_GAP_S = 0.01          # between batches, so the centre's own writes get in
EXPORT_BUSY_MS = 1000
HOLD_BUSY_MS = 5000
STATEMENT = "INSERT INTO rms_export ... (export batch)"

# Walks incidents in id order from the last batch ("+status" keeps SQLite off the status index, which would sort
# every closed incident again for each batch), so a batch reads about 50 rows and takes well under a millisecond.
NEXT_BATCH = (f"SELECT id FROM incidents WHERE id > ? AND test = 0 "
              f"AND +status IN ({cadstore.placeholders(cadstore.CLOSED_INCIDENT)}) "
              f"AND id NOT IN (SELECT incident_id FROM rms_export) ORDER BY id LIMIT ?")


def say(pid, text):
    print(f"incident-archive {pid}: {text}", flush=True)


def export(data_dir, batch_rows=BATCH_ROWS):
    """Copy closed real incidents that are not yet exported into rms_export, one short transaction per batch.
    Returns (rows, batches)."""
    conn = cadstore.connect(data_dir, busy_timeout_ms=EXPORT_BUSY_MS)
    rows = batches = after = 0
    try:
        while True:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ids = [row[0] for row in conn.execute(NEXT_BATCH, (after, *cadstore.CLOSED_INCIDENT, batch_rows))]
                now = time.time()
                conn.executemany("INSERT INTO rms_export (incident_id, exported_t) VALUES (?, ?)",
                                 [(incident_id, now) for incident_id in ids])
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            if not ids:
                return rows, batches
            rows, batches, after = rows + len(ids), batches + 1, ids[-1]
            time.sleep(BATCH_GAP_S)
    finally:
        conn.close()


# ----- the lock holders' file (cad_locks.json), which observe() shows under cad-db -----

def register(data_dir, holder):
    """Add this session to cad_locks.json, keeping the other holders that are still running."""
    with cadstore.holders_lock(data_dir):
        keep = [h for h in cadstore.lock_holders(data_dir) if h["pid"] != holder["pid"] and alive(h["pid"])]
        write_json(cadstore.locks_path(data_dir), {"holders": keep + [holder]})


def unregister(data_dir, pid):
    """Remove this session from cad_locks.json. If the file stays locked, the entry names a process about to
    end, and readers skip it then."""
    try:
        with cadstore.holders_lock(data_dir):
            write_json(cadstore.locks_path(data_dir),
                       {"holders": [h for h in cadstore.lock_holders(data_dir) if h["pid"] != pid]})
    except cadstore.HoldersBusy:
        pass


def hold_lock(data_dir, seconds):
    """Take cad-db's write lock and stall with it for `seconds`, registered as a lock holder; then roll back."""
    pid = os.getpid()
    conn = cadstore.connect(data_dir, busy_timeout_ms=HOLD_BUSY_MS)
    try:
        conn.execute("BEGIN IMMEDIATE")
        register(data_dir, {"session": f"incident-archive-{pid}", "pid": pid, "since_t": round(time.time(), 3),
                            "mode": "write", "statement": STATEMENT})
        time.sleep(seconds)   # stuck: the batch never finishes and never commits
    finally:
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        finally:
            conn.close()
            unregister(data_dir, pid)


def burn_cpu(seconds):
    try:   # a batch job runs at low priority, so it slows nothing else down
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except (psutil.Error, OSError):
        pass
    end = time.time() + seconds
    x = 0
    while time.time() < end:
        x = (x * 31 + 7) % 1_000_003


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--export", action="store_true", help="the normal run")
    mode.add_argument("--hold-lock", type=float, metavar="S", help="stall S seconds holding cad-db's write lock")
    mode.add_argument("--cpu", type=float, metavar="S", help="a heavy, harmless run of S seconds")
    args = parser.parse_args(argv)
    seconds = args.cpu if args.hold_lock is None else args.hold_lock
    if not args.export and not (math.isfinite(seconds) and seconds > 0):
        parser.error("S must be a number of seconds above 0")
    pid = os.getpid()
    started = time.time()
    try:
        if args.export:
            say(pid, "export started")
            rows, batches = export(args.data)
            say(pid, f"exported {rows} closed incidents in {batches} batches ({time.time() - started:.1f} s)")
        elif args.hold_lock is not None:
            say(pid, f"export batch started; it holds cad-db's write lock for {seconds:g} s")
            hold_lock(args.data, seconds)
            say(pid, f"export batch rolled back after {time.time() - started:.0f} s")
        else:
            say(pid, f"heavy run started for {seconds:g} s at low priority")
            burn_cpu(seconds)
            say(pid, f"heavy run finished after {time.time() - started:.0f} s")
    except (sqlite3.Error, cadstore.HoldersBusy) as exc:
        say(pid, f"stopped: cad-db or its lock file could not be used ({type(exc).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
