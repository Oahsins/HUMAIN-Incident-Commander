"""A tiny in-memory system behind the adapter contract, for testing the agent with no processes and no bank.

    web (service) -> cache (dependency, standby cache-b) and db (datastore); partner (external)

Faults: web_down, web_bad_config, cache_slow, db_locked, partner_down. Each allowed action clears the
fault it fixes; nothing else changes anything.
"""

import time

PROFILE = {
    "system": "fake", "contract_version": 1,
    "capabilities": {"probe": True, "act": True, "changes": True, "baseline": "warmup", "max_mode": "auto",
                     "min_window_s": 1},
    "journeys": [{"name": "order", "default": True, "entry": "web", "slo": {"success_rate": 0.99, "p95_ms": 500},
                  "side_effects": "none", "description": "a user places an order"}],
    "slo": {"success_rate": 0.99, "p95_ms": 500},
    "components": [
        {"name": "web", "kind": "service", "depends_on": ["cache", "db", "partner"], "impact_weight": 1.0,
         "actions": ["restart", "rollback", "revert_config"], "standby": None, "description": "web front end"},
        {"name": "cache", "kind": "dependency", "depends_on": [], "impact_weight": 1.0,
         "actions": ["restart", "failover"], "standby": "cache-b", "description": "cache, with a standby"},
        {"name": "cache-b", "kind": "dependency", "depends_on": [], "impact_weight": 0.0, "actions": ["restart"],
         "standby": None, "description": "cache standby"},
        {"name": "db", "kind": "datastore", "depends_on": [], "impact_weight": 1.0, "actions": ["release_lock"],
         "standby": None, "description": "database"},
        {"name": "partner", "kind": "external", "depends_on": [], "impact_weight": 0.5, "actions": [],
         "standby": None, "description": "a partner's API, run by another organisation"},
    ],
    "actions": {"restart": {"est_seconds": 1, "params": {}, "description": "restart"},
                "rollback": {"est_seconds": 1, "params": {}, "description": "previous release"},
                "revert_config": {"est_seconds": 1, "params": {"key": {"optional": True}}, "description": "undo a setting"},
                "release_lock": {"est_seconds": 1, "params": {}, "description": "end the lock holder"},
                "failover": {"est_seconds": 1, "params": {"to": {"enum": ["standby", "primary"]}},
                             "description": "switch to the standby"},
                "quarantine": {"est_seconds": 1, "params": {"item": {}}, "description": "set an item aside"}},
    "forbidden": [],
}

FIXES = {("restart", "web"): "web_down", ("revert_config", "web"): "web_bad_config",
         ("failover", "cache"): "cache_slow", ("release_lock", "db"): "db_locked"}


def _entry(**kw):
    entry = {"up": True, "p95_ms": 20.0, "error_rate": 0.0, "reject_rate": 0.0, "rps": 10.0, "cpu_pct": 5.0,
             "mem_mb": 50.0, "restarts": 0, "release": "1.0", "config_version": 1, "extra": {}}
    entry.update(kw)
    return entry


class FakeSystem:
    def __init__(self, faults=()):
        self.faults = set(faults)
        self.t0 = time.time()
        self.active = "primary"
        self.acts = []

    def describe(self):
        return PROFILE

    def observe(self, window_s=10.0):
        f, now = self.faults, time.time()
        web = _entry(extra={"dependencies": {"cache": {"p95_ms": 900.0 if "cache_slow" in f and self.active == "primary"
                                                        else 15.0, "error_rate": 0.0, "reject_rate": 0.0, "rps": 10.0},
                                             "db": {"p95_ms": 10.0, "error_rate": 1.0 if "db_locked" in f else 0.0,
                                                    "reject_rate": 0.0, "rps": 10.0}}})
        if "web_down" in f:
            web.update(up=False, error_rate=None, rps=None, p95_ms=None, extra={"exits_15m": 1, "last_exit_s_ago": 3,
                                                                              "last_exit_code": 1})
        if "web_bad_config" in f:
            web["reject_rate"] = 0.6
        if "db_locked" in f:
            web["error_rate"] = 0.5
        components = {
            "web": web,
            "cache": _entry(rps=0.0 if self.active == "standby" else 10.0, extra={"active": self.active}),
            "cache-b": _entry(rps=10.0 if self.active == "standby" else 0.0),
            "db": _entry(p95_ms=None, rps=None, extra={"lock_holders": [{"session": "batch", "mode": "write",
                                                                         "held_s": 30, "statement": "UPDATE"}]}
                         if "db_locked" in f else {}),
            "partner": _entry(up=False if "partner_down" in f else True, error_rate=1.0 if "partner_down" in f else 0.0),
        }
        changes = []
        if "web_bad_config" in f:
            changes.append({"id": "c-1", "t": self.t0 - 2, "component": "web", "kind": "config", "actor": "operator",
                            "detail": {"key": "limit", "from": 100, "to": 1}})
        baseline = {name: {"p95_ms": 20.0, "error_rate": 0.0, "reject_rate": 0.0, "rps": 10.0}
                    for name in ("web", "cache", "db", "partner")}
        baseline["cache-b"] = {"p95_ms": None, "error_rate": None, "reject_rate": None, "rps": 0.0}
        return {"t": now, "window_s": window_s, "components": components, "changes": changes, "baseline": baseline}

    def logs(self, component, since_s=60.0, limit=200):
        if component == "web" and self.faults & {"web_down", "db_locked"}:
            return [{"t": time.time() - 1, "level": "ERROR", "component": "web", "event": "fail", "msg": "request failed"}]
        return []

    def probe(self, journey=None):
        f = self.faults
        steps = [{"step": "web", "component": "web", "ok": "web_down" not in f, "detail": "answered"},
                 {"step": "order", "component": "web", "ok": not f & {"db_locked", "cache_slow"} or
                  ("cache_slow" in f and self.active == "standby" and "db_locked" not in f), "detail": "order placed"},
                 {"step": "partner", "component": "partner", "ok": "partner_down" not in f, "detail": "sent"}]
        if not steps[0]["ok"]:
            steps = steps[:1]
        return {"journey": "order", "ok": all(s["ok"] for s in steps), "steps": steps}

    def act(self, action, target, params=None):
        self.acts.append((action, target, dict(params or {})))
        component = next((c for c in PROFILE["components"] if c["name"] == target), None)
        if component is None or action not in component["actions"]:
            return {"ok": False, "refused": True, "action": action, "target": target,
                    "detail": f"{action} is not allowed on {target}"}
        if action == "failover":
            self.active = (params or {}).get("to", "standby")
            return {"ok": True, "refused": False, "action": action, "target": target, "detail": f"now {self.active}"}
        self.faults.discard(FIXES.get((action, target), ""))
        return {"ok": True, "refused": False, "action": action, "target": target, "detail": "done"}
