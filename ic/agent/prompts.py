"""What the model is told, and the shape of the answers it must give.

Everything system-specific comes from the adapter's describe() profile, so the
same words work for any system: a practice system or one the organisers supply.
"""

import json

from ic.contract import ACTIONS, ROOT_CAUSE_CLASSES

CLASS_MEANINGS = {
    "process_down": "the component's process has stopped or crashed and is not serving",
    "bad_release": "a recent release of this component causes the failures; rollback fixes it",
    "bad_config": "a recent setting change on this component causes the failures; revert_config fixes it",
    "lock_held": "a session holds a datastore lock and blocks writes; release_lock on the datastore fixes it",
    "dependency_slow": "a dependency answers too slowly or fails while its callers are healthy; failover to its "
                       "standby fixes it when it has one",
    "poison_message": "one malformed work item crashes or blocks a worker every time; quarantine that item "
                      "(params.item), then restart the worker if it is down. Only an item the worker cannot read "
                      "is poison: an item that waits because a system after the worker refuses or times out is not",
    "stale_cache": "users are shown old data although their requests succeed, while the component's release and "
                   "settings are unchanged; restart clears it",
    "resource_exhaustion": "a component has run out of memory, disk, connections or threads; a restart buys time, "
                           "then escalate so a person can add capacity",
    "external_outage": "a component run by another organisation is failing; no allowed action fixes it, so escalate",
}

# Shared by every arm's instructions (the react arm states its own steps, but knows the same about faults).
HIDDEN_FAULTS = ("One fault can hide another. While a component is down or failing, the components after it get "
                 "little or no work, so their own faults show no symptom yet. A setting changed to a value that "
                 "cannot work (zero or negative where a positive amount is needed, a timeout or limit far below "
                 "what normal traffic needs) is a fault even before it shows a symptom.")

_PARAMS = {"type": "object", "additionalProperties": False, "required": ["to", "item", "key"],
           "properties": {"to": {"anyOf": [{"type": "string", "enum": ["standby", "primary"]}, {"type": "null"}]},
                          "item": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                          "key": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}

_FIX = {"type": "object", "additionalProperties": False, "required": ["action", "target", "params", "note"],
        "properties": {"action": {"type": "string", "enum": list(ACTIONS) + ["escalate"]},
                       "target": {"type": "string"},
                       "params": _PARAMS,
                       "note": {"type": "string"}}}

_FAULT = {"type": "object", "additionalProperties": False,
          "required": ["target", "class", "confidence", "evidence", "explains", "fix"],
          "properties": {"target": {"type": "string"},
                         "class": {"type": "string", "enum": list(ROOT_CAUSE_CLASSES)},
                         "confidence": {"type": "number"},
                         "evidence": {"type": "string"},
                         "explains": {"type": "array", "items": {"type": "string"}},
                         "fix": {"type": "array", "items": _FIX}}}

ASSESS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["healthy", "summary", "faults", "dismissed"],
    "properties": {
        "healthy": {"type": "boolean"},
        "summary": {"type": "string"},
        "faults": {"type": "array", "items": _FAULT},
        "dismissed": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["finding", "why"],
            "properties": {"finding": {"type": "string"}, "why": {"type": "string"}}}},
    },
}

SBAR_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["situation", "background", "assessment", "recommendation"],
    "properties": {k: {"type": "string"} for k in ("situation", "background", "assessment", "recommendation")},
}


def describe_system(profile):
    """The profile as plain text for a system prompt."""
    lines = [f"System: {profile.get('system')}."]
    slo = profile.get("slo") or {}
    if slo:
        lines.append(f"Service level: {slo.get('success_rate', 0):.0%} of journeys succeed, p95 under "
                     f"{slo.get('p95_ms')} ms.")
    for journey in profile.get("journeys", []):
        lines.append(f"Journey '{journey['name']}'{' (main)' if journey.get('default') else ''}: "
                     f"{journey.get('description', '')}")
    lines.append("Components (name, kind, depends on, allowed actions, description):")
    for c in profile["components"]:
        standby = f"; standby: {c['standby']}" if c.get("standby") else ""
        lines.append(f"- {c['name']} ({c['kind']}); depends on {', '.join(c.get('depends_on') or []) or 'nothing'}; "
                     f"actions: {', '.join(c.get('actions') or []) or 'none'}{standby}; {c.get('description', '')}")
    lines.append("Actions (six bounded, safe actions; nothing else can be sent):")
    for name, spec in (profile.get("actions") or {}).items():
        params = ", ".join(f"{k} ({v.get('description') or ' or '.join(v.get('enum', [])) or 'see description'})"
                           for k, v in (spec.get("params") or {}).items())
        lines.append(f"- {name}: {spec.get('description', '')} (takes about {spec.get('est_seconds', '?')} s"
                     + (f"; params: {params}" if params else "") + ")")
    if profile.get("forbidden"):
        lines.append("Never: " + "; ".join(profile["forbidden"]) + ".")
    return "\n".join(lines)


def classes_text():
    return "\n".join(f"- {name}: {meaning}" for name, meaning in CLASS_MEANINGS.items())


def assess_system(profile):
    return f"""You are the incident commander for a running software system. Find every fault behind the symptoms, and choose the safest fix for each one.

{describe_system(profile)}

Root-cause classes:
{classes_text()}

How to decide:
- The survey lists findings in ABCDE order (Access, Bottlenecks, Capacity, Dependencies, Events), each with an id. FAULT findings are symptoms. info findings are context, such as recent changes and busy jobs.
- Several faults can be present at once. List each one separately, in the order you found them. One fault can explain several findings: a stopped worker also explains its growing backlog.
- A change made to the failing component shortly before its symptoms is strong evidence. A change with no symptom is usually not a fault: routine tuning (a slightly different interval, size or timeout) is normal. A job that is not running is normal.
- {HIDDEN_FAULTS} List it, with its fix.
- The target is the component where the fix is applied. Use only the actions listed for that component. Params: failover needs "to" ("standby", or "primary" to go back); quarantine needs "item" (the id of the work item to set aside, from the findings or logs); revert_config may name the setting in "key" (otherwise the newest change not made by the incident commander is undone); every other param is null.
- If no allowed action fixes a fault, give the single fix action "escalate", with the component as its target, and say in its note what a person, or the organisation that runs the component, must do. A restart that only buys time is followed by "escalate".
- Every FAULT finding id must appear in one fault's "explains", or in "dismissed" with the reason it is not a fault.
- If the main journey passes and nothing is wrong, answer healthy=true with no faults. Never act on a healthy component.
- confidence is a number from 0 to 1. Keep evidence to one or two sentences that quote the findings or log lines you relied on."""


def reassess_note():
    return ("This is a reassessment after remediation did not bring the system back. List every fault you now "
            "believe was present in this incident, including ones already fixed (give those an empty fix list). "
            "Give new fix steps only for faults that remain. Do not repeat an action that already failed to help "
            "unless the evidence shows it will work now.")


def sbar_system():
    return ("You write the handover at the end of an incident, for the engineer who takes over. Use SBAR: situation "
            "(what is happening now, one or two sentences), background (what changed and when), assessment (the "
            "root causes and what was done, with each action's result), recommendation (what the engineer must do "
            "next, including anything escalated and any money or data effects for the operations team to review). "
            "Plain English, short sentences: one or two per part, never more than three. Say only what the facts "
            "show, and name the specific components, settings, versions and items. The incident commander took "
            "every action itself; say so plainly rather than calling it automatic. If recovery was not confirmed, "
            "say so first. Leave out what did not happen.")


def compact(value, limit=2000):
    text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "...(cut)"
