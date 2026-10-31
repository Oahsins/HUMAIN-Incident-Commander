"""Deploy a payments build that mishandles the customer's retry."""

from pathlib import Path
import time

from targets.bank.faults.common import ACTORS

TYPE = "double_posting"
CLASSES = ["bad_release"]


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameter")
    if params.get("target") != "payments" or params.get("variant") != "v1":
        raise ValueError("unsupported target or variant")
    module = str(Path(__file__).with_name("sealed_4.py"))
    if not control.deploy("payments", "1.5", module_path=module, actor=rng.choice(ACTORS)):
        raise RuntimeError("release did not become available")
    return {"type": TYPE, "target": "payments", "class": "bad_release",
            "detail": {"release": "1.5"}, "t": time.time()}
