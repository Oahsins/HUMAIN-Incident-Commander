"""A local web console for trying the frozen incident commander from a browser.

    python console/app.py            # then open http://127.0.0.1:8088

Pick a practice case and a mode, press Run, and watch the agent's steps arrive live.
Or tick several cases and run them one after another with a scoreboard, or run the
repository's own test suite. The console only drives run.py (up, inject, agent, check,
down, or demo) and pytest, the same commands as the README, so it adds no agent
behaviour of its own. One run at a time.

A model key typed into the page goes only into that run's environment. It is never
written to disk or logged. Without a key, only the two-fault demo runs (as a replay).
Standard library only.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CASES_FILE = os.path.join(ROOT, "scenarios", "dev", "dev.jsonl")
KEY_VAR = "ANTHROPIC_API_KEY"
MODES = ("auto", "confirm", "advise")
SET_MODES = ("auto", "advise")   # confirm asks before every action, so it runs one case at a time
KEY_VARS = (KEY_VAR, "IC_ANTHROPIC_API_KEY")
ALERT_DELAY_S = 5      # the same delay as `run.py demo` between the faults and the alert
CHECK_WAIT_S = 31      # the checker's 20 s window ends 10 s before the verdict, plus 1 s


def load_cases():
    cases = []
    with open(CASES_FILE, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            case = json.loads(line)
            target = case["target"]
            cases.append({
                "id": case["id"],
                "faults": [{"type": f["type"], "params": f["params"]} for f in case["input"]["faults"]
                           if f["type"] != "benign"],
                "decoys": sum(1 for f in case["input"]["faults"] if f["type"] == "benign"),
                "notes": target.get("notes", ""),
                "healthy": target.get("healthy", False),
                "escalate": target.get("must_escalate", False),
                "fixes": [{"cls": r["class"], "target": r["target"], "action": r["fix"]["action"]}
                          for r in target.get("root_causes", [])],
            })
    return cases


class Job:
    """One run: a list of run.py commands, their output as lines, and a pending yes/no question."""

    def __init__(self, steps, env, label, port_base, meta=None):
        self.steps, self.env, self.label, self.port_base = steps, env, label, port_base
        self.meta = meta or {"kind": "one"}
        self.lines = []
        self.state = "running"
        self.prompt = None
        self.proc = None
        self.stopped = False
        self.lock = threading.Lock()
        self.t0 = time.time()
        threading.Thread(target=self._run, daemon=True).start()

    def emit(self, text, kind="out"):
        with self.lock:
            self.lines.append({"t": round(time.time() - self.t0, 2), "kind": kind, "text": text})

    def _run(self):
        try:
            for step in self.steps:
                if self.stopped:
                    break
                if step[0] == "say":
                    self.emit(step[1], "note")
                elif step[0] == "case":
                    self.emit(step[1], "case")
                elif step[0] == "py":
                    self._command(step[1], script=False)
                elif step[0] == "wait":
                    self.emit(step[2], "note")
                    end = time.time() + step[1]
                    while time.time() < end and not self.stopped:
                        time.sleep(0.2)
                else:
                    code = self._command(step[1], quiet=step[0] == "quiet")
                    if code != 0 and step[1][0] in ("up", "inject"):
                        self.emit(f"`run.py {step[1][0]}` failed, so the run stops here", "error")
                        self.stopped = True
            if self.stopped:
                failed = any(line["kind"] == "error" for line in self.lines)
                self.stopped = False
                self._command(["down", "--port-base", str(self.port_base)], quiet=True)
                self.emit("stopped; the test bank is shut down", "note")
                self.state = "error" if failed else "stopped"
            else:
                self.state = "done"
        except Exception as exc:  # report, never crash the server
            self.emit(f"console error: {exc}", "error")
            self.state = "error"
        finally:
            self.prompt = None
            self.env = None   # drop the key as soon as the run ends

    def _command(self, args, quiet=False, script=True):
        cmd = [sys.executable, "-u"] + ([os.path.join(ROOT, "run.py")] if script else []) + args
        if not quiet:
            self.emit("$ python " + ("run.py " if script else "") + " ".join(args), "cmd")
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
        buf = b""
        while True:
            chunk = os.read(self.proc.stdout.fileno(), 4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not quiet:
                    self.emit(line.decode("utf-8", "replace").rstrip("\r"))
            text = buf.decode("utf-8", "replace")
            if text.rstrip().endswith("[y/N]"):     # confirm mode asks before each action
                self.emit(text.strip(), "ask")
                self.prompt = text.strip()
                buf = b""
        if buf and not quiet:
            self.emit(buf.decode("utf-8", "replace"))
        code = self.proc.wait()
        if not quiet:
            self.emit(f"exit {code}", "exit")
        self.proc = None
        return code

    def answer(self, yes):
        if self.proc and self.prompt:
            self.prompt = None
            self.emit("you answered: " + ("yes" if yes else "no"), "note")
            self.proc.stdin.write(b"y\n" if yes else b"n\n")
            self.proc.stdin.flush()

    def stop(self):
        self.stopped = True
        if self.proc:
            self.proc.terminate()


def plan(case_id, mode, port_base):
    pb = ["--port-base", str(port_base)]
    if case_id == "demo":
        return [("run", ["demo", *pb, "--mode", mode])]
    return [
        ("quiet", ["down", *pb]),
        ("run", ["up", *pb]),
        ("run", ["inject", *pb, "--scenario", "scenarios/dev/dev.jsonl", "--id", case_id]),
        ("wait", ALERT_DELAY_S, f"the alert fires in {ALERT_DELAY_S} s; nobody tells the agent what broke"),
        ("run", ["agent", *pb, "--mode", mode]),
        ("wait", CHECK_WAIT_S, f"waiting {CHECK_WAIT_S} s for a clean checker window (every customer retry finished)"),
        ("run", ["check", *pb]),
        ("run", ["down", *pb]),
    ]


def plan_set(case_ids, mode, port_base):
    """Several practice cases, one after another, each on a fresh bank."""
    steps = []
    for i, case_id in enumerate(case_ids):
        steps.append(("case", f"{case_id} ({i + 1} of {len(case_ids)})"))
        steps += plan(case_id, mode, port_base)
    return steps


def plan_selftest():
    return [("say", "the repository's own test suite, as CI runs it (about a minute); no model calls"),
            ("py", ["-m", "pytest", "-q", "-p", "no:cacheprovider"])]


class Handler(BaseHTTPRequestHandler):
    server_version = "IncidentConsole/1"

    def log_message(self, *args):   # keep the terminal quiet; requests may carry a key
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def do_GET(self):
        app = self.server.app
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as handle:
                return self._send(200, handle.read(), "text/html; charset=utf-8")
        if self.path == "/api/info":
            return self._send(200, {"cases": app["cases"], "key_in_env": bool(os.environ.get(KEY_VAR)),
                                    "modes": MODES})
        if self.path.startswith("/api/events"):
            job = app["job"]
            since = 0
            if "since=" in self.path:
                try:
                    since = int(self.path.split("since=", 1)[1].split("&")[0])
                except ValueError:
                    since = 0
            if not job:
                return self._send(200, {"lines": [], "state": "idle", "prompt": None, "next": 0})
            with job.lock:
                lines = job.lines[since:]
                nxt = len(job.lines)
            return self._send(200, {"lines": lines, "state": job.state, "prompt": job.prompt, "next": nxt,
                                    "label": job.label, "meta": job.meta})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        app = self.server.app
        try:
            body = self._body()
        except ValueError:
            return self._send(400, {"error": "bad request"})
        if self.path == "/api/run":
            job = app["job"]
            if job and job.state == "running":
                return self._send(409, {"error": "a run is already going; stop it first"})
            env = dict(os.environ, COLUMNS="400", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            env.pop("IC_RECORD", None)
            if body.get("selftest"):
                for var in KEY_VARS:      # the tests never need a model, so they never get a key
                    env.pop(var, None)
                app["job"] = Job(plan_selftest(), env, "self-test", app["port_base"], {"kind": "selftest"})
                return self._send(200, {"ok": True})
            mode = body.get("mode") or "auto"
            if mode not in MODES:
                return self._send(400, {"error": "unknown mode"})
            known = {c["id"] for c in app["cases"]}
            many = body.get("cases")
            if many is not None:
                if not isinstance(many, list) or not many or len(set(map(str, many))) != len(many):
                    return self._send(400, {"error": "pick one or more different practice cases"})
                many = [str(c) for c in many]
                if any(c not in known for c in many):
                    return self._send(400, {"error": "unknown case"})
                if mode not in SET_MODES:
                    return self._send(400, {"error": "Confirm mode asks before every action, so it runs one "
                                                     "case at a time. Pick auto or advise for a set."})
            case_id = str(body.get("case") or "demo")
            if many is None and case_id != "demo" and case_id not in known:
                return self._send(400, {"error": "unknown case"})
            key = (body.get("key") or "").strip()
            if key:
                env[KEY_VAR] = key
            if not env.get(KEY_VAR):
                if many is not None:
                    return self._send(400, {"error": "A set of practice cases needs a model key: every case "
                                                     "after the demo calls the model."})
                if case_id != "demo":
                    return self._send(400, {"error": "This case needs a model key. Paste one, or run the demo, "
                                                     "which replays a recorded run without a key."})
                if mode == "advise":
                    return self._send(400, {"error": "Advise mode needs a model key: the recorded replay comes "
                                                     "from a run that acted, so its handover would not fit."})
            if many is not None:
                app["job"] = Job(plan_set(many, mode, app["port_base"]), env,
                                 f"a set of {len(many)} cases, mode {mode}", app["port_base"],
                                 {"kind": "set", "cases": many, "mode": mode})
                return self._send(200, {"ok": True})
            label = ("the two-fault demo" if case_id == "demo" else case_id) + f", mode {mode}"
            app["job"] = Job(plan(case_id, mode, app["port_base"]), env, label, app["port_base"],
                             {"kind": "one", "case": case_id, "mode": mode})
            return self._send(200, {"ok": True})
        if self.path == "/api/answer":
            job = app["job"]
            if job:
                job.answer(bool(body.get("yes")))
            return self._send(200, {"ok": True})
        if self.path == "/api/stop":
            job = app["job"]
            if job:
                job.stop()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088, help="the console's own port")
    parser.add_argument("--port-base", type=int, default=27400, help="first of the test bank's 10 ports")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.app = {"cases": load_cases(), "job": None, "port_base": args.port_base}
    print(f"Incident console: http://{args.host}:{args.port}  (bank ports {args.port_base}-{args.port_base + 9}; "
          f"Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        job = server.app["job"]
        if job and job.state == "running":
            job.stop()
        subprocess.run([sys.executable, os.path.join(ROOT, "run.py"), "down", "--port-base", str(args.port_base)],
                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
