"""A small operator runbook: observe, take the first matching fix, then check again.

The six rules use component kinds and the public adapter fields. They do not
know the target system's names or its private state. A changed release or
setting is evidence only when the same component is also behaving badly.
"""

from time import monotonic, sleep, time

from ic.contract import GUARD_MAX_ACTIONS, GUARD_MAX_REPEATS, empty_result
from ic.guard import Guard, StepLimit


class _BudgetReached(Exception):
    """An internal stop signal; the caller still receives a complete handover."""


def _number(value):
    return value if isinstance(value, (int, float)) else 0.0


def _bad(metrics, baseline):
    """A meaningful error/reject increase or a worker's stalled queue."""
    extra = metrics.get("extra") or {}
    return (
        _number(metrics.get("error_rate")) > max(0.05, _number(baseline.get("error_rate")) + 0.05)
        or _number(metrics.get("reject_rate")) > max(0.05, _number(baseline.get("reject_rate")) + 0.05)
        or (_number(extra.get("queue_depth")) > 0
            and _number(extra.get("oldest_pending_s")) >= 3
            and _number(extra.get("processed_per_s")) == 0)
    )


def _changes(observation, name, kind):
    """Keep unresolved changes; an operator's undo closes the earlier change."""
    changes = [c for c in observation.get("changes", [])
               if c.get("component") == name and c.get("kind") == kind]
    current = {}
    for change in sorted(changes, key=lambda c: c.get("t", 0)):
        detail = change.get("detail") or {}
        key = detail.get("key") if kind == "config" else kind
        if detail.get("revert") or detail.get("rollback"):
            current.pop(key, None)
        elif change.get("actor") != "incident-commander":
            current[key] = change
    return list(current.values())


def _upstream_bad(component, observation):
    """Avoid blaming a harmless deployment for a visibly failing dependency."""
    all_metrics = observation.get("components", {})
    metrics = all_metrics.get(component["name"], {})
    edges = (metrics.get("extra") or {}).get("dependencies", {})
    for name in component.get("depends_on", []):
        upstream = all_metrics.get(name, {})
        extra = upstream.get("extra") or {}
        if upstream.get("up") is False or extra.get("lock_holders"):
            return True
        if _number((edges.get(name) or {}).get("error_rate")) > 0.05:
            return True
    return False


def _candidate(action, component, cause, reason, params=None):
    return {"action": action, "target": component["name"], "params": params or {},
            "class": cause, "reason": reason}


def _rules(profile, observation):
    """Six fixed rules, checked in this order; component order is also fixed."""
    components = profile.get("components", [])
    metrics = observation.get("components", {})
    baseline = observation.get("baseline", {})
    candidates = []

    # 1. A held datastore lock plus blocked writes calls for releasing the lock.
    for comp in components:
        m = metrics.get(comp["name"], {})
        extra = m.get("extra") or {}
        holders = extra.get("lock_holders") or []
        if (comp.get("kind") == "datastore" and "release_lock" in comp.get("actions", [])
                and holders and (_number(extra.get("write_errors")) > 0
                                 or any(_number(h.get("held_s")) >= 5 for h in holders))):
            candidates.append(_candidate("release_lock", comp, "lock_held", "A held lock is blocking writes."))

    # 2. New release + local errors, without a failing dependency: roll back.
    for comp in components:
        name = comp["name"]
        m, base = metrics.get(name, {}), baseline.get(name, {})
        changed = m.get("release") is not None and m.get("release") != base.get("release")
        if ("rollback" in comp.get("actions", []) and changed
                and _bad(m, base) and not _upstream_bad(comp, observation)
                and (_changes(observation, name, "deploy") or base.get("release") is not None)):
            candidates.append(_candidate("rollback", comp, "bad_release", "A changed release coincides with local failures."))

    # 3. New settings + rejects, errors or a stalled queue: undo that setting.
    for comp in components:
        name = comp["name"]
        m, base = metrics.get(name, {}), baseline.get(name, {})
        changes = _changes(observation, name, "config")
        if "revert_config" not in comp.get("actions", []) or not _bad(m, base):
            continue
        if changes:
            # A drastic reduction or zero is more suspicious than a small harmless change.
            def priority(change):
                detail = change.get("detail") or {}
                before, after = detail.get("from"), detail.get("to")
                severe = (isinstance(before, (int, float)) and before > 0
                          and isinstance(after, (int, float)) and after < before / 10)
                return severe, change.get("t", 0)
            change = max(changes, key=priority)
            key = (change.get("detail") or {}).get("key")
            params = {"key": key} if key is not None else {}
            candidates.append(_candidate("revert_config", comp, "bad_config", "A setting change coincides with degraded service.", params))
        elif (profile.get("capabilities", {}).get("changes") is False
              and base.get("config_version") is not None
              and m.get("config_version") != base.get("config_version")):
            candidates.append(_candidate("revert_config", comp, "bad_config", "Settings differ from the healthy baseline."))

    # 4. A crashed or unresponsive process, without an explicit stop: restart.
    for comp in components:
        name = comp["name"]
        m = metrics.get(name, {})
        extra = m.get("extra") or {}
        stopped = _changes(observation, name, "stop")
        if ("restart" in comp.get("actions", []) and comp.get("kind") not in ("external", "job")
                and (m.get("up") is False or extra.get("not_answering") is True)
                and not (comp.get("kind") == "worker" and stopped)):
            candidates.append(_candidate("restart", comp, "process_down", "The process is down or is not answering."))

    # 5. A worker stopped by an operator is brought back with the same restart.
    for comp in components:
        name = comp["name"]
        if (comp.get("kind") == "worker" and "restart" in comp.get("actions", [])
                and metrics.get(name, {}).get("up") is False
                and _changes(observation, name, "stop")):
            candidates.append(_candidate("restart", comp, "process_down", "A stopped worker cannot drain its queue."))

    # 6. A slow/failing dependency link with a usable standby: switch callers.
    for comp in components:
        name = comp["name"]
        extra = metrics.get(name, {}).get("extra") or {}
        if (comp.get("kind") != "dependency" or not comp.get("standby")
                or "failover" not in comp.get("actions", []) or extra.get("active") == "standby"
                or metrics.get(comp["standby"], {}).get("up") is False):
            continue
        for caller in components:
            edge = ((metrics.get(caller["name"], {}).get("extra") or {}).get("dependencies") or {}).get(name)
            if name not in caller.get("depends_on", []) or not edge:
                continue
            if (_number(edge.get("error_rate")) > 0.05
                    or _number(edge.get("p95_ms")) > _number(profile.get("slo", {}).get("p95_ms", 1000))):
                candidates.append(_candidate("failover", comp, "dependency_slow", "Callers see failures or excessive delay on this dependency.", {"to": "standby"}))
                break
    return candidates


