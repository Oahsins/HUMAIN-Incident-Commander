"""Small files shared between a system's processes: settings, the change log and releases.

Everything lives in the copy's data folder, so two copies never share state.
Writes go to a temporary file first and are then swapped in, so a reader never
sees half a file. On Windows the swap can briefly fail while another process
is reading, so it is retried.
"""

import json
import os
import tempfile
import threading
import time


def write_json(path, value):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=1)
    for attempt in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: a reader has the file open; try again shortly
            time.sleep(0.02)
    os.replace(tmp, path)


def read_json(path, default=None):
    for attempt in range(50):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return default
        except (PermissionError, ValueError):  # mid-swap on Windows, or a torn read: retry
            time.sleep(0.02)
    return default


class ConfigStore:
    """Versioned settings for one component: config/<component>.json.

    {"version": 3, "values": {...},
     "history": [{"version": 2, "key": "max_transfer_minor", "from": 1000000, "to": 5000, "t": ..., "actor": ...}, ...]}
    Every change records the one key it changed, so undoing a change restores
    that key only and leaves every later change in place.
    """

    def __init__(self, data_dir, component):
        self.path = os.path.join(data_dir, "config", f"{component}.json")

    def init(self, values):
        write_json(self.path, {"version": 1, "values": dict(values), "history": []})

    def load(self):
        return read_json(self.path, {"version": 0, "values": {}, "history": []})

    def set(self, key, value, actor):
        return self.set_many({key: value}, actor)

    def set_many(self, values, actor):
        doc = self.load()
        now = time.time()
        for key, value in values.items():
            doc["history"].append({"version": doc["version"], "key": key, "from": doc["values"].get(key),
                                   "to": value, "t": now, "actor": actor})
            doc["values"][key] = value
        doc["version"] += 1
        write_json(self.path, doc)
        return doc

    def revert(self, actor, key=None, skip_actor=None):
        """Undo one change: the newest change to `key`, or with no key the newest change not made by skip_actor.

        Returns the history entry it undid, or None when there is nothing to undo.
        """
        doc = self.load()
        for entry in reversed(doc["history"]):
            if entry.get("revert") or entry.get("undone"):
                continue
            if key is not None and entry.get("key") != key:
                continue
            if key is None and skip_actor is not None and entry.get("actor") == skip_actor:
                continue
            entry["undone"] = True
            current = doc["values"].get(entry["key"])
            doc["values"][entry["key"]] = entry["from"]
            doc["history"].append({"version": doc["version"], "key": entry["key"], "from": current,
                                   "to": entry["from"], "t": time.time(), "actor": actor, "revert": True})
            doc["version"] += 1
            write_json(self.path, doc)
            return {"key": entry["key"], "from": current, "to": entry["from"], "changed_by": entry.get("actor")}
        return None


class CachedConfig:
    """Read-side view a service uses on every request; re-reads the file at most every 0.2 s."""

    def __init__(self, data_dir, component):
        self.store = ConfigStore(data_dir, component)
        self.lock = threading.Lock()
        self.doc = self.store.load()
        self.read_t = time.time()

    def values(self):
        with self.lock:
            if time.time() - self.read_t > 0.2:
                self.doc = self.store.load() or self.doc
                self.read_t = time.time()
            return self.doc["values"], self.doc["version"]


class Routing:
    """routing.json: which side (primary or standby) serves each component that has a standby.

    Routing is not a setting: a failover never shows up as a config change,
    and undoing a setting never undoes a failover.
    """

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "routing.json")

    def load(self):
        return read_json(self.path, {})

    def active(self, component):
        return self.load().get(component, "primary")

    def set(self, component, side):
        doc = self.load()
        doc[component] = side
        write_json(self.path, doc)


class CachedRouting:
    """Read-side view of routing.json for a service; re-reads at most every 0.2 s."""

    def __init__(self, data_dir):
        self.routing = Routing(data_dir)
        self.lock = threading.Lock()
        self.doc = self.routing.load()
        self.read_t = time.time()

    def active(self, component):
        with self.lock:
            if time.time() - self.read_t > 0.2:
                self.doc = self.routing.load()
                self.read_t = time.time()
            return self.doc.get(component, "primary")


class ChangeLog:
    """changes.jsonl: deploys, setting changes, starts, stops, restarts and so on."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "changes.jsonl")
        self.lock = threading.Lock()

    def add(self, component, kind, actor, **detail):
        record = {"id": f"c-{time.time_ns() // 1000:x}", "t": round(time.time(), 3), "component": component,
                  "kind": kind, "actor": actor, "detail": detail}
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        return record

    def recent(self, since_s=900.0):
        if not os.path.exists(self.path):
            return []
        cutoff = time.time() - since_s
        out = []
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record["t"] >= cutoff:
                    out.append(record)
        return out


class Releases:
    """releases.json: which release each component runs, its history, and extra release modules.

    {"current": {"payments": "1.3"}, "history": {"payments": ["1.2"]}, "modules": {"payments:1.5": "path/to/v1_5.py"}}
    """

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "releases.json")

    def load(self):
        return read_json(self.path, {"current": {}, "history": {}, "modules": {}})

    def init(self, current):
        write_json(self.path, {"current": dict(current), "history": {k: [] for k in current}, "modules": {}})

    def current(self, component):
        return self.load()["current"].get(component)

    def deploy(self, component, version, module_path=None):
        doc = self.load()
        old = doc["current"].get(component)
        if old is not None and old != version:
            doc["history"].setdefault(component, []).append(old)
        doc["current"][component] = version
        if module_path:
            doc["modules"][f"{component}:{version}"] = os.path.abspath(module_path)
        write_json(self.path, doc)
        return old

    def rollback(self, component):
        """Return to the previous release. Returns (from, to) or None when there is none."""
        doc = self.load()
        history = doc["history"].get(component) or []
        if not history:
            return None
        old = doc["current"][component]
        new = history.pop()
        doc["current"][component] = new
        write_json(self.path, doc)
        return old, new

    def module_path(self, component, version):
        return self.load()["modules"].get(f"{component}:{version}")
