"""Hand over: the SBAR note for the engineer who takes over, and the escalation record.

The model writes the note when there is time for one more call; otherwise, or
if the call fails, a template writes it from the same facts. Either way the
handover is written inside the budget.
"""

from ic.agent import prompts

MODEL_SBAR_MIN_S = 10.0     # below this much budget, use the template


def escalation(fault, fix, profile, journey_down):
    """The escalation record for one fault that needs a person (CONTRACT.md section 9)."""
    component = next((c for c in profile.get("components", []) if c["name"] == fix.get("target")), {})
    external = component.get("kind") == "external"
    role = next((c.get("role") for c in profile.get("escalation_contacts") or []
                 if component.get("name") in (c.get("for") or [])), None)
    return {"components": [fix.get("target") or fault.get("target")],
            "class": fault.get("class"),
            "reason": fault.get("evidence") or fix.get("note") or "no allowed action fixes this fault",
            "urgency": "now" if journey_down or fault.get("class") in ("external_outage", "resource_exhaustion")
                       else "soon",
            "to": role or component.get("owner") or ("the organisation that runs " + component["name"] if external
                                                     else "the on-call engineer"),
            "ask": fix.get("note") or "investigate and fix; the incident commander has no safe action for this"}


def merge_escalations(records):
    """One escalation for the incident: every component, the most urgent urgency."""
    if not records:
        return None
    first = dict(records[0])
    if len(records) > 1:
        first["components"] = sorted({c for r in records for c in r["components"]})
        first["class"] = records[0]["class"] if len({r["class"] for r in records}) == 1 else None
        first["reason"] = "; ".join(r["reason"] for r in records)
        first["ask"] = "; ".join(r["ask"] for r in records)
        first["urgency"] = "now" if any(r["urgency"] == "now" for r in records) else "soon"
        first["to"] = "; ".join(sorted({r["to"] for r in records}))
    return first


def facts(result, profile, summary=""):
    """Plain-text facts for the note: outcome, causes, actions, escalation."""
    lines = [f"System: {profile.get('system')}. Outcome: {result['outcome']}. Mode: {result['mode']}."]
    if summary:
        lines.append(f"Assessment summary: {summary}")
    for cause in result.get("root_causes") or []:
        lines.append(f"Root cause: {cause['class']} on {cause['target']} (confidence {cause.get('confidence')}). "
                     f"Evidence: {cause.get('evidence', '')}")
    for record in result.get("actions") or []:
        state = ("done" if record.get("ok") else "failed") if record.get("sent") else \
            f"not sent ({record.get('refused_reason')})"
        lines.append(f"Action: {record['action']} on {record['target']} {record.get('params') or ''}: {state}. "
                     f"{record.get('detail', '')}")
    for record in result.get("proposed_actions") or []:
        lines.append(f"Proposed, not taken (advise mode): {record['action']} on {record['target']} "
                     f"{record.get('params') or ''}. Reason: {record.get('reason', '')}")
    if result.get("escalation"):
        e = result["escalation"]
        lines.append(f"Escalated ({e['urgency']}) to {e['to']}: {', '.join(e['components'])}. Ask: {e['ask']}")
    return "\n".join(lines)


def template(result, profile, summary=""):
    """The note without a model."""
    outcome = result["outcome"]
    causes = result.get("root_causes") or []
    sent = [a for a in result.get("actions") or [] if a.get("sent")]
    situation = {
        "recovered": "The system is serving normally again; the incident commander's sustained check passed.",
        "no_incident": "No fault was found: every component and the main journey looked normal.",
        "escalated": "Recovery was not confirmed. Part of the incident needs a person.",
        "advised": "Nothing was changed (advise mode). A plan is below for a person to carry out.",
        "budget_exhausted": "Recovery was not confirmed: the incident commander ran out of time.",
        "gave_up": "Recovery was not confirmed: the incident commander could not complete its assessment.",
    }.get(outcome, f"Outcome: {outcome}.")
    background = summary or ("; ".join(f"{c['class']} on {c['target']}" for c in causes) or "No cause identified.")
    assessment = "; ".join(f"{a['action']} on {a['target']}: {'done' if a.get('ok') else 'failed'}" for a in sent) \
        or "No action was taken."
    recommendation = []
    if result.get("escalation"):
        recommendation.append(f"{result['escalation']['to']}: {result['escalation']['ask']}")
    if result.get("proposed_actions"):
        recommendation.append("Carry out: " + "; ".join(f"{a['action']} on {a['target']}"
                                                         for a in result["proposed_actions"]))
    if outcome not in ("recovered", "no_incident"):
        recommendation.append("Check the system yourself before declaring it recovered.")
    recommendation.append("Review any money or data effects with the operations team.")
    return {"situation": situation, "background": background, "assessment": assessment,
            "recommendation": " ".join(recommendation)}


def write(incident, summary=""):
    """Fill result["sbar"]: the model when time allows, else the template."""
    result, profile = incident.result, incident.describe()
    note = None
    if incident.remaining() >= MODEL_SBAR_MIN_S:
        note = incident.ask("hand_over", "sbar", prompts.sbar_system(),
                            [{"role": "user", "content": facts(result, profile, summary)}],
                            prompts.SBAR_SCHEMA, effort="low", max_tokens=4000, keep_s=1.0)
    if not note or not all(isinstance(note.get(k), str) and note[k] for k in prompts.SBAR_SCHEMA["required"]):
        note = template(result, profile, summary)
        incident.note("hand_over", "note", "sbar", "handover written from the template")
    result["sbar"] = {k: note[k] for k in prompts.SBAR_SCHEMA["required"]}
    return result["sbar"]
