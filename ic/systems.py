"""Find a test system's parts by name, so harness code never imports a system's modules directly.

    from ic import systems
    p = systems.platform("bank", port_base=8200, seed=7)
    checker = systems.checker("bank")
"""

import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _module(system, part):
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    return importlib.import_module(f"targets.{system}.{part}")


def platform(system, **kwargs):
    """A Platform for one copy of the system (not yet started)."""
    return _module(system, "platform").Platform(**kwargs)


def checker(system):
    """The system's checker module, with verify(control, window_s=..., since_t=...)."""
    return _module(system, "checker")


def available():
    base = os.path.join(ROOT, "targets")
    return sorted(name for name in os.listdir(base)
                  if os.path.exists(os.path.join(base, name, "platform.py")))
