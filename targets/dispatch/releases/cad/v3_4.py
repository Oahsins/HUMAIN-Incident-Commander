"""CAD release 3.4: the computer-aided dispatch server.

POST /calls enters a 9-1-1 call that call handling has answered, in one write transaction:
1. a call CAD already holds gets its incident again, so entering a call twice is harmless;
2. under repeat_match "ani_open", a repeat call from a number with an open incident is linked to that incident;
3. any other call creates a pending incident, with the priority and unit type its nature calls for.

POST /mdt is the gateway for unit terminals: it queues each status report as it comes, for unit-sync to apply,
and checks nothing but its shape and size.

A busy or failing cad-db fails the request with 503 and counts as a failed write. Logs carry ids, never what a
caller said or where they are.
"""

import json
import math
import re
import sqlite3
import threading
import time

from ic.kit import net
from ic.kit.service import ServiceBase
from ic.kit.stats import Window
from targets.dispatch import area, cadstore
from targets.dispatch.worker import check_settings, is_busy

CALL_ID = re.compile(r"C-[0-9a-f]{8}")
NARRATIVE_MAX = 500
REPORT_MAX_BYTES = 4096     # a terminal report, encoded
UNIT_ID_MAX = 16
LOCATION_SOURCES = ("ali", "verbal")
UNAVAILABLE = {"error": "cad unavailable (settings)"}


