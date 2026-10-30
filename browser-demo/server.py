"""The browser customer's bank app: serves page.html and forwards its calls to the real gateway.

Demo only, not evidence. One customer, web-01, pays from the existing account
cust-20. After every payment attempt it appends one line to the copy's
customers.jsonl in the simulated customers' own format (targets/bank/customers.py),
so the independent checker counts the browser customer like any other. Without
that line, a posted browser payment would read as a ghost payment.

Responses map the way customers.py maps them: 2xx is ok, 4xx is rejected,
5xx or a timeout is failed.

    python browser-demo/server.py --port-base 27800

Also serves /stage (the page beside the live terminal, for filming) and
/terminal (a view of the demo's terminal log), both outside what the customer sees.
"""

import argparse
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CUSTOMER = "web-01"
ACCOUNT = "cust-20"   # an existing customer account; never probe-01, never a probe- id
ATTEMPT_TIMEOUT_S = 3.0   # as customers.py
PAGES = {"/": "page.html", "/stage": "stage.html", "/terminal": "terminal.html"}


class App:
    def __init__(self, port_base, data_dir, terminal_log):
        self.gateway = f"http://127.0.0.1:{port_base}"
        self.customers_log = os.path.join(data_dir, "customers.jsonl")
        self.journal = os.path.join(data_dir, "web-01-journal.jsonl")   # for report.py; the checker never reads it
        self.terminal_log = terminal_log
        self.lock = threading.Lock()
        self.seq = 0

    def append(self, path, record):
        with self.lock:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")

    def call(self, method, path, payload=None):
        """(status, body) from the gateway; status is 'timeout' or 'refused' when there was no answer."""
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.gateway + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=ATTEMPT_TIMEOUT_S) as response:
                return response.status, json.loads(response.read() or b"{}")
        except HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {}
        except (socket.timeout, TimeoutError):
            return "timeout", {"error": f"no answer within {ATTEMPT_TIMEOUT_S:.0f} s"}
        except URLError as exc:
            if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                return "timeout", {"error": f"no answer within {ATTEMPT_TIMEOUT_S:.0f} s"}
            return "refused", {"error": "the bank did not answer"}
        except (ConnectionError, OSError):
            return "refused", {"error": "the bank did not answer"}

    def pay(self, body):
        amount = int(body["amount_minor"])
        e2e = body.get("end_to_end_id")
        if not e2e:   # a new payment; Retry sends the same id again
            with self.lock:
                self.seq += 1
                e2e = f"{CUSTOMER}-{self.seq:06d}"
        if not e2e.startswith(CUSTOMER + "-"):
            return 400, {"error": "unknown payment"}
        payment = {"from_acct": ACCOUNT, "amount_minor": amount, "currency": "SAR", "beneficiary_bank": "BANK-B",
                   "beneficiary_acct": "ben-400", "end_to_end_id": e2e}
        t0 = time.time()
        status, answer = self.call("POST", "/pay", payment)
        t1 = time.time()
        if isinstance(status, int) and status < 400:
            outcome = "ok"
        elif isinstance(status, int) and status < 500:
            outcome = "rejected"
        else:
            outcome = "failed"
        self.append(self.customers_log, {
            "kind": "payment", "t_start": round(t0, 3), "t_end": round(t1, 3), "customer": CUSTOMER,
            "end_to_end_id": e2e, "amount_minor": amount, "outcome": outcome, "status": status,
            "payment_id": answer.get("payment_id"), "attempts": 1})
        self.append(self.journal, {"t_start": t0, "t_end": t1, "end_to_end_id": e2e, "amount_minor": amount,
                                   "outcome": outcome, "status": status, "answer": answer, "retry": bool(body.get("end_to_end_id"))})
        return 200, {"end_to_end_id": e2e, "outcome": outcome, "http": status, "answer": answer,
                     "ms": round((t1 - t0) * 1000)}

    def terminal(self):
        try:
            with open(self.terminal_log, encoding="utf-8", errors="replace") as handle:
                return 200, {"text": handle.read()[-60_000:]}
        except OSError:
            return 200, {"text": ""}


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, kind="application/json"):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def relay(self, status, body):
            # the page always gets the gateway's own status code and body
            self.send(status if isinstance(status, int) else 504, {**body, "http": status})

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in PAGES:
                with open(os.path.join(HERE, PAGES[path]), "rb") as handle:
                    return self.send(200, handle.read(), "text/html; charset=utf-8")
            if path == "/api/balance":
                return self.relay(*app.call("GET", f"/balance/{ACCOUNT}"))
            if path.startswith("/api/payment/"):
                return self.relay(*app.call("GET", "/payment/" + path.rsplit("/", 1)[1]))
            if path == "/api/terminal":
                return self.send(*app.terminal())
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/pay":
                return self.send(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                int(body["amount_minor"])
            except (ValueError, KeyError, TypeError):
                return self.send(400, {"error": "bad request"})
            self.send(*app.pay(body))

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port-base", type=int, default=27800, help="the bank copy's port base (gateway = +0)")
    parser.add_argument("--port", type=int, default=None, help="this server's port (default port base + 30)")
    parser.add_argument("--data", default=None, help="the copy's folder (default runs/bank-<port base>)")
    parser.add_argument("--terminal-log", default="", help="the demo's terminal log, shown on /terminal")
    args = parser.parse_args()
    data = args.data or os.path.join(ROOT, "runs", f"bank-{args.port_base}")
    port = args.port or args.port_base + 30
    app = App(args.port_base, data, args.terminal_log)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(app))
    print(f"browser customer {CUSTOMER} ({ACCOUNT}) on http://127.0.0.1:{port}/ -> gateway {app.gateway}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
