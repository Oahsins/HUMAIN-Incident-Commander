"""The CAD database (cad-db): incidents, calls, units, assignments and the queue of unit reports, in one SQLite file.

Two tables are written only by triggers, never by a release: `unit_history` (every change of a unit
record's status or incident) and `incident_events` (every incident created, every change of its status,
every incident deleted). They are stamped with the database's own clock, and the checker reads them as
evidence of what CAD showed and when.

The functions at the end are the monitors a centre's staff watch (docs/DISPATCH.md, Monitors). They read
the database directly, so they still answer while the dispatcher or unit-sync is down.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import quote

from ic.kit.store import read_json
from targets.dispatch import area

DB_CLOCK = "(julianday('now') - 2440587.5) * 86400.0"

OPEN_INCIDENT = ("pending", "dispatched", "enroute", "onscene")
CLOSED_INCIDENT = ("closed", "cancelled")
OPEN_ASSIGNMENT = ("assigned", "alerted", "acked", "onscene")
UNIT_STATUSES = ("available", "enroute", "onscene", "outofservice")

# Monitor thresholds (simulated seconds; the centre clock is 1:20, docs/DISPATCH.md).
UNACKNOWLEDGED_S = 3.0      # CAD's "dispatched, not acknowledged" timer
WELFARE_S = 4.0             # CAD's en-route and on-scene status timers
REPORT_OVERDUE_S = 3.0      # CAD's terminal-not-reporting indicator

SCHEMA = """
CREATE TABLE incidents (id INTEGER PRIMARY KEY AUTOINCREMENT, first_call_id TEXT NOT NULL, ani TEXT NOT NULL,
  nature TEXT NOT NULL, priority INTEGER NOT NULL, unit_type TEXT NOT NULL, narrative TEXT NOT NULL,
  x REAL NOT NULL, y REAL NOT NULL, location_source TEXT NOT NULL,
  status TEXT NOT NULL, test INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, release TEXT,
  created_t REAL NOT NULL, pending_since REAL, updated_t REAL NOT NULL, closed_t REAL, close_reason TEXT);
CREATE TABLE calls (call_id TEXT PRIMARY KEY, incident_id INTEGER NOT NULL, ani TEXT NOT NULL,
  linked INTEGER NOT NULL, test INTEGER NOT NULL DEFAULT 0, t REAL NOT NULL);
CREATE TABLE units (id TEXT PRIMARY KEY, type TEXT NOT NULL, station TEXT NOT NULL, test INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, incident_id INTEGER, status_t REAL, status_since REAL NOT NULL, applied_t REAL, source TEXT);
CREATE TABLE unit_history (id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id TEXT NOT NULL, status TEXT NOT NULL,
  incident_id INTEGER, t REAL NOT NULL);
CREATE TABLE incident_events (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL,
  op TEXT NOT NULL, status TEXT, first_call_id TEXT, test INTEGER, t REAL NOT NULL);
CREATE TABLE assignments (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL, unit_id TEXT NOT NULL,
  status TEXT NOT NULL, source TEXT NOT NULL, test INTEGER NOT NULL DEFAULT 0,
  assigned_t REAL NOT NULL, alerted_t REAL, next_alert_t REAL, acked_t REAL, closed_t REAL);
CREATE TABLE field_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id TEXT, payload_json TEXT NOT NULL,
  status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_t REAL NOT NULL, updated_t REAL NOT NULL);
CREATE TABLE rms_export (incident_id INTEGER PRIMARY KEY, exported_t REAL NOT NULL);

CREATE INDEX incidents_board ON incidents(status, priority, id);
CREATE INDEX incidents_ani ON incidents(ani, status);
CREATE INDEX calls_incident ON calls(incident_id);
CREATE INDEX unit_history_unit ON unit_history(unit_id, t);
CREATE INDEX incident_events_incident ON incident_events(incident_id);
CREATE INDEX assignments_status ON assignments(status, unit_id);
CREATE INDEX assignments_incident ON assignments(incident_id);
CREATE INDEX field_queue_status ON field_queue(status, id);
CREATE INDEX field_queue_unit ON field_queue(unit_id, status, id);
CREATE INDEX field_queue_updated ON field_queue(updated_t);
"""

TRIGGERS = f"""
CREATE TRIGGER units_history_insert AFTER INSERT ON units
BEGIN
  INSERT INTO unit_history (unit_id, status, incident_id, t) VALUES (NEW.id, NEW.status, NEW.incident_id, {DB_CLOCK});
