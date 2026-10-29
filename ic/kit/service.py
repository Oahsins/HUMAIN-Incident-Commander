"""The base every service in a test system builds on.

A service is one OS process: a small web server with /health and /metrics, a
JSON log file, versioned settings it re-reads while running, and rolling
statistics for the requests it serves and the dependencies it calls.

A release of a service is a Python class. Release 1.4 of payments, say, is a
subclass of release 1.3 that changes one method. Deploying a release restarts
the process with that class; rolling back restarts it with the previous one.
"""

import os
import threading
import time
import traceback
from collections import defaultdict

from . import net
from .logs import Logger
from .stats import Window
from .store import CachedConfig, CachedRouting

INTERNAL_PATHS = ("/health", "/metrics", "/admin")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ServiceBase:
    """Subclass this, set COMPONENT, add routes() and optionally background()."""

    COMPONENT = None
    VERSION = None

    def __init__(self, ctx):
        self.ctx = ctx
        self.component = ctx["component"]
        self.version = ctx["version"]
        self.port = ctx["port"]
        self.data_dir = ctx["data_dir"]
        self.ports = ctx.get("ports", {})
        self.config = CachedConfig(self.data_dir, self.component)
        self.routing = CachedRouting(self.data_dir)
        self.log = Logger(self.component, os.path.join(self.data_dir, "logs", f"{self.component}.jsonl"))
        self.stats = Window()
        self.deps = defaultdict(Window)
        self.started_t = time.time()
        self.server = None
        self._log_lock = threading.Lock()
        self._log_marks = {}

    # ----- things a release overrides -----

    def routes(self):
        """Extra endpoints: {("GET", "/path"): fn(request) -> dict}."""
        return {}

    def background(self):
        """Optional work loop for workers. Runs in its own thread; return to stop."""
        return None

    def extra_metrics(self, window_s):
        """Component-specific signals for /metrics (queue depth and so on)."""
        return {}

    # ----- shared behaviour -----

    def setting(self, key, default=None):
        values, _ = self.config.values()
        return values.get(key, default)

    def url(self, component, path):
        return f"http://127.0.0.1:{self.ports[component]}{path}"

    def call(self, dep, method, url, payload=None, timeout=2.0):
        """Call a dependency and record the outcome as this service saw it."""
        started = time.perf_counter()
        try:
            status, body = net.call(method, url, payload, timeout)
            self.deps[dep].add((time.perf_counter() - started) * 1000, "ok")
            return status, body
        except net.CallError as exc:
            outcome = "reject" if exc.kind == "http" and exc.status and exc.status < 500 else "error"
            self.deps[dep].add((time.perf_counter() - started) * 1000, outcome)
            raise

    def log_every(self, key, interval_s, level, event, msg, **fields):
        """Log a repeating problem at most once per interval, with a count of how often it happened."""
        now = time.time()
        with self._log_lock:
            last_t, count = self._log_marks.get(key, (0.0, 0))
            count += 1
            if now - last_t < interval_s:
                self._log_marks[key] = (last_t, count)
                return
            self._log_marks[key] = (now, 0)
        self.log.write(level, event, msg, occurrences=count, **fields)

    def short_traceback(self):
        """The traceback with file paths relative to the code and data folders, as an operator would see it."""
        text = traceback.format_exc(limit=6)
        for prefix in (self.data_dir + os.sep, ROOT + os.sep):
            text = text.replace(prefix, "")
        return text

    def crash(self, exc, **fields):
        """A worker hit something it cannot handle: log the traceback and exit like a real crash."""
        self.log.error("crash", f"{type(exc).__name__}: {exc}", traceback=self.short_traceback(), **fields)
        os._exit(1)

    def _health(self, request):
        return {"ok": True, "component": self.component, "release": self.version}

    def _metrics(self, request):
        window = float(request["query"].get("window", 10))
        _, config_version = self.config.values()
        return {"component": self.component, "release": self.version, "config_version": config_version,
                "uptime_s": round(time.time() - self.started_t, 1), "pid": os.getpid(),
                **self.stats.summary(window),
                "dependencies": {name: w.summary(window) for name, w in self.deps.items()},
                "extra": self.extra_metrics(window)}

    def _check_admin(self, request):
        token = self.ctx.get("admin_token")
        if not token or request["headers"].get("X-Admin-Token") != token:
            raise net.Reply(403, {"error": "admin token required"})

    def _hang(self, request):
        """Admin hook: stop answering requests, as a hung process would."""
        self._check_admin(request)
        self.server.gate.clear()
        return {"ok": True, "hung": True}

    def _on_request(self, method, path, status, ms):
        if path.startswith(INTERNAL_PATHS):
            return
        outcome = "ok" if status < 400 else ("reject" if status < 500 else "error")
        self.stats.add(ms, outcome)

    def _on_exception(self, exc, path):
        self.log_every(f"exc:{type(exc).__name__}:{path}", 2.0, "ERROR", "unhandled_exception",
                       f"{type(exc).__name__}: {exc}", path=path, traceback=self.short_traceback())

    def serve(self):
        routes = {("GET", "/health"): self._health, ("GET", "/metrics"): self._metrics,
                  ("POST", "/admin/hang"): self._hang, **self.routes()}
        self.server = net.JsonServer(self.port, routes, on_request=self._on_request)
        self.server.on_exception = self._on_exception
        self.log.info("start", f"{self.component} {self.version} listening on {self.port}", release=self.version)
        worker = threading.Thread(target=self._run_background, daemon=True)
        worker.start()
        try:
            self.server.serve_forever(poll_interval=0.2)
        finally:
            self.server.server_close()

    def _run_background(self):
        try:
            self.background()
        except Exception as exc:  # an uncaught error in a worker loop crashes the whole process
            self.crash(exc)
