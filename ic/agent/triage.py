"""Triage: from the survey to an ordered plan of fixes.

The model names the faults and a fix for each (prompts.ASSESS_SCHEMA). Code
then checks the answer against the profile, accounts for every fault finding,
and orders the fixes:

    upstream first   a fix on a component others depend on comes before a fix on its callers
    then WSJF        weighted shortest job first: impact_weight / the action's est_seconds

The fifo ablation keeps the model's own order instead.
"""

import time

from ic.contract import ACTIONS, ROOT_CAUSE_CLASSES
from ic.agent import prompts, survey as abcde_survey

LOG_COMPONENTS = 4        # read logs for at most this many components with fault findings
LOG_LINES = 12            # distinct log lines kept per component


# ----- what the model reads -----

def log_lines(records, now=None, limit=LOG_LINES):
    """Warnings and errors from one component's logs, newest last, repeats counted. No field names assumed."""
    now = now or time.time()
    seen, order = {}, []
    for record in records:
        if "raw" in record:
            text = str(record["raw"])
            if not any(word in text.lower() for word in ("warn", "error", "fail", "exception", "refused", "timeout")):
                continue
        else:
            level = str(record.get("level", "")).upper()
            if level and level not in ("WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"):
                continue
            text = " ".join(f"{k}={v}" for k, v in record.items() if k not in ("t", "component"))
        text = text[:300]
        if text not in seen:
            order.append(text)
            seen[text] = {"n": 0, "t": record.get("t")}
        seen[text]["n"] += 1
        seen[text]["t"] = record.get("t") or seen[text]["t"]
    out = []
    for text in order[-limit:]:
        t = seen[text]["t"]
        age = f"{now - t:.0f} s ago" if isinstance(t, (int, float)) else "time unknown"
        repeat = f" (x{seen[text]['n']})" if seen[text]["n"] > 1 else ""
        out.append(f"  [{age}]{repeat} {text}")
    return out


def assess_message(profile, findings, probe, logs_by_component, containment=None, history=None):
    """The user message for the assessment call."""
    parts = ["Survey (ABCDE order):", abcde_survey.table(findings)]
    if probe:
        steps = ", ".join(f"{s.get('step')}={'ok' if s.get('ok') else 'FAIL'}" for s in probe.get("steps", []))
        parts.append(f"\nProbe of the {probe.get('journey')} journey: {steps}")
        for step in probe.get("steps", []):
            if not step.get("ok"):
                parts.append(f"  first failing step '{step.get('step')}': {step.get('detail', '')}")
                break
    for component, lines in logs_by_component.items():
        parts.append(f"\nRecent warnings and errors from {component}:")
        parts.extend(lines or ["  (none)"])
    if containment:
        parts.append(f"\nAlready done to contain the incident: {containment}")
    if history:
        parts.append("\nActions taken so far in this incident:")
        parts.extend(f"  {line}" for line in history)
    parts.append("\nGive every fault, its evidence and its fix. Account for every FAULT finding id.")
    return "\n".join(parts)


# ----- checking the model's answer -----

def check_assessment(answer, profile, findings):
    """Keep what fits the profile. Returns (faults, notes, missing_ids)."""
    components = {c["name"]: c for c in profile.get("components", [])}
    notes, faults = [], []
    for fault in answer.get("faults") or []:
        target = fault.get("target")
        if target not in components:
            notes.append(f"ignored a fault on unknown component {target!r}")
            continue
        cls = fault.get("class") if fault.get("class") in ROOT_CAUSE_CLASSES else None
        fixes = []
        for fix in fault.get("fix") or []:
            action, where = fix.get("action"), fix.get("target") or target
            if action == "escalate":
                fixes.append({**fix, "target": where if where in components else target})
            elif action not in ACTIONS or where not in components:
                notes.append(f"dropped fix {action} on {where}: not an action on a known component")
            elif action not in components[where].get("actions", []):
                notes.append(f"dropped fix {action} on {where}: not allowed there")
            else:
                fixes.append({**fix, "target": where})
        faults.append({**fault, "class": cls, "fix": fixes})
    fault_ids = {f["id"] for f in abcde_survey.faults(findings)}
    covered = {i for f in faults for i in (f.get("explains") or [])}
    covered |= {d.get("finding") for d in answer.get("dismissed") or []}
    missing = sorted(fault_ids - covered)
    return faults, notes, missing


def root_causes(faults):
    return [{"target": f["target"], "class": f["class"], "confidence": f.get("confidence"),
             "evidence": f.get("evidence", "")} for f in faults if f.get("class")]


# ----- ordering -----

def dependents(profile):
    """{component: how many components depend on it, directly or not}."""
    callers = {c["name"]: set() for c in profile.get("components", [])}
    for c in profile.get("components", []):
        for dep in c.get("depends_on") or []:
            callers.setdefault(dep, set()).add(c["name"])
    out = {}
    for name in callers:
        seen, stack = set(), list(callers[name])
        while stack:
            caller = stack.pop()
            if caller not in seen:
                seen.add(caller)
                stack.extend(callers.get(caller, ()))
        out[name] = len(seen - {name})
    return out


def plan(faults, profile, order="triage"):
    """[(fault, fix)] in the order they are carried out. Escalations come after every action."""
    steps = [(i, fault, fix) for i, fault in enumerate(faults) for fix in fault.get("fix") or []]
    actions = [s for s in steps if s[2]["action"] != "escalate"]
    escalations = [s for s in steps if s[2]["action"] == "escalate"]
    if order == "triage":
        upstream = dependents(profile)
        weights = {c["name"]: float(c.get("impact_weight", 1.0) or 0.0) for c in profile.get("components", [])}
        seconds = {name: float(spec.get("est_seconds") or 1.0) for name, spec in (profile.get("actions") or {}).items()}

        def key(step):
            index, fault, fix = step
            # Fixes for one fault stay in the model's order (restart, then quarantine, say).
            return (-upstream.get(fault["target"], 0),
                    -(weights.get(fault["target"], 1.0) / max(seconds.get(fix["action"], 1.0), 0.1)),
                    index)
        firsts = {}
        for step in actions:
            firsts.setdefault(step[0], step)
        fault_order = sorted(firsts.values(), key=key)
        actions = [s for first in fault_order for s in actions if s[0] == first[0]]
    return [(fault, fix) for _, fault, fix in actions + escalations]