END;
CREATE TRIGGER units_history_update AFTER UPDATE OF status, incident_id ON units
WHEN OLD.status IS NOT NEW.status OR OLD.incident_id IS NOT NEW.incident_id
BEGIN
  INSERT INTO unit_history (unit_id, status, incident_id, t) VALUES (NEW.id, NEW.status, NEW.incident_id, {DB_CLOCK});
END;
CREATE TRIGGER incident_events_insert AFTER INSERT ON incidents
BEGIN
  INSERT INTO incident_events (incident_id, op, status, first_call_id, test, t)
  VALUES (NEW.id, 'insert', NEW.status, NEW.first_call_id, NEW.test, {DB_CLOCK});
END;
CREATE TRIGGER incident_events_status AFTER UPDATE OF status ON incidents
WHEN OLD.status IS NOT NEW.status
BEGIN
  INSERT INTO incident_events (incident_id, op, status, first_call_id, test, t)
  VALUES (NEW.id, 'update', NEW.status, NEW.first_call_id, NEW.test, {DB_CLOCK});
END;
CREATE TRIGGER incident_events_delete AFTER DELETE ON incidents
BEGIN
  INSERT INTO incident_events (incident_id, op, status, first_call_id, test, t)
  VALUES (OLD.id, 'delete', OLD.status, OLD.first_call_id, OLD.test, {DB_CLOCK});
