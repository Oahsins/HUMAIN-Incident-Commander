"""Clients for a running copy of a test system: the agent's adapter, the privileged control, and the platform.

These are generic. A system's own adapter.py, control.py and platform.py
subclass them, so an adapter for a real system (one an organiser supplies, say)
can replace the HTTP calls without the agent noticing.
"""

import os
import time

from . import net, proc
from .store import read_json
from .supervisor import fresh_dir

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def default_data_dir(system, port_base):
    return os.path.join(ROOT, "runs", f"{system}-{port_base}")


class OpsAdapter:
    """The five functions the agent may use (CONTRACT.md section 3). Nothing here can inject a fault."""

    def __init__(self, port_base):
        self.base = f"http://127.0.0.1:{port_base + 9}"

    def _get(self, path, timeout=5.0):
        return net.get(self.base + path, timeout=timeout)[1]

    def _post(self, path, payload, timeout=10.0):
        return net.post(self.base + path, payload, timeout=timeout)[1]

    def describe(self):
        return self._get("/ops/describe")

    def observe(self, window_s=10.0):
        return self._get(f"/ops/observe?window={window_s}", timeout=10.0)

    def logs(self, component, since_s=60.0, limit=200):
        return self._get(f"/ops/logs?component={component}&since={since_s}&limit={limit}")["records"]

    def probe(self, journey=None):
        return self._post("/ops/probe", {"journey": journey}, timeout=15.0)

    def act(self, action, target, params=None):
        try:
            return self._post("/ops/act", {"action": action, "target": target, "params": params or {}}, timeout=20.0)
        except net.CallError as exc:
            return {"ok": False, "refused": False, "action": action, "target": target,
                    "detail": f"action call failed: {exc}"}


class ControlClient:
    """Privileged operations (CONTRACT.md section 5). For the injector, the checker and the harness only."""

    def __init__(self, port_base, data_dir):
        self.port_base = port_base
        self.data_dir = data_dir
        self.base = f"http://127.0.0.1:{port_base + 9}"
        with open(os.path.join(data_dir, "control.token"), encoding="utf-8") as handle:
            self.token = handle.read().strip()

    def _post(self, path, payload=None, timeout=20.0):
        return net.post(self.base + path, payload or {}, timeout=timeout, headers={"X-Control-Token": self.token})[1]

    def kill(self, component):
        """Hard-kill a process, as a crash would. No change is recorded."""
        return self._post("/control/kill", {"component": component})["ok"]

    def stop(self, component, actor="operator", log_change=True):
        return self._post("/control/stop", {"component": component, "actor": actor, "log_change": log_change})["ok"]

    def start(self, component, actor="operator", log_change=True):
        return self._post("/control/start", {"component": component, "actor": actor, "log_change": log_change})["ok"]

    def deploy(self, component, release, module_path=None, actor="pipeline"):
        """Switch a component to another release and restart it. True when it answers health checks again."""
        return self._post("/control/deploy", {"component": component, "release": release,
                                              "module_path": module_path and os.path.abspath(module_path),
                                              "actor": actor})["ok"]

    def set_config(self, component, key, value, actor="operator"):
        return self._post("/control/config", {"component": component, "key": key, "value": value, "actor": actor})["ok"]

    def link(self, route, latency_ms=0, jitter_ms=0, drop_pct=0.0):
        return self._post("/control/link", {"route": route, "latency_ms": latency_ms, "jitter_ms": jitter_ms,
                                            "drop_pct": drop_pct})["ok"]

    def db(self, name=None):
        """A direct connection to one of the system's datastores. Each system's Control provides it."""
        raise NotImplementedError

    def spawn(self, name, argv):
        """Start a helper process and return its pid. In argv, "{python}" is this Python and "{data}" the data folder."""
        return self._post("/control/spawn", {"name": name, "argv": argv})["pid"]

    def admin(self, component, op, payload=None):
        return self._post("/control/admin", {"component": component, "op": op, "payload": payload})

    def snapshot(self):
        return self._post("/control/snapshot")

    def baseline(self, window_s=10.0):
        return self._post("/control/baseline", {"window_s": window_s})

    def paths(self):
        d = self.data_dir
        return {"data_dir": d, "logs": os.path.join(d, "logs"),
                "actions": os.path.join(d, "actions.jsonl"), "changes": os.path.join(d, "changes.jsonl")}

    def shutdown(self):
        return self._post("/control/shutdown")


