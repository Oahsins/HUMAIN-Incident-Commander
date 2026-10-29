"""The control plane for one running copy of a test system.

It starts every process, watches them, keeps the change log, and serves two
APIs on one port:

- /ops/...      what the agent's adapter may use: describe, observe, logs, probe, act.
                Only the six allowlisted actions exist here.
- /control/...  privileged operations for the fault injector, the checker and
                the evaluation harness. Every call needs the control token,
                which is written to the copy's data folder and never given to
                the agent.

The system-specific parts (which components exist, what a journey is, how a
generic action maps onto this system) come from a SystemSpec.
"""

import argparse
import importlib
import json
import os
import secrets
import shutil
import sys
import threading
import time

from . import net, proc
from .logs import read as read_logs
from .store import ChangeLog, ConfigStore, Releases, Routing, read_json, write_json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT) if ROOT not in sys.path else None
from ic.contract import ACTIONS  # noqa: E402  (the six allowlisted actions)

AGENT_ACTOR = "incident-commander"


class ManagedProcess:
    def __init__(self, name):
        self.name = name
        self.popen = None
        self.started_t = None
        self.restarts = 0
        self.exits = []          # [(t, exit_code)]
        self.expected_down = False


class Supervisor:
    def __init__(self, spec, port_base, data_dir, seed=0, condition="default"):
        self.spec = spec
        self.port_base = port_base
        self.data_dir = os.path.abspath(data_dir)
        self.seed = seed
        self.condition = condition
        self.lock = threading.RLock()
        self.procs = {}
        self.jobs = {}
        self.changes = ChangeLog(self.data_dir)
        self.releases = Releases(self.data_dir)
        self.control_token = secrets.token_hex(16)
        self.admin_token = secrets.token_hex(16)
        self.baseline = {}
        self.stopping = False
        self.ports = {c["name"]: port_base + c["port_offset"] for c in spec.components(condition)
                      if c.get("port_offset") is not None}
        self.ports["supervisor"] = port_base + 9
        self.links = {name: {"listen": port_base + r["listen_offset"], "upstream": self.ports[r["upstream"]],
                             "latency_ms": 0, "jitter_ms": 0, "drop_pct": 0.0}
                      for name, r in spec.links().items()}
        for name, link in self.links.items():   # services reach a linked dependency through its relay port
            self.ports[name] = link["listen"]
        self.env = {"IC_ADMIN_TOKEN": self.admin_token, "PYTHONPATH": ROOT,
                    "IC_LOG_FORMAT": "v2" if condition == "log_format_v2" else "v1",
                    "PYTHONUNBUFFERED": "1"}

    # ----- set-up -----

    def prepare(self):
        os.makedirs(os.path.join(self.data_dir, "logs"), exist_ok=True)
        write_json(os.path.join(self.data_dir, "ports.json"), {"ports": self.ports, "port_base": self.port_base})
        write_json(os.path.join(self.data_dir, "links.json"), {"routes": self.links})
        with open(os.path.join(self.data_dir, "control.token"), "w", encoding="utf-8") as handle:
            handle.write(self.control_token)
        components = self.spec.components(self.condition)
        self.releases.init({c["name"]: c["version"] for c in components if c.get("version")})
        for c in components:
            if c.get("config") is not None:
                ConfigStore(self.data_dir, c["name"]).init(c["config"])
        self.spec.init_data(self)

    def start_all(self):
        self.jobs["linkproxy"] = proc.spawn(proc.python_argv("ic.kit.linkproxy", "--config",
                                            os.path.join(self.data_dir, "links.json")),
                                            os.path.join(self.data_dir, "logs", "linkproxy.out"), self.env, cwd=ROOT)
        for c in self.spec.start_order(self.condition):
            self.start(c, log_change=False)
        for c in self.spec.start_order(self.condition):
            if not self.wait_healthy(c, 10):
                raise RuntimeError(f"{c} did not become healthy")
        argv = self.spec.traffic_argv(self)
        if argv:
            self.jobs["traffic"] = proc.spawn(argv, os.path.join(self.data_dir, "logs", "traffic.out"),
                                              self.env, cwd=ROOT)

    # ----- process operations -----

    def component(self, name):
        for c in self.spec.components(self.condition):
            if c["name"] == name:
                return c
        return None

    def start(self, name, actor="system", log_change=True):
        with self.lock:
            mp = self.procs.setdefault(name, ManagedProcess(name))
            if mp.popen and mp.popen.poll() is None:
                return False
            version = self.releases.current(name)
            image = (self.component(name) or {}).get("image", name)
            argv = proc.python_argv("ic.kit.run_service", "--system", self.spec.system, "--component", name,
                                    "--image", image, "--version", version, "--data", self.data_dir)
            mp.popen = proc.spawn(argv, os.path.join(self.data_dir, "logs", f"{name}.out"), self.env, cwd=ROOT)
            mp.started_t = time.time()
            mp.expected_down = False
            if log_change:
                self.changes.add(name, "start", actor, release=version)
            return True

    def stop(self, name, actor="system", log_change=True):
        with self.lock:
            mp = self.procs.get(name)
            if not mp or not mp.popen or mp.popen.poll() is not None:
                return False
            mp.expected_down = True
            proc.kill(mp.popen.pid)
            mp.popen.wait(timeout=5)
            if log_change:
                self.changes.add(name, "stop", actor)
            return True

    def kill(self, name):
        """A crash: the process dies without anyone recording a change."""
        with self.lock:
            mp = self.procs.get(name)
            if not mp or not mp.popen or mp.popen.poll() is not None:
                return False
            proc.kill(mp.popen.pid)
            return True

    def restart(self, name, actor):
        with self.lock:
            self.stop(name, actor, log_change=False)
            self.start(name, actor, log_change=False)
            self.procs[name].restarts += 1
            self.changes.add(name, "restart", actor, release=self.releases.current(name))
        return self.wait_healthy(name, 6)

    def deploy(self, name, version, module_path=None, actor="pipeline"):
        if module_path:
            copy = os.path.join(self.data_dir, "releases", name, "v" + version.replace(".", "_") + ".py")
            os.makedirs(os.path.dirname(copy), exist_ok=True)
            shutil.copyfile(module_path, copy)
            module_path = copy
        with self.lock:
            old = self.releases.deploy(name, version, module_path)
            self.stop(name, actor, log_change=False)
            self.start(name, actor, log_change=False)
            self.changes.add(name, "deploy", actor, **{"from": old, "to": version})
        return self.wait_healthy(name, 6)

    def rollback(self, name, actor):
        with self.lock:
            moved = self.releases.rollback(name)
            if not moved:
                return False, "no earlier release to return to"
            self.stop(name, actor, log_change=False)
            self.start(name, actor, log_change=False)
            self.changes.add(name, "deploy", actor, **{"from": moved[0], "to": moved[1], "rollback": True})
        return self.wait_healthy(name, 6), f"{name} {moved[0]} -> {moved[1]}"

    def set_config(self, name, key, value, actor="operator"):
        store = ConfigStore(self.data_dir, name)
        before = store.load()["values"].get(key)
        store.set(key, value, actor)
        self.changes.add(name, "config", actor, key=key, **{"from": before, "to": value})

    def revert_config(self, name, actor, key=None):
        """Undo one setting change: the newest change to `key`, or the newest one the agent did not make."""
        undone = ConfigStore(self.data_dir, name).revert(actor, key=key, skip_actor=AGENT_ACTOR)
        if not undone:
            return False, f"no setting change to undo on {name}" + (f" for {key}" if key else "")
        self.changes.add(name, "config", actor, key=undone["key"], revert=True,
                         **{"from": undone["from"], "to": undone["to"]})
        return True, (f"{name} {undone['key']} restored from {undone['from']} to {undone['to']} "
                      f"(changed earlier by {undone['changed_by']})")

    def set_link(self, route, latency_ms=0, jitter_ms=0, drop_pct=0.0):
        with self.lock:
            self.links[route].update(latency_ms=latency_ms, jitter_ms=jitter_ms, drop_pct=drop_pct)
            write_json(os.path.join(self.data_dir, "links.json"), {"routes": self.links})

    def spawn_job(self, name, argv):
        with self.lock:
            full = [sys.executable if a == "{python}" else a.replace("{data}", self.data_dir) for a in argv]
            running = self.jobs.get(name)
            if running is not None and running.poll() is None:   # keep tracking an earlier run of the same job
                self.jobs[f"{name}#{running.pid}"] = running
            self.jobs[name] = proc.spawn(full, os.path.join(self.data_dir, "logs", f"{name}.out"), self.env, cwd=ROOT)
            return self.jobs[name].pid

    def jobs_named(self, name):
        """Running helper processes started under this job name."""
        return [job for key, job in self.jobs.items() if key.split("#")[0] == name and job.poll() is None]

    def wait_healthy(self, name, timeout_s):
        port = self.ports.get(name)
        if port is None:
            return True

        def check():
            try:
                net.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
                return True
            except net.CallError:
                mp = self.procs.get(name)
                if mp and mp.popen and mp.popen.poll() is not None:
                    return "dead"
                return False
        return proc.wait_until(check, timeout_s, 0.1) is True

    def is_up(self, name):
        mp = self.procs.get(name)
        return bool(mp and mp.popen and mp.popen.poll() is None)

    def monitor(self):
        """Notice processes that exit by themselves (crashes) and remember when and how."""
        while not self.stopping:
            with self.lock:
                for mp in self.procs.values():
                    if mp.popen and mp.popen.poll() is not None and not mp.expected_down:
                        mp.exits.append((time.time(), mp.popen.returncode))
                        mp.expected_down = True  # recorded once; stays down until someone starts it
            time.sleep(0.25)

    # ----- what the agent may see (ops) -----

    def metrics_of(self, name, window_s):
        port = self.ports.get(name)
        if port is None or not self.is_up(name):
            return None
        try:
            return net.get(f"http://127.0.0.1:{port}/metrics?window={window_s}", timeout=1.0)[1]
        except net.CallError:
            return None

    def observe(self, window_s=10.0):
        out = {}
        for c in self.spec.components(self.condition):
            name = c["name"]
            mp = self.procs.get(name)
            m = self.metrics_of(name, window_s) if c.get("port_offset") is not None else None
            usage = proc.usage(mp.popen.pid) if mp and mp.popen and mp.popen.poll() is None else {}
            recent_exits = [e for e in (mp.exits if mp else []) if e[0] > time.time() - 900]
            entry = {"up": m is not None if c.get("port_offset") is not None else None,
                     "p95_ms": m.get("p95_ms") if m else None,
                     "error_rate": m.get("error_rate") if m else None,
                     "reject_rate": m.get("reject_rate") if m else None,
                     "rps": m.get("rps") if m else None,
                     "cpu_pct": usage.get("cpu_pct"), "mem_mb": usage.get("mem_mb"),
                     "restarts": mp.restarts if mp else 0,
                     "release": self.releases.current(name),
                     "config_version": m.get("config_version") if m else None,
                     "extra": {}}
            if m and m.get("dependencies"):
                entry["extra"]["dependencies"] = m["dependencies"]
            if m and m.get("extra"):
                entry["extra"].update(m["extra"])
            if recent_exits:
                entry["extra"]["exits_15m"] = len(recent_exits)
                entry["extra"]["last_exit_s_ago"] = round(time.time() - recent_exits[-1][0], 1)
                entry["extra"]["last_exit_code"] = recent_exits[-1][1]
            if mp and mp.popen and mp.popen.poll() is None and m is None and c.get("port_offset") is not None:
                entry["extra"]["not_answering"] = True
            if c.get("standby"):
                entry["extra"]["active"] = Routing(self.data_dir).active(name)
            out[name] = entry
        for c in self.spec.components(self.condition):
            if c["kind"] == "job":
                out[c["name"]]["up"] = None
                out[c["name"]]["extra"]["running"] = bool(self.jobs_named(c["name"]))
            elif c["kind"] == "external":
                out[c["name"]].update(self.external_view(c["name"], out))
        self.spec.observe_extra(self, out, window_s)
        return {"t": time.time(), "window_s": window_s, "components": out, "baseline": self.baseline,
                "changes": [{k: v for k, v in ch.items()} for ch in self.changes.recent(900)]}

    def external_view(self, name, out):
        """Another organisation's system: only what our own callers saw of it."""
        views = [((e.get("extra") or {}).get("dependencies") or {}).get(name) for e in out.values()]
        views = [v for v in views if v and v.get("n")]
        if not views:
            return {"up": None, "p95_ms": None, "error_rate": None, "reject_rate": None, "rps": None,
                    "cpu_pct": None, "mem_mb": None, "restarts": None, "release": None, "config_version": None,
                    "extra": {"view": "no calls from our side in the window"}}
        view = max(views, key=lambda v: v["n"])
        return {"up": (view.get("error_rate") or 0.0) < 1.0, "p95_ms": view.get("p95_ms"),
                "error_rate": view.get("error_rate"), "reject_rate": view.get("reject_rate"), "rps": view.get("rps"),
                "cpu_pct": None, "mem_mb": None, "restarts": None, "release": None, "config_version": None,
                "extra": {"view": "as our callers see it; its own metrics and logs are not visible"}}

    def logs(self, component, since_s=60.0, limit=200):
        c = self.component(component)
        if c is None:
            raise net.Reply(404, {"error": f"no component {component}"})
        if c["kind"] == "external":
            return []   # we cannot read another organisation's logs
        path = os.path.join(self.data_dir, "logs", f"{component}.jsonl")
        return read_logs(path, time.time() - since_s, limit)

    def act(self, action, target, params, actor=AGENT_ACTOR):
        c = self.component(target)
        allowed = c.get("actions", []) if c else []
        if action not in ACTIONS or action not in allowed:
            record = {"ok": False, "refused": True, "action": action, "target": target,
                      "detail": f"{action} is not allowed on {target}"}
        else:
            ok, detail = self.spec.act(self, action, target, params or {}, actor)
            record = {"ok": bool(ok), "refused": False, "action": action, "target": target, "detail": detail}
        with open(os.path.join(self.data_dir, "actions.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": time.time(), "params": params or {}, **record}) + "\n")
        return record

    def compute_baseline(self, window_s):
        snapshot = self.observe(window_s)["components"]
        self.baseline = {name: {"p95_ms": e["p95_ms"], "error_rate": e["error_rate"],
                                "reject_rate": e["reject_rate"], "rps": e["rps"], "release": e["release"],
                                "config_version": e["config_version"]}
                         for name, e in snapshot.items() if e["up"] is not None}
        write_json(os.path.join(self.data_dir, "baseline.json"), self.baseline)
        return self.baseline

    # ----- HTTP API -----

    def routes(self):
        def q(request, key, default):
            return request["query"].get(key, default)

        def control(fn):
            def wrapped(request):
                if request["headers"].get("X-Control-Token") != self.control_token:
                    raise net.Reply(403, {"error": "control token required"})
                return fn(request["body"])
            return wrapped

        ops = {
            ("GET", "/ops/describe"): lambda r: self.spec.describe(self),
            ("GET", "/ops/observe"): lambda r: self.observe(float(q(r, "window", 10))),
            ("GET", "/ops/logs"): lambda r: {"records": self.logs(q(r, "component", ""), float(q(r, "since", 60)),
                                                                  int(q(r, "limit", 200)))},
            ("POST", "/ops/probe"): lambda r: self.spec.probe(self, r["body"].get("journey")),
            ("POST", "/ops/act"): lambda r: self.act(r["body"].get("action"), r["body"].get("target"),
                                                     r["body"].get("params")),
            ("GET", "/health"): lambda r: {"ok": True, "system": self.spec.system},
        }
        ctl = {
            "/control/kill": lambda b: {"ok": self.kill(b["component"])},
            "/control/stop": lambda b: {"ok": self.stop(b["component"], b.get("actor", "operator"),
                                                        b.get("log_change", True))},
            "/control/start": lambda b: {"ok": self.start(b["component"], b.get("actor", "operator"),
                                                          b.get("log_change", True))},
            "/control/deploy": lambda b: {"ok": self.deploy(b["component"], b["release"], b.get("module_path"),
                                                            b.get("actor", "pipeline"))},
            "/control/config": lambda b: (self.set_config(b["component"], b["key"], b["value"],
                                                          b.get("actor", "operator")) or {"ok": True}),
            "/control/link": lambda b: (self.set_link(b["route"], b.get("latency_ms", 0), b.get("jitter_ms", 0),
                                                      b.get("drop_pct", 0.0)) or {"ok": True}),
            "/control/spawn": lambda b: {"ok": True, "pid": self.spawn_job(b["name"], b["argv"])},
            "/control/admin": lambda b: self._admin(b),
            "/control/snapshot": lambda b: self.spec.snapshot(self),
            "/control/baseline": lambda b: {"baseline": self.compute_baseline(float(b.get("window_s", 10)))},
            "/control/shutdown": lambda b: self._shutdown_soon(),
        }
        return {**ops, **{("POST", path): control(fn) for path, fn in ctl.items()}}

    def _admin(self, body):
        port = self.ports[body["component"]]
        return net.post(f"http://127.0.0.1:{port}/admin/{body['op']}", body.get("payload") or {},
                        timeout=2.0, headers={"X-Admin-Token": self.admin_token})[1]

    def _shutdown_soon(self):
        threading.Thread(target=self.shutdown, daemon=True).start()
        return {"ok": True}

    def shutdown(self):
        self.stopping = True
        time.sleep(0.2)
        with self.lock:
            for job in list(self.jobs.values()):
                if job.poll() is None:
                    proc.kill(job.pid)
            for mp in self.procs.values():
                if mp.popen and mp.popen.poll() is None:
                    mp.expected_down = True
                    proc.kill(mp.popen.pid)
            self.spec.cleanup(self)
        write_json(os.path.join(self.data_dir, "supervisor.json"), {"pid": os.getpid(), "status": "stopped"})
        if self.server:
            self.server.shutdown()

    def serve(self):
        self.server = net.JsonServer(self.ports["supervisor"], self.routes())
        threading.Thread(target=self.monitor, daemon=True).start()
        write_json(os.path.join(self.data_dir, "supervisor.json"),
                   {"pid": os.getpid(), "port": self.ports["supervisor"], "status": "ready", "t": time.time()})
        self.server.serve_forever(poll_interval=0.2)


def fresh_dir(path):
    """Remove an old copy's data folder; retried because Windows releases files slowly."""
    for attempt in range(20):
        if not os.path.exists(path):
            break
        try:
            shutil.rmtree(path)
        except OSError:
            time.sleep(0.25)
    os.makedirs(path, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Run the control plane for one copy of a test system.")
    parser.add_argument("--system", required=True)
    parser.add_argument("--port-base", type=int, required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--condition", default="default")
    args = parser.parse_args()
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    spec = importlib.import_module(f"targets.{args.system}.spec").Spec()
    sup = Supervisor(spec, args.port_base, args.data, args.seed, args.condition)
    sup.server = None
    try:
        sup.prepare()
        sup.start_all()
    except Exception as exc:
        write_json(os.path.join(sup.data_dir, "supervisor.json"),
                   {"pid": os.getpid(), "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        sup.shutdown()
        raise
    sup.serve()


if __name__ == "__main__":
    main()