END;
"""


def path(data_dir):
    return os.path.join(data_dir, "cad.db")


def locks_path(data_dir):
    return os.path.join(data_dir, "cad_locks.json")


class HoldersBusy(Exception):
    """cad_locks.json stayed locked by another process."""


@contextmanager
def holders_lock(data_dir, wait_s=2.0):
    """A short lock on cad_locks.json, for every process that rewrites it: cad_locks.lock, made with
    O_CREAT|O_EXCL and closed at once (Windows has no fcntl, and cannot remove an open file). Tried every 50 ms
    for up to wait_s; one older than 5 s was left by a process that died while holding it, and is removed."""
    lock = os.path.splitext(locks_path(data_dir))[0] + ".lock"
    deadline = time.time() + wait_s
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 5.0:
                    os.remove(lock)
            except OSError:
                pass
        except PermissionError:   # Windows: another process is removing it
            pass
        if time.time() >= deadline:
            raise HoldersBusy()
        time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def lock_holders(data_dir):
    """The entries of cad_locks.json that are well formed: a dict with a whole pid above 0. Never raises."""
    try:
        doc = read_json(locks_path(data_dir), {"holders": []})
    except OSError:
        return []
    holders = doc.get("holders") if isinstance(doc, dict) else None
    return [h for h in holders if isinstance(h, dict) and isinstance(h.get("pid"), int)
            and not isinstance(h["pid"], bool) and h["pid"] > 0] if isinstance(holders, list) else []


def connect(data_dir, busy_timeout_ms=1000, readonly=False):
    """Open cad-db. Writers wait up to busy_timeout_ms for a lock, then fail with 'database is locked'."""
    if readonly:   # quoted, so a folder name with "#", "?" or "%" cannot change what the URI opens
        uri = "file:" + quote(path(data_dir).replace("\\", "/"), safe="/:") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=busy_timeout_ms / 1000, isolation_level=None,
                               check_same_thread=False)
    else:
        conn = sqlite3.connect(path(data_dir), timeout=busy_timeout_ms / 1000, isolation_level=None,
                               check_same_thread=False)
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.row_factory = sqlite3.Row
    return conn


def create(data_dir):
    """A fresh cad-db: the schema, the evidence triggers, and every unit available at its station."""
    conn = sqlite3.connect(path(data_dir), isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.executescript(TRIGGERS)
        now = time.time()
        rows = [(u["id"], u["type"], u["station"], 0) for u in area.UNITS]
        rows.append((area.TEST_UNIT, "test", area.TEST_STATION, 1))
        conn.executemany("INSERT INTO units (id, type, station, test, status, incident_id, status_t, status_since, "
                         "applied_t, source) VALUES (?, ?, ?, ?, 'available', NULL, NULL, ?, NULL, 'seed')",
                         [(*row, now) for row in rows])
    finally:
        conn.close()


def placeholders(values):
    return ", ".join("?" for _ in values)


# ----- monitors (docs/DISPATCH.md, Monitors); integrity counts leave out test rows and TEST-1 -----

def pending_board(conn, now, window_s):
    """The dispatcher's pending board: real incidents waiting for a unit, the oldest one's time since entry,
    and units committed by the dispatcher per second."""
    depth, oldest = conn.execute("SELECT COUNT(*), MIN(created_t) FROM incidents "
                                 "WHERE status = 'pending' AND test = 0").fetchone()
    committed = conn.execute("SELECT COUNT(*) FROM assignments WHERE source = 'dispatcher' AND assigned_t >= ?",
                             (now - window_s,)).fetchone()[0]
    return {"queue_depth": depth,
            "oldest_pending_s": round(max(0.0, now - oldest), 1) if oldest is not None else 0.0,
            "processed_per_s": round(committed / window_s, 2) if window_s else None}


def units_not_acknowledging(conn, now):
    return conn.execute("SELECT COUNT(DISTINCT unit_id) FROM assignments WHERE test = 0 "
                        "AND status IN ('assigned', 'alerted') AND assigned_t < ?",
                        (now - UNACKNOWLEDGED_S,)).fetchone()[0]


def unit_status_timers_expired(conn, now):
    return conn.execute("SELECT COUNT(*) FROM units WHERE test = 0 AND status IN ('enroute', 'onscene') "
                        "AND status_since < ?", (now - WELFARE_S,)).fetchone()[0]


def possible_duplicate_incidents(conn):
    """Open real incidents that share a caller's number with another open real incident."""
    return conn.execute(f"SELECT COALESCE(SUM(n), 0) FROM (SELECT COUNT(*) AS n FROM incidents WHERE test = 0 "
                        f"AND status IN ({placeholders(OPEN_INCIDENT)}) GROUP BY ani HAVING COUNT(*) > 1)",
                        OPEN_INCIDENT).fetchone()[0]


def unit_reports_overdue(conn, now):
    return conn.execute("SELECT COUNT(*) FROM units WHERE test = 0 AND COALESCE(applied_t, status_since) < ?",
                        (now - REPORT_OVERDUE_S,)).fetchone()[0]


def field_queue_state(conn, now, window_s):
    """unit-sync's queue as the CAD administrator sees it. Counts every row, test reports included."""
    depth, oldest = conn.execute("SELECT COUNT(*), MIN(created_t) FROM field_queue "
                                 "WHERE status = 'pending'").fetchone()
    head = conn.execute("SELECT id, created_t, attempts FROM field_queue WHERE status = 'pending' "
                        "ORDER BY id LIMIT 1").fetchone()
    quarantined = conn.execute("SELECT COUNT(*) FROM field_queue WHERE status = 'quarantined'").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM field_queue WHERE updated_t >= ? AND status IN ('applied', 'skipped')",
                        (now - window_s,)).fetchone()[0]
    return {"queue_depth": depth,
            "oldest_pending_s": round(max(0.0, now - oldest), 1) if oldest is not None else 0.0,
            "processed_per_s": round(done / window_s, 2) if window_s else None,
            "head_item": ({"id": head[0], "age_s": round(max(0.0, now - head[1]), 1), "attempts": head[2]}
                          if head else None),
            "quarantined_items": quarantined}
