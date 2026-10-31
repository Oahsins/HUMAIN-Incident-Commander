import time

TYPE = "sealed_10"
CLASSES = ["bad_config", "process_down", "dependency_slow", "lock_held", "external_outage"]
OPTIONS = {
    "v1": ("call-handling", "bad_config", "positions", 0),
    "v2": ("dispatcher", "bad_config", "ack_timeout_s", 0.05),
    "v3": ("cad", "bad_config", "repeat_match", "off"),
    "v4": ("unit-sync", "bad_config", "batch_size", 0),
    "v5": ("dispatcher", "process_down", "hang", None),
    "v6": ("cad", "process_down", "kill", None),
    "v7": ("alerting", "dependency_slow", "dispatcher->alerting", None),
    "v8": ("cad-db", "lock_held", None, None),
    "v9": ("call-network", "external_outage", "call-handling->call-network", None),
}


def inject(control, params, rng):
    if set(params) - {"target", "variant"}:
        raise ValueError("unsupported parameters")
    variant = params.get("variant", "v1")
    if variant not in OPTIONS:
        raise ValueError("unsupported selection")
    target, label, key, value = OPTIONS[variant]
    if params.get("target", target) != target:
        raise ValueError("unsupported selection")
    actor = rng.choice(("operator", "pipeline"))
    detail = {}
    if label == "bad_config":
        ok = control.set_config(target, key, value, actor=actor)
        detail = {"key": key, "value": value}
    elif label == "process_down":
        if key == "hang":
            ok = control.admin(target, "hang").get("ok") is True
        else:
            ok = control.kill(target)
    elif label in ("dependency_slow", "external_outage"):
        ok = control.link(key, drop_pct=1.0)
        detail = {"route": key, "drop_pct": 1.0}
    else:
        pid = control.spawn("incident-archive", ["{python}", "-m", "targets.dispatch.jobs.incident_archive",
                                               "--data", "{data}", "--hold-lock", "600"])
        ok = isinstance(pid, int) and pid > 0
        detail = {"pid": pid, "hold_s": 600}
    if not ok:
        raise RuntimeError("change was not completed")
    return {"type": TYPE, "target": target, "class": label, "detail": detail, "t": time.time()}
