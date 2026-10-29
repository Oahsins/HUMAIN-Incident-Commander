"""Apply a scenario's faults to a running test system (CONTRACT.md section 7).

    from ic import inject
    manifest = inject.apply("bank", control, faults, seed=7)

Practice fault types live in targets/<system>/faults/dev/<type>.py. The sealed
exam's fault types live in faults/heldout/ and load only with
allow_sealed=True, so nothing touches them by accident during development.
"""

import importlib.util
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fault_path(system, fault_type, folder):
    return os.path.join(ROOT, "targets", system, "faults", folder, f"{fault_type}.py")


def load(system, fault_type, allow_sealed=False):
    """The fault plugin module for one fault type."""
    folders = ["dev", "heldout"] if allow_sealed else ["dev"]
    for folder in folders:
        path = fault_path(system, fault_type, folder)
        if os.path.exists(path):
            if ROOT not in sys.path:
                sys.path.insert(0, ROOT)
            name = f"_fault_{system}_{folder}_{fault_type}"
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    if not allow_sealed and os.path.exists(fault_path(system, fault_type, "heldout")):
        raise PermissionError(f"{fault_type} is a sealed exam fault; it loads only for the final run")
    raise KeyError(f"no fault type {fault_type!r} for {system}")


def available(system, allow_sealed=False):
    names = []
    for folder in (["dev", "heldout"] if allow_sealed else ["dev"]):
        directory = os.path.join(ROOT, "targets", system, "faults", folder)
        if os.path.isdir(directory):
            names += sorted(f[:-3] for f in os.listdir(directory) if f.endswith(".py") and not f.startswith("_"))
    return names


def apply(system, control, faults, seed=7, allow_sealed=False, t0=None, on_inject=None):
    """Inject each fault at its at_s offset from t0 (default: now). Returns the manifest entries in order."""
    rng = random.Random(seed)
    t0 = time.time() if t0 is None else t0
    manifest = []
    for fault in sorted(faults, key=lambda f: f.get("at_s", 0)):
        delay = t0 + float(fault.get("at_s", 0)) - time.time()
        if delay > 0:
            time.sleep(delay)
        module = load(system, fault["type"], allow_sealed)
        entry = module.inject(control, dict(fault.get("params") or {}), rng)
        entry.setdefault("type", fault["type"])
        entry.setdefault("t", time.time())
        entry["at_s"] = fault.get("at_s", 0)
        manifest.append(entry)
        if on_inject:
            on_inject(entry)
    return manifest
