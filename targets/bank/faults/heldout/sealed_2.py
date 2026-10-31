"""Deploy an unchanged screening build to the unused standby."""

from pathlib import Path
import time

from targets.bank.faults.common import ACTORS

TYPE = "sealed_2"
CLASSES = []


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameter")
    if params.get("target") != "screening-standby" or params.get("variant") != "v1":
        raise ValueError("unsupported target or variant")
    module = str(Path(__file__).with_name("sealed_5.py"))
    if not control.deploy("screening-standby", "4.1.2", module_path=module, actor=rng.choice(ACTORS)):
        raise RuntimeError("release did not become available")
    return {"type": TYPE, "target": None, "class": None, "detail": {}, "t": time.time()}
