"""The react arm (an ablation): the same model, tools, budget, safety wrapper, sustained check and handover
as abcde, without the fixed ABCDE survey and the triage order. The model chooses every next step itself.

Each turn the model answers in REACT_SCHEMA: one tool call (observe, logs, probe, act), an escalation, or
"done". "done" starts the sustained check; if the check fails, the model is told so and carries on.
"""

from ic.contract import ACTIONS, ROOT_CAUSE_CLASSES
from ic.agent import prompts, sbar, triage, verify
from ic.agent import survey as abcde_survey
from ic.agent.common import Incident, OutOfTime

HANDOVER_KEEP_S = 12.0
EFFORT = "medium"

REACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["thought", "tool", "component", "window_s", "action", "target", "params", "root_causes", "note"],
    "properties": {
        "thought": {"type": "string"},
        "tool": {"type": "string", "enum": ["observe", "logs", "probe", "act", "escalate", "done"]},
        "component": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "window_s": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "action": {"anyOf": [{"type": "string", "enum": list(ACTIONS)}, {"type": "null"}]},
        "target": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "params": prompts._PARAMS,
        "root_causes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["target", "class", "confidence", "evidence"],
            "properties": {"target": {"type": "string"}, "class": {"type": "string", "enum": list(ROOT_CAUSE_CLASSES)},
                           "confidence": {"type": "number"}, "evidence": {"type": "string"}}}},
        "note": {"type": "string"},
    },
}


def system_prompt(profile):
    return f"""You are the incident commander for a running software system. An alert has fired. Find every fault, fix what the allowed actions can fix, and hand over anything they cannot.

{prompts.describe_system(profile)}

Root-cause classes:
{prompts.classes_text()}

Each turn, choose exactly one step:
- observe: metrics for every component over the last window_s seconds, with each component's warm-up baseline and recent changes.
- logs: recent log records of one component (set component).
- probe: one synthetic run of the main journey, step by step.
- act: one action (set action, target and params). Only the actions listed for a component can be sent. Params: failover needs "to"; quarantine needs "item"; revert_config may name "key"; otherwise null.
- escalate: hand a fault no allowed action fixes to a person (target = the component, note = what they must do).
- done: you believe the system is back. List every root cause you found in root_causes. A sustained check then runs; if it fails you are told and carry on.
Several faults can be present at once. A change made shortly before a component's symptoms is strong evidence. Never act on a healthy component. Keep thought to one or two sentences."""


def _escalation(reply, incident):
    target = reply.get("target") or reply.get("component")
    cause = next((c for c in reply.get("root_causes") or [] if c.get("target") == target), {})
    fault = {"target": target, "class": cause.get("class"), "evidence": reply.get("thought", "")}
    return sbar.escalation(fault, {"target": target, "note": reply.get("note", "")}, incident.describe(), True)


def _add_causes(incident, causes):
    known = {(c["target"], c["class"]) for c in incident.result["root_causes"]}
    for cause in causes or []:
        if cause.get("target") in incident.components and (cause["target"], cause["class"]) not in known:
            incident.result["root_causes"].append({k: cause.get(k) for k in ("target", "class", "confidence", "evidence")})
            known.add((cause["target"], cause["class"]))


def run_incident(adapter, *, budget_s=90.0, max_steps=40, model=None, log=None, seed=0, mode="auto", confirm=None,
                 audit_path=None, **_):
    incident = Incident(adapter, "react", budget_s=budget_s, max_steps=max_steps, model=model, log=log, mode=mode,
                        confirm=confirm, seed=seed, audit_path=audit_path)
    escalations, handoffs, summary = [], [], ""
    try:
        profile = incident.describe()
        system = system_prompt(profile)
        messages = [{"role": "user", "content": "An alert has fired on this system. Investigate and respond."}]
        while True:
            reply = incident.ask("triage", "react", system, messages, REACT_SCHEMA, effort=EFFORT,
                                 max_tokens=8000, keep_s=HANDOVER_KEEP_S)
            if reply is None:
                incident.declare("gave_up")
                break
            messages.append({"role": "assistant", "content": prompts.compact(reply, 3000)})
            tool, text = reply.get("tool"), ""
            incident.note("triage", "note", "react", f"{tool}: {reply.get('thought', '')}"[:300])
            if tool == "observe":
                window = reply.get("window_s") or 8.0
                text = prompts.compact(incident.tool("survey", "observe", max(2.0, min(float(window), 60.0))), 6000)
            elif tool == "logs":
                component = reply.get("component") or reply.get("target")
                if component not in incident.components:
                    text = f"there is no component named {component!r}"
                else:
                    lines = triage.log_lines(incident.tool("survey", "logs", component, 60.0, 200), limit=20)
                    text = "\n".join(lines) or "no warnings or errors"
            elif tool == "probe":
                text = prompts.compact(incident.tool("survey", "probe"), 3000)
            elif tool == "act":
                incident.need(HANDOVER_KEEP_S)
                record = incident.act("remediate", reply.get("action"), reply.get("target"),
                                      reply.get("params") or {}, reason=reply.get("thought", "")[:300])
                text = prompts.compact({k: record[k] for k in ("sent", "ok", "refused_reason", "detail")}, 1000)
            elif tool == "escalate":
                _add_causes(incident, reply.get("root_causes"))
                escalations.append(_escalation(reply, incident))
                text = "escalation recorded; carry on with anything the allowed actions can fix, or say done"
            elif tool == "done":
                _add_causes(incident, reply.get("root_causes"))
                summary = reply.get("note", "") or summary
                if incident.mode == "advise":
                    incident.declare("advised")
                    break
                ignore = {c for e in escalations for c in e["components"]}
                ok, findings = verify.sustained(incident, incident.result["actions"], ignore_components=ignore,
                                                keep_s=HANDOVER_KEEP_S)
                if ok:
                    sbar.settle_urgency(escalations, incident.result["actions"], findings)
                    handoffs = sbar.damage_handoffs(verify.damage(findings, ignore), incident.describe())
                    incident.declare("escalated" if any(e["urgency"] == "now" for e in escalations) else "recovered")
                    break
                if escalations and not [f for f in abcde_survey.faults(findings) if f.get("component") not in ignore]:
                    incident.declare("escalated")
                    break
                text = "the sustained check failed. Still abnormal:\n" + abcde_survey.table(findings)
            else:
                text = f"unknown step {tool!r}"
            messages.append({"role": "user", "content": f"Result of {tool}:\n{text}"})
    except OutOfTime:
        if not incident.result["t_declared"]:
            incident.declare("budget_exhausted")
    except Exception as exc:
        incident.note("hand_over", "note", "error", f"the incident commander failed: {type(exc).__name__}: {exc}")
        if not incident.result["t_declared"]:
            incident.declare("gave_up")
    finally:
        if not incident.result["t_declared"]:
            incident.declare(incident.result["outcome"])
        if escalations and incident.result["outcome"] in ("gave_up", "budget_exhausted"):
            incident.result["outcome"] = "escalated"
        incident.result["escalation"] = sbar.merge_escalations(
            escalations + handoffs + sbar.quarantine_handoffs(incident.result, incident.profile or {}))
        try:
            sbar.write(incident, summary)
        except OutOfTime:
            incident.result["sbar"] = sbar.template(incident.result, incident.profile or {}, summary)
        incident.result["steps"] = incident.guard.steps
        incident.result["audit"] = incident.guard.audit
    return incident.result