def _action_record(proposal, **updates):
    record = {"t": time(), "action": proposal["action"], "target": proposal["target"],
              "params": proposal["params"], "reason": proposal["reason"], "sent": False,
              "declined": False, "ok": False, "refused": False, "refused_reason": None, "detail": ""}
    record.update(updates)
    return record


def run_incident(adapter, *, budget_s=90.0, max_steps=40, model=None,
                 log=None, seed=0, mode="auto", confirm=None, **_):
    """Run fixed rules through the safety wrapper; no model or private data is used."""
    result = empty_result("runbook", mode)
    result["t_start"] = time()
    deadline = monotonic() + max(0.0, budget_s)
    guarded = adapter if isinstance(adapter, Guard) else Guard(adapter, mode=mode, confirm=confirm, max_steps=max_steps)
    profile, observation, probe = {}, {}, {}
    steps, streak, streak_start = 0, 0, None
    previous, attempts = None, {}

    def trace(phase, kind, name, summary):
        entry = {"t": time() - result["t_start"], "phase": phase, "kind": kind, "name": name, "summary": summary}
        result["trace"].append(entry)
        if log is not None:
            log(dict(entry))

    def call(name, *args, **kwargs):
        nonlocal steps
        if steps >= max_steps or monotonic() >= deadline:
            raise _BudgetReached
        steps += 1
        value = getattr(guarded, name)(*args, **kwargs)
        trace("verify" if result["actions"] else "survey", "tool", name, "Read the current system." if name != "act" else "Requested a bounded action.")
        if name != "act" and monotonic() >= deadline:
            raise _BudgetReached
        return value

    def wait(seconds):
        remaining = deadline - monotonic()
        if seconds >= remaining:
            if remaining > 0:
                sleep(remaining)
            raise _BudgetReached
        sleep(max(0.0, seconds))

    def diagnose(proposal):
        pair = (proposal["target"], proposal["class"])
        if pair not in {(r["target"], r["class"]) for r in result["root_causes"]}:
            result["root_causes"].append({"target": pair[0], "class": pair[1], "confidence": 0.8, "evidence": proposal["reason"]})

    def escalate(reason):
        failed = [c["name"] for c in profile.get("components", [])
                  if c.get("kind") == "external" and (
                      observation.get("components", {}).get(c["name"], {}).get("up") is False
                      or _bad(observation.get("components", {}).get(c["name"], {}), {}))]
        for name in failed:
            diagnose({"target": name, "class": "external_outage", "reason": "The external component is failing from its callers' view."})
        if not failed:
            failed = list(dict.fromkeys(s["component"] for s in probe.get("steps", [])
                                       if s.get("ok") is False and s.get("component")))
        contacts = profile.get("escalation_contacts") or []
        contact = next((c.get("role") for c in contacts if set(c.get("for", [])) & set(failed)), None)
        result["escalation"] = {"components": failed, "class": "external_outage" if failed and all(
            any(c["name"] == name and c.get("kind") == "external" for c in profile.get("components", [])) for name in failed) else None,
            "reason": reason, "urgency": "now", "to": contact, "ask": "Investigate the failing components and restore service."}
        result["outcome"] = "escalated"

    try:
        profile = call("describe")
        # Respect a supplied wrapper's mode and the target's advertised access cap.
        modes = {"advise": 0, "confirm": 1, "auto": 2}
        mode = min((mode, getattr(guarded, "mode", mode), profile.get("capabilities", {}).get("max_mode", "auto")), key=lambda m: modes[m])
        if profile.get("capabilities", {}).get("act") is False:
            mode = "advise"
        result["mode"] = mode
        window_s = max(10.0, profile.get("capabilities", {}).get("min_window_s", 2.0))
        while True:
            observation = call("observe", window_s=window_s)
            probe = call("probe")
            candidates = _rules(profile, observation)
            if mode == "advise":
                for order, proposal in enumerate(candidates, 1):
                    diagnose(proposal)
                    result["proposed_actions"].append(_action_record(proposal, order=order, detail="Proposed only; no command was sent."))
                result["outcome"] = "advised"
                break
            # Avoid both consecutive repeats and refusals at the wrapper's limits.
            proposal = next((p for p in candidates if (p["action"], p["target"]) != previous
                             and attempts.get((p["action"], p["target"]), 0) < GUARD_MAX_REPEATS), None)
            if proposal is not None and len(result["actions"]) < GUARD_MAX_ACTIONS:
                diagnose(proposal)
                trace("triage", "note", "first_matching_rule", proposal["reason"])
                action_key = proposal["action"], proposal["target"]
                previous = action_key
                attempts[action_key] = attempts.get(action_key, 0) + 1
                record = _action_record(proposal)
                # A target can cap auto access at confirm even when its wrapper
                # was constructed with auto. Apply that stricter cap ourselves.
                if mode == "confirm" and getattr(guarded, "mode", mode) != "confirm":
                    if confirm is None or not confirm({k: proposal[k] for k in ("action", "target", "params", "reason")}):
                        record.update(declined=True, detail="The proposed action was not confirmed.")
                        result["actions"].append(record)
                        escalate("The proposed correction was not confirmed.")
                        break
                response = call("act", proposal["action"], proposal["target"], proposal["params"], proposal["reason"])
                refused = bool(response.get("refused"))
                declined = bool(response.get("declined")) or response.get("refused_reason") == "declined"
                record.update({k: response[k] for k in ("ok", "refused", "refused_reason", "detail") if k in response})
                record.update(sent=not refused and not declined, declined=declined)
                record["ok"] = bool(record["ok"] and record["sent"])
                result["actions"].append(record)
                if record["sent"] and result["t_first_action"] is None:
                    result["t_first_action"] = record["t"]
                trace("remediate", "action", proposal["action"], proposal["reason"])
                if monotonic() >= deadline:
                    raise _BudgetReached
                if refused or declined:
                    if response.get("refused_reason") == "step_limit":
                        raise _BudgetReached
                    escalate("The proposed correction was declined or refused; human attention is required.")
                    break
                streak, streak_start = 0, None
                comp = next(c for c in profile["components"] if c["name"] == proposal["target"])
                seconds = comp.get("action_seconds", {}).get(proposal["action"], profile.get("actions", {}).get(proposal["action"], {}).get("est_seconds", 1.0))
                wait(float(seconds))
                continue
            if probe.get("ok") is True and not candidates:
                if not result["actions"]:
                    result["outcome"] = "no_incident"
                    break
                streak += 1
                if streak_start is None:
                    streak_start = monotonic()
                trace("verify", "note", "consecutive_pass", f"Successful probe {streak}; checking a ten-second window.")
                if streak >= 3 and monotonic() - streak_start >= 10:
                    result["outcome"] = "recovered"
                    break
                wait(5.0)
            else:
                escalate("No untried safe runbook rule can restore the failing journey.")
                break
    except (StepLimit, _BudgetReached):
        result["outcome"] = "budget_exhausted"
    result["t_declared"] = time()
    causes = "; ".join(f"{r['target']}: {r['class']}" for r in result["root_causes"]) or "No recognised cause."
    result["sbar"] = {
        "situation": f"The runbook ended with {result['outcome']}.",
        "background": f"Surveyed {len(profile.get('components', []))} components; attempted {len(result['actions'])} bounded actions.",
        "assessment": causes,
        "recommendation": ("Follow the proposed action plan and verify recovery." if mode == "advise" else
                           "Continue monitoring the system." if result["outcome"] in ("recovered", "no_incident") else
                           "A human operator should investigate the remaining symptoms."),
    }
    trace("hand_over", "note", "sbar", result["sbar"]["situation"])
    return result
