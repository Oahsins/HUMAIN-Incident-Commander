"""Small JSON-over-HTTP helpers built on the standard library.

Every service in a test system is a plain Python web server. This file holds the
two halves: a server that routes requests to Python functions, and a client that
calls other services with a timeout.
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


class CallError(Exception):
    """A call to another service failed. `kind` is timeout, refused, http or bad_response."""

    def __init__(self, kind, status=None, body=None, detail=""):
        super().__init__(f"{kind} {status or ''} {detail}".strip())
        self.kind = kind
        self.status = status
        self.body = body or {}
        self.detail = detail


def call(method, url, payload=None, timeout=2.0, headers=None):
    """Call a JSON endpoint. Returns (status, body). Raises CallError on failure.

    4xx and 5xx answers raise CallError(kind="http") with the status and body,
    so callers can tell a rejection from a crash.
    """
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method,
                      headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
    except HTTPError as exc:
        try:
            body = json.loads(exc.read() or b"{}")
        except ValueError:
            body = {}
        raise CallError("http", exc.code, body, body.get("error", "")) from None
    except (socket.timeout, TimeoutError):
        raise CallError("timeout", detail=f"no answer within {timeout}s") from None
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise CallError("timeout", detail=f"no answer within {timeout}s") from None
        raise CallError("refused", detail=str(reason)) from None
    except (ConnectionError, OSError) as exc:
        raise CallError("refused", detail=str(exc)) from None
    except ValueError:
        raise CallError("bad_response", detail="answer was not JSON") from None


def get(url, timeout=2.0, headers=None):
    return call("GET", url, None, timeout, headers)


def post(url, payload=None, timeout=2.0, headers=None):
    return call("POST", url, payload or {}, timeout, headers)


class Reply(Exception):
    """Raise inside a route to answer with a status other than 200."""

    def __init__(self, status, body):
        super().__init__(status)
        self.status = status
        self.body = body


class JsonServer(ThreadingHTTPServer):
    """A threaded HTTP server whose routes are Python functions.

    routes maps ("GET", "/path") to fn(request) -> dict. A path ending in "/*"
    matches any suffix, which the function reads from request["tail"].
    on_request(method, path, status, ms) is called after each request, which is
    how services measure their own latency and error rates.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, routes, on_request=None, host="127.0.0.1"):
        self.routes = routes
        self.on_request = on_request
        self.gate = threading.Event()  # cleared = the service is hung (an injected fault)
        self.gate.set()
        super().__init__((host, port), _Handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the console quiet; services write JSON logs instead
        pass

    def _route(self, method, path):
        routes = self.server.routes
        if (method, path) in routes:
            return routes[(method, path)], ""
        for (m, p), fn in routes.items():
            if m == method and p.endswith("/*") and path.startswith(p[:-1]):
                return fn, path[len(p) - 1:]
        return None, ""

    def _serve(self, method):
        started = time.perf_counter()
        parsed = urlparse(self.path)
        status, body = 500, {"error": "internal error"}
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            payload = json.loads(raw) if raw else {}
            fn, tail = self._route(method, parsed.path)
            if fn is None:
                status, body = 404, {"error": "no such endpoint"}
            else:
                # A hung service stops answering everything, health checks included.
                # Only the token-protected admin hooks stay reachable.
                if not parsed.path.startswith("/admin"):
                    self.server.gate.wait()
                request = {"method": method, "path": parsed.path, "tail": tail,
                           "query": {k: v[-1] for k, v in parse_qs(parsed.query).items()},
                           "body": payload, "headers": dict(self.headers)}
                status, body = 200, fn(request)
        except Reply as reply:
            status, body = reply.status, reply.body
        except ValueError:
            status, body = 400, {"error": "request was not valid JSON"}
        except Exception as exc:  # a real bug in a release: answer 500 and let the service log it
            status, body = 500, {"error": f"{type(exc).__name__}: {exc}"}
            handler = getattr(self.server, "on_exception", None)
            if handler:
                handler(exc, parsed.path)
        data = json.dumps(body).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        if self.server.on_request:
            self.server.on_request(method, parsed.path, status, (time.perf_counter() - started) * 1000)

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")


def port_free(port, host="127.0.0.1"):
    """True when nothing is listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0
