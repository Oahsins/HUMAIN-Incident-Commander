"""The two harness controls: do nothing, or apply the labelled fixes."""

import copy
import time

from ic.contract import empty_result

AI_ARMS = {"abcde", "naive_verify", "fifo", "react"}
ARMS = AI_ARMS | {"runbook", "noop", "oracle"}


def load_arm(name):
    """Import AI code only when requested; never read an arm's implementation."""
    if name == "noop":
        return noop
    if name == "runbook":
        try:
            from baselines.runbook import run_incident
        except ImportError:
            raise ValueError("runbook is not installed; merge the runbook pull request first") from None
        return run_incident
    if name in AI_ARMS:
        try:
            from ic.agent import load_arm as load_ai_arm
        except ImportError:
            raise ValueError("AI arms are not installed; merge the agent pull request first") from None
        return load_ai_arm(name)
    raise ValueError(f"unknown arm: {name}")


def noop(adapter, *, budget_s=90.0, max_steps=40, model=None, log=None, seed=0,
         mode="auto", confirm=None, **_):
    result = empty_result("noop", mode)
    result.update(outcome="no_incident", t_start=time.time(), t_declared=time.time())
    result["sbar"] = {"situation": "No intervention control.", "background": "No observations or actions.",
                      "assessment": "Recovery is decided by the independent checker.",
                      "recommendation": "Retain the checker verdict."}
    return result


def resolve_params(params, detail):
    """Runtime values are supplied by the matching manifest entry, never guessed."""
    out = copy.deepcopy(params or {})
    for key, value in out.items():
        if value is None:
            if key not in detail or detail[key] is None:
                raise ValueError(f"manifest does not supply oracle parameter {key}")
            out[key] = detail[key]
    return out


def oracle(adapter, *, root_causes, manifest, budget_s=90.0, max_steps=40,
           model=None, log=None, seed=0, mode="auto", confirm=None, **_):
    """Privileged control arm only: labels never reach a tested agent or runbook."""
    from ic.guard import Guard, StepLimit

    guarded = adapter if isinstance(adapter, Guard) else Guard(adapter, mode=mode, confirm=confirm, max_steps=max_steps)
    result = empty_result("oracle", mode)
    result["t_start"] = time.time()
    deadline = time.monotonic() + budget_s
    escalation = []
    try:
        profile = guarded.describe()
        components = {c["name"]: c for c in profile.get("components", [])}
        for cause in root_causes:
            result["root_causes"].append({k: cause[k] for k in ("target", "class")})
            match = next((m for m in manifest if (m.get("target"), m.get("class")) == (cause["target"], cause["class"])), None)
            if match is None:
                raise ValueError("oracle label has no matching manifest entry")
            pending = [cause["fix"]]
            while pending:
                fix = pending.pop(0)
                pending[0:0] = fix.get("then", [])
                if fix["action"] == "escalate":
                    escalation.append(fix["target"])
                    continue
                if time.monotonic() >= deadline:
                    result["outcome"] = "budget_exhausted"
                    return result
                action, target = fix["action"], fix["target"]
                params = resolve_params(fix.get("params"), match.get("detail", {}))
                record = {"t": time.time(), "action": action, "target": target, "params": params,
                          "reason": "Labelled oracle fix.", "sent": False, "declined": False,
                          "ok": False, "refused": False, "refused_reason": None, "detail": ""}
                if mode == "advise" or profile.get("capabilities", {}).get("max_mode") == "advise":
                    record["order"] = len(result["proposed_actions"]) + 1
                    result["proposed_actions"].append(record)
                    continue
                reply = guarded.act(action, target, params)
                record.update(reply)
                record["sent"] = not record.get("refused", False) and not record.get("declined", False)
                result["actions"].append(record)
                if record["sent"] and result["t_first_action"] is None:
                    result["t_first_action"] = record["t"]
                delay = components.get(target, {}).get("action_seconds", {}).get(action,
                    profile.get("actions", {}).get(action, {}).get("est_seconds", 0))
                remaining = max(0, deadline - time.monotonic())
                time.sleep(max(0, min(float(delay), remaining)))
                if float(delay) > remaining:
                    result["outcome"] = "budget_exhausted"
                    return result
                if not record.get("ok"):
                    result["outcome"] = "gave_up"
                    return result
        if escalation:
            result["escalation"] = {"components": sorted(set(escalation)), "class": None,
                "reason": "The labelled fault has no allowed fix.", "urgency": "now", "to": None,
                "ask": "Restore the affected external service."}
        result["outcome"] = "advised" if result["proposed_actions"] else "escalated" if escalation else "recovered"
    except StepLimit:
        result["outcome"] = "budget_exhausted"
    finally:
        result["t_declared"] = time.time()
        result["sbar"] = {"situation": "Labelled fixes applied as a validity control.",
            "background": "Fixes came from scenario labels and the injection manifest.",
            "assessment": result["outcome"], "recommendation": "Use the independent checker verdict."}
    return result
