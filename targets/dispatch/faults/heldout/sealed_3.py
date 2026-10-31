import time
from pathlib import Path

TYPE = "sealed_3"
CLASSES = ["bad_release"]


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameters")
    target = params.get("target", "dispatcher")
    if target != "dispatcher" or params.get("variant", "v1") != "v1":
        raise ValueError("unsupported selection")
    actor = rng.choice(("operator", "pipeline"))
    pid = control.surge(2.5, 300, seed=173, mix="normal")
    module = str(Path(__file__).with_name("sealed_4.py"))
    if not control.deploy(target, "2.2", module_path=module, actor=actor):
        raise RuntimeError("change was not completed")
    return {"type": TYPE, "target": target, "class": "bad_release",
            "detail": {"release": "2.2", "pid": pid}, "t": time.time()}