class PlatformBase:
    """Start and stop one copy of a test system (CONTRACT.md section 6)."""

    system = None
    adapter_cls = OpsAdapter
    control_cls = ControlClient
    conditions = ("default",)   # the robustness conditions this system implements (ic.contract.CONDITIONS)

    def __init__(self, port_base=8100, data_dir=None, seed=0, condition="default"):
        self.port_base = port_base
        self.data_dir = os.path.abspath(data_dir or default_data_dir(self.system, port_base))
        self.seed = seed
        self.condition = condition
        self.popen = None

    def start(self, warmup_s=10.0, detached=False, timeout_s=45.0):
        """Start every process and the test customers, wait for health, then measure the baseline."""
        if self.condition not in self.conditions:
            raise ValueError(f"{self.system} does not implement the condition {self.condition!r} "
                             f"(it has: {', '.join(self.conditions)})")
        for offset in range(10):
            if not net.port_free(self.port_base + offset):
                raise RuntimeError(f"port {self.port_base + offset} is in use: is another copy running? "
                                   f"Try `python run.py down --port-base {self.port_base}`")
        fresh_dir(self.data_dir)
        os.makedirs(os.path.join(self.data_dir, "logs"), exist_ok=True)
        argv = proc.python_argv("ic.kit.supervisor", "--system", self.system, "--port-base", self.port_base,
                                "--data", self.data_dir, "--seed", self.seed, "--condition", self.condition)
        self.popen = proc.spawn(argv, os.path.join(self.data_dir, "logs", "supervisor.out"),
                                {"PYTHONPATH": ROOT}, detached=detached, cwd=ROOT)
        proc.wait_until(lambda: self._status() in ("ready", "failed"), timeout_s, 0.2)
        status = self._status()
        if status != "ready":
            info = read_json(os.path.join(self.data_dir, "supervisor.json"), {})
            self.stop()
            raise RuntimeError(f"{self.system} did not start: {info.get('error') or status or 'timed out'} "
                               f"(see {os.path.join(self.data_dir, 'logs')})")
        time.sleep(warmup_s)
        self.control().baseline(warmup_s)
        self.after_warmup(warmup_s)
        return self

    def after_warmup(self, warmup_s):
        """Hook for a system to record its own healthy reference (the bank's checker baseline, say)."""

    def _status(self):
        return read_json(os.path.join(self.data_dir, "supervisor.json"), {}).get("status")

    def running(self):
        return self._status() == "ready" and not net.port_free(self.port_base + 9)

    def adapter(self):
        return self.adapter_cls(self.port_base)

    def control(self):
        return self.control_cls(self.port_base, self.data_dir)

    def stop(self):
        """Stop everything. Safe to call twice, and safe after a crash."""
        info = read_json(os.path.join(self.data_dir, "supervisor.json"), {})
        try:
            self.control().shutdown()
        except (net.CallError, OSError):
            pass
        pid = info.get("pid") or (self.popen.pid if self.popen else None)
        if pid:
            proc.wait_until(lambda: not proc.alive(pid), 5.0, 0.1)
            if proc.alive(pid):
                proc.kill(pid)
        # Anything still holding our ports belongs to this copy: clean it up.
        for offset in range(10):
            port = self.port_base + offset
            for conn in _listeners(port):
                proc.kill(conn)


def _listeners(port):
    import psutil
    pids = set()
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN and conn.pid:
                pids.add(conn.pid)
    except (psutil.AccessDenied, PermissionError):
        pass
    return pids
