import time
from pathlib import Path

TYPE = "sealed_1"
CLASSES = ["bad_release"]


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameters")
    target = params.get("target", "call-handling")
    if target != "call-handling" or params.get("variant", "v1") != "v1":
        raise ValueError("unsupported selection")
    actor = rng.choice(("operator", "pipeline"))
    module = str(Path(__file__).with_name("sealed_2.py"))
    if not control.deploy(target, "5.3", module_path=module, actor=actor):
        raise RuntimeError("change was not completed")
    return {"type": TYPE, "target": target, "class": "bad_release",
            "detail": {"release": "5.3"}, "t": time.time()}
