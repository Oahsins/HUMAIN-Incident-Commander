import time

TYPE = "sealed_9"
CLASSES = []
OPTIONS = {
    "v1": ("unit-sync", "setting", "batch_size", 100),
    "v2": ("cad", "setting", "write_timeout_ms", 2000),
    "v3": ("call-handling", "setting", "rollover_s", 3.0),
    "v4": ("dispatcher", "setting", "alert_timeout_s", 1.5),
    "v5": ("alerting-backup", "release", None, "1.6.1"),
    "v6": ("incident-archive", "job", None, None),
    "v7": ("call-handling", "setting", "positions", 12),
}


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameters")
    variant = params.get("variant", "v1")
    if variant not in OPTIONS:
        raise ValueError("unsupported selection")
    target, operation, key, value = OPTIONS[variant]
    if params.get("target", target) != target:
        raise ValueError("unsupported selection")
    actor = rng.choice(("operator", "pipeline"))
    detail = {"component": target}
    if operation == "setting":
        ok = control.set_config(target, key, value, actor=actor)
        detail.update(key=key, value=value)
    elif operation == "release":
        ok = control.deploy(target, value, actor=actor)
        detail["release"] = value
    else:
        pid = control.spawn("incident-archive", ["{python}", "-m", "targets.dispatch.jobs.incident_archive",
                                               "--data", "{data}", "--export"])
        ok = isinstance(pid, int) and pid > 0
        detail["pid"] = pid
    if not ok:
        raise RuntimeError("change was not completed")
    return {"type": TYPE, "target": None, "class": None, "detail": detail, "t": time.time()}