class Release(ServiceBase):
    SETTINGS = {"repeat_match": ("enum", ("ani_open", "off")), "write_timeout_ms": ("int", 1, 10000)}

    def __init__(self, ctx):
        super().__init__(ctx)
        self.local = threading.local()
        self.write_errors = Window()
        self.unusable_lock = threading.Lock()
        self.unusable_mark = (0.0, 0)   # when settings_unusable was last written, and how often it came up since

    def routes(self):
        return {("POST", "/calls"): self.create_call, ("POST", "/mdt"): self.mdt}

    # ----- entering a call -----

    def validate_call(self, body):
        """The call as CAD keeps it; a 400 names the first field that is wrong, never its value."""
        if not isinstance(body, dict):
            raise net.Reply(400, {"error": "body: not an object"})
        call_id, ani, test, nature = (body.get(key) for key in ("call_id", "ani", "test", "nature"))
        if not isinstance(call_id, str) or not CALL_ID.fullmatch(call_id):
            raise net.Reply(400, {"error": "call_id: not a call id"})
        if not valid_number(ani):
            raise net.Reply(400, {"error": "ani: not a valid number"})
        if not (isinstance(test, int) and not isinstance(test, bool) and test in (0, 1)):
            raise net.Reply(400, {"error": "test: not 0 or 1"})
        if not isinstance(nature, str) or nature not in area.NATURES:
            raise net.Reply(400, {"error": "nature: not a known nature"})
        if nature == "test" and test != 1:
            raise net.Reply(400, {"error": "nature: test is only for test calls"})
        narrative = body.get("narrative")
        if not _text(narrative, NARRATIVE_MAX):
            raise net.Reply(400, {"error": f"narrative: not text of at most {NARRATIVE_MAX} characters"})
        location = _point(body.get("location"))
        if location is None:
            raise net.Reply(400, {"error": "location: not {x, y} finite numbers"})
        source = body.get("location_source")
        if not isinstance(source, str) or source not in LOCATION_SOURCES:
            raise net.Reply(400, {"error": "location_source: not ali or verbal"})
        return {"call_id": call_id, "ani": ani, "nature": nature, "narrative": narrative, "location": location,
                "location_source": source, "test": test}

    def find_call(self, conn, call_id):
        row = conn.execute("SELECT incident_id, linked FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        return {"incident_id": row[0], "linked": bool(row[1])} if row else None

    def find_open_incident(self, conn, ani, test):
        """The newest open incident from this number, as CAD's repeat-call check finds it."""
        row = conn.execute(f"SELECT id FROM incidents WHERE ani = ? AND test = ? AND status IN "
                           f"({cadstore.placeholders(cadstore.OPEN_INCIDENT)}) ORDER BY id DESC LIMIT 1",
                           (ani, test, *cadstore.OPEN_INCIDENT)).fetchone()
        return row[0] if row else None

    def create_incident(self, conn, call):
        """A new pending incident, and the call that opened it."""
        now = time.time()
        nature = area.NATURES[call["nature"]]
        cursor = conn.execute(
            "INSERT INTO incidents (first_call_id, ani, nature, priority, unit_type, narrative, x, y, "
            "location_source, status, test, attempts, release, created_t, pending_since, updated_t) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 0, ?, ?, ?, ?)",
            (call["call_id"], call["ani"], call["nature"], nature["priority"], nature["unit_type"],
             call["narrative"], call["location"]["x"], call["location"]["y"], call["location_source"],
             call["test"], self.version, now, now, now))
        incident_id = cursor.lastrowid
        conn.execute("INSERT INTO calls (call_id, incident_id, ani, linked, test, t) VALUES (?, ?, ?, 0, ?, ?)",
                     (call["call_id"], incident_id, call["ani"], call["test"], now))
        return incident_id

    def link_call(self, conn, incident_id, call):
        conn.execute("INSERT INTO calls (call_id, incident_id, ani, linked, test, t) VALUES (?, ?, ?, 1, ?, ?)",
                     (call["call_id"], incident_id, call["ani"], call["test"], time.time()))

    def create_call(self, request):
        settings = self._settings()
        call = self.validate_call(request["body"])

        def enter(conn):
            held = self.find_call(conn, call["call_id"])
            if held is not None:
                return "held", held["incident_id"], held["linked"]
            if settings["repeat_match"] == "ani_open":
                incident_id = self.find_open_incident(conn, call["ani"], call["test"])
                if incident_id is not None:
                    self.link_call(conn, incident_id, call)
                    return "linked", incident_id, True
            return "created", self.create_incident(conn, call), False

        outcome, incident_id, linked = self._write("calls", settings, enter)
        if outcome == "linked":
            self.log.info("call_linked", f"call {call['call_id']} linked to open incident {incident_id}",
                          call_id=call["call_id"], incident_id=incident_id)
        elif outcome == "created":
            priority = area.NATURES[call["nature"]]["priority"]
            self.log.info("incident_created", f"incident {incident_id} created from call {call['call_id']}",
                          incident_id=incident_id, call_id=call["call_id"], priority=priority)
            raise net.Reply(201, {"incident_id": incident_id, "linked": False})
        return {"incident_id": incident_id, "linked": linked}

    # ----- the gateway for unit terminals -----

    def mdt(self, request):
        settings = self._settings()
        body = request["body"]
        payload = _encoded(body) if isinstance(body, dict) else None
        if payload is None or len(payload) > REPORT_MAX_BYTES:
            raise net.Reply(400, {"error": "body: not an object or too large"})
        unit = body.get("unit")
        unit_id = unit if _text(unit, UNIT_ID_MAX) else None

        def queue(conn):
            now = time.time()
            cursor = conn.execute("INSERT INTO field_queue (unit_id, payload_json, status, attempts, created_t, "
                                  "updated_t) VALUES (?, ?, 'pending', 0, ?, ?)", (unit_id, payload, now, now))
            return cursor.lastrowid

        return {"queued": self._write("mdt", settings, queue)}

    def extra_metrics(self, window_s):
        return {"db_write_errors": self.write_errors.summary(window_s)["n"]}

    # ----- cad-db -----

    def _db(self, timeout_ms):
        """This handler thread's connection; its busy timeout follows write_timeout_ms on every request."""
        conn = getattr(self.local, "conn", None)
        if conn is None:
            conn = self.local.conn = cadstore.connect(self.data_dir, busy_timeout_ms=timeout_ms)
        conn.execute(f"PRAGMA busy_timeout = {int(timeout_ms)}")
        return conn

    def _write(self, operation, settings, work):
        """work(conn) in one BEGIN IMMEDIATE. A busy or failing cad-db rolls back and answers 503."""
        conn = None
        try:
            conn = self._db(settings["write_timeout_ms"])
            conn.execute("BEGIN IMMEDIATE")
            result = work(conn)
            conn.execute("COMMIT")
            return result
        except sqlite3.Error as exc:
            _rollback(conn)
            self.write_errors.add(0.0, "error")
            if isinstance(exc, sqlite3.OperationalError) and is_busy(exc):
                self.log_every(f"db_busy:{operation}", 2.0, "WARN", "db_busy",
                               f"cad-db is busy; the {operation} write was not made", operation=operation)
                raise net.Reply(503, {"error": "cad-db busy"}) from None
            self.log_every(f"db_error:{operation}", 2.0, "ERROR", "db_error",
                           f"cad-db could not be written ({type(exc).__name__})", operation=operation,
                           error=type(exc).__name__)
            self._drop_connection()
            raise net.Reply(503, {"error": "cad-db unavailable"}) from None
        finally:
            _rollback(conn)   # nothing is left open, whatever ended the work

    def _drop_connection(self):
        conn = getattr(self.local, "conn", None)
        self.local.conn = None
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    # ----- settings -----

    def _settings(self):
        """The settings in force. A value that cannot be used answers 503 and is logged by its key, never its
        value."""
        settings, bad_key = check_settings(self.config.values()[0], self.SETTINGS)
        if settings is None:
            self._log_unusable(bad_key)
            raise net.Reply(503, dict(UNAVAILABLE))
        return settings

    def _log_unusable(self, bad_key):
        """One ERROR line every 2 s naming the setting. Not log_every: its own first parameter is called key."""
        now = time.time()
        with self.unusable_lock:
            last_t, count = self.unusable_mark
            if now - last_t < 2.0:
                self.unusable_mark = (last_t, count + 1)
                return
            self.unusable_mark = (now, 0)
        self.log.error("settings_unusable",
                       f"setting {bad_key} cannot be used; calls and unit reports are refused until it changes",
                       occurrences=count + 1, key=bad_key)


def valid_number(ani):
    """A number of the shape 0PP-555-01NN, in ASCII digits with nothing after it."""
    return area.valid_number(ani) and len(ani) == 12 and ani.isascii()


def _rollback(conn):
    if conn is None:
        return
    try:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _encoded(body):
    try:
        return json.dumps(body)
    except (TypeError, ValueError, RecursionError):
        return None


def _text(value, limit):
    """A str of at most `limit` characters that the database can store."""
    if not isinstance(value, str) or len(value) > limit:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _point(value):
    """{x, y} as two finite floats, or None."""
    if not isinstance(value, dict):
        return None
    xy = []
    for key in ("x", "y"):
        v = value.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        try:
            v = float(v)
        except OverflowError:
            return None
        if not math.isfinite(v):
            return None
        xy.append(v)
    return {"x": xy[0], "y": xy[1]}
