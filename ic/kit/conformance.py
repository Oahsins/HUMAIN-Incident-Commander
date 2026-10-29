"""Does an adapter keep the contract? Run this against any new system's adapter (docs/ADDING-A-SYSTEM.md).

    from ic.kit.conformance import check_adapter, check_verdict
    problems = check_adapter(adapter)          # [] when it conforms
    problems = check_adapter(adapter, act=False)   # skip act(): read-only systems
    problems = check_verdict(checker.verify(control, since_t=t0))   # the keys eval/ reads from any checker

check_adapter calls describe(), observe(), probe() and logs() once each, and act() once
with an action no component allows (which must come back refused, never raise).
"""

from ic.contract import ACTIONS, COMPONENT_KINDS

ENTRY_KEYS = ("up", "p95_ms", "error_rate", "reject_rate", "rps", "cpu_pct", "mem_mb", "restarts", "release",
              "config_version", "extra")


def check_profile(profile):
    problems = []
    for key in ("system", "components", "actions"):
        if key not in profile:
            problems.append(f"describe(): no {key!r}")
    names = set()
    for c in profile.get("components", []):
        name = c.get("name")
        names.add(name)
        if c.get("kind") not in COMPONENT_KINDS:
            problems.append(f"describe(): {name}: kind {c.get('kind')!r} is not one of {COMPONENT_KINDS}")
        for action in c.get("actions") or []:
            if action not in ACTIONS:
                problems.append(f"describe(): {name}: {action!r} is not one of the six actions")
        if "failover" in (c.get("actions") or []) and not c.get("standby"):
            problems.append(f"describe(): {name} may fail over but names no standby")
    for c in profile.get("components", []):
        for dep in c.get("depends_on") or []:
            if dep not in names:
                problems.append(f"describe(): {c.get('name')} depends on unknown {dep!r}")
    for action in profile.get("actions") or {}:
        if action not in ACTIONS:
            problems.append(f"describe(): action {action!r} is not one of the six actions")
    journeys = profile.get("journeys") or []
    if journeys and sum(1 for j in journeys if j.get("default")) != 1:
        problems.append("describe(): exactly one journey must be the default")
    return problems


def check_observation(profile, obs):
    problems = []
    names = {c["name"] for c in profile.get("components", [])}
    entries = obs.get("components") or {}
    for name in names - set(entries):
        problems.append(f"observe(): no entry for {name}")
    for name, entry in entries.items():
        for key in ENTRY_KEYS:
            if key not in entry:
                problems.append(f"observe(): {name} has no {key!r}")
        if not isinstance(entry.get("extra", {}), dict):
            problems.append(f"observe(): {name}: extra must be a dict")
    if not isinstance(obs.get("changes", []), list):
        problems.append("observe(): changes must be a list")
    return problems


def check_adapter(adapter, act=True):
    """A list of contract problems, empty when the adapter conforms."""
    problems = []
    profile = adapter.describe()
    problems += check_profile(profile)
    problems += check_observation(profile, adapter.observe(5.0))
    capabilities = profile.get("capabilities") or {}
    if capabilities.get("probe", True):
        probe = adapter.probe()
        if not isinstance(probe.get("steps"), list):
            problems.append("probe(): no steps list")
        for step in probe.get("steps") or []:
            if "step" not in step or "ok" not in step:
                problems.append("probe(): every step needs 'step' and 'ok'")
                break
    first = (profile.get("components") or [{}])[0].get("name")
    if first is not None:
        records = adapter.logs(first, 60.0, 5)
        if not isinstance(records, list):
            problems.append("logs(): must return a list")
        elif any("t" not in r for r in records):
            problems.append("logs(): every record needs 't'")
    if act and capabilities.get("act", True) and first is not None:
        try:
            answer = adapter.act("not-an-action", first, {})
        except Exception as exc:   # act() must never raise
            problems.append(f"act(): raised {type(exc).__name__} instead of refusing")
        else:
            if answer.get("ok") or not answer.get("refused"):
                problems.append("act(): an action outside the six must come back refused")
    return problems


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_verdict(verdict, impact=True):
    """A list of contract problems in a checker's verdict (CONTRACT.md section 10), empty when it has every key
    eval/ reads. impact=False for a verdict taken without since_t, which has no impact."""
    problems = []
    for key in ("recovered", "slo_ok"):
        if not isinstance(verdict.get(key), bool):
            problems.append(f"verdict: {key} must be true or false")
    journeys = verdict.get("journeys") or {}
    for key in ("n", "ok"):
        if not _count(journeys.get(key)):
            problems.append(f"verdict: journeys.{key} must be a whole number")
    for key in ("success_rate", "p95_ms"):
        if key not in journeys or not (journeys[key] is None or _number(journeys[key])):
            problems.append(f"verdict: journeys.{key} must be a number or null")
    integrity = verdict.get("integrity") or {}
    if not isinstance(integrity.get("ok"), bool):
        problems.append("verdict: integrity.ok must be true or false")
    operations = integrity.get("for_operations")
    if not isinstance(operations, list) or not all(isinstance(item, dict) and item.get("kind") for item in operations):
        problems.append("verdict: integrity.for_operations must be a list of items, each with a kind")
    if not _count(integrity.get("harmful_quarantines")):
        problems.append("verdict: integrity.harmful_quarantines must be a whole number")
    if impact:
        found = verdict.get("impact") or {}
        for key in ("breach_seconds", "time_to_mitigate_s"):
            if not _number(found.get(key)) or found[key] < 0:
                problems.append(f"verdict: impact.{key} must be seconds, 0 or more")
        if not _count(found.get("failed_journeys")):
            problems.append("verdict: impact.failed_journeys must be a whole number")
        if not isinstance(found.get("mitigation_censored"), bool):
            problems.append("verdict: impact.mitigation_censored must be true or false")
    return problems
