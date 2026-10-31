import time
from pathlib import Path

TYPE = "sealed_7"
CLASSES = ["bad_release"]


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameters")
    target = params.get("target", "cad")
    if target != "cad" or params.get("variant", "v1") != "v1":
        raise ValueError("unsupported selection")
    actor = rng.choice(("operator", "pipeline"))
    module = str(Path(__file__).with_name("sealed_8.py"))
    if not control.deploy(target, "3.5", module_path=module, actor=actor):
        raise RuntimeError("change was not completed")
    return {"type": TYPE, "target": target, "class": "bad_release",
            "detail": {"release": "3.5"}, "t": time.time()}
