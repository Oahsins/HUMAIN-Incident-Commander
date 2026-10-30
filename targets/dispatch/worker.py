"""The loop the dispatcher and unit-sync share.

Each cycle a worker waits at the server's gate (a hung process does no work), checks its settings, runs
one cycle of its own work against cad-db, then sleeps for its poll interval. It sleeps in 0.25 s slices
and wakes early when its settings change, so an undone setting takes effect at once.

Settings are numbers or named choices, never true/false. A setting that cannot be used pauses the work
and logs one line every 2 s naming the setting (never its value). A busy or failing database ends the
cycle and counts as a write error; only a report the worker cannot read, or a bug, stops the process.
"""

import sqlite3
import threading
import time

from ic.kit.service import ServiceBase
from ic.kit.stats import Window
from targets.dispatch import cadstore


def usable(value, rule):
    """Can a setting's value be used? rule is ("num", lo, hi): lo < v <= hi; ("int", lo, hi): a whole number
    with lo <= v <= hi; ("enum", values): one of the values. True and false are never usable."""
    kind = rule[0]
    if kind == "enum":
        return isinstance(value, str) and value in rule[1]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    lo, hi = rule[1], rule[2]
    if kind == "int":
        return float(value).is_integer() and lo <= value <= hi
    return lo < value <= hi


def check_settings(values, schema):
    """(settings, None) when every setting in the schema is usable, else (None, the first unusable key)."""
    settings = {}
    for key, rule in schema.items():
        value = values.get(key)
        try:
            ok = usable(value, rule)
        except (OverflowError, ValueError):   # a number too large to compare as a float
            ok = False
        if not ok:
            return None, key
        settings[key] = int(value) if rule[0] == "int" else value
    return settings, None


def is_busy(exc):
    text = str(exc).lower()
    return "locked" in text or "busy" in text


class Worker(ServiceBase):
    """Subclass this, set SETTINGS and OPERATION, and write cycle(conn, settings) -> items handled."""

    SETTINGS = {}
    OPERATION = "work"
    BUSY_MS = 1000
    cycle_version = None   # the settings version the current cycle ran with, set by run_loop

    def __init__(self, ctx):
        super().__init__(ctx)
        self.local = threading.local()
        self.write_errors = Window()
        self.unusable_lock = threading.Lock()
        self.unusable_mark = (0.0, 0)   # when settings_unusable was last written, and how often it came up since

    def db(self):
        """One cad-db connection per thread."""
        if not hasattr(self.local, "conn"):
            self.local.conn = cadstore.connect(self.data_dir, busy_timeout_ms=self.BUSY_MS)
        return self.local.conn

    def write_error(self):
        self.write_errors.add(0.0, "error")

    def settings(self):
        values, _ = self.config.values()
        return check_settings(values, self.SETTINGS)

    def wait(self, seconds):
        """Sleep in 0.25 s slices; return early when the settings change from the ones the cycle ran with (read
        before it), so a change made during a cycle also cuts short the sleep its old poll_interval_s set."""
        version = self.cycle_version
        if version is None:
            _, version = self.config.values()
        end = time.time() + seconds
        while True:
            left = end - time.time()
            if left <= 0:
                return
            time.sleep(min(0.25, left))
            if self.config.values()[1] != version:
                return

    def background(self):
        self.run_loop()

    def run_loop(self):
        while True:
            self.server.gate.wait()
            self.cycle_version = self.config.values()[1]   # read first: a change after it ends the next wait
            settings, bad_key = self.settings()
            if settings is None:
                self.log_unusable(bad_key)
                self.wait(0.25)
                continue
            conn = self.db()
            try:
                self.cycle(conn, settings)
            except sqlite3.DatabaseError as exc:
                self.database_error(conn, exc)
            self.wait(settings["poll_interval_s"])

    def log_unusable(self, bad_key):
        """One ERROR line every 2 s naming the setting, never its value. Not log_every: its own first parameter
        is called key, the field this line must carry."""
        now = time.time()
        with self.unusable_lock:
            last_t, count = self.unusable_mark
            if now - last_t < 2.0:
                self.unusable_mark = (last_t, count + 1)
                return
            self.unusable_mark = (now, 0)
        self.log.error("settings_unusable", f"setting {bad_key} cannot be used; work is paused until it changes",
                       occurrences=count + 1, key=bad_key)

    def database_error(self, conn, exc):
        """A busy or failing database: roll back, count a write error, log, and let the next cycle try again."""
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        self.write_error()
        if is_busy(exc):
            self.log_every("db_busy", 2.0, "WARN", "db_busy", "cad-db is busy; this cycle ended without writing",
                           operation=self.OPERATION)
        else:
            self.log_every("db_error", 2.0, "ERROR", "db_error",
                           f"cad-db could not be used ({type(exc).__name__})", operation=self.OPERATION)

    def cycle(self, conn, settings):
        raise NotImplementedError

    def extra_metrics(self, window_s):
        return {"db_write_errors": self.write_errors.summary(window_s)["n"]}
