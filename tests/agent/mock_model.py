"""A rule-based stand-in for the model, so the agent's plumbing can be tested with no key and no network.

It reads the survey table the agent sends and answers in the assessment schema.
It is not clever: it knows the practice faults' signatures, which is enough to
drive the survey, triage, remediate, verify and hand-over steps end to end.
"""

import json
import re

from ic import llm

LINE = re.compile(r"^\s*\[(?P<id>[A-E]\d+)\] (?P<sev>FAULT|info ) (?:(?P<comp>[\w-]+): )?(?P<text>.*)$")


def _findings(text):
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            out.append({"id": m["id"], "fault": m["sev"] == "FAULT", "component": m["comp"], "text": m["text"]})
    return out


def _fix(action, target, note="", **params):
    return {"action": action, "target": target, "note": note,
            "params": {"to": params.get("to"), "item": params.get("item"), "key": params.get("key")}}


def assess(user_text):
    findings = _findings(user_text)
    faults_found = [f for f in findings if f["fault"]]
    changes = [f for f in findings if f["id"].startswith("E")]
    faults, explained = [], set()

    def add(target, cls, fixes, ids, evidence):
        faults.append({"target": target, "class": cls, "confidence": 0.8, "evidence": evidence,
                       "explains": sorted(set(ids)), "fix": fixes})
        explained.update(ids)

    by_comp = {}
    for f in faults_found:
        by_comp.setdefault(f["component"], []).append(f)
    for f in faults_found:
        comp, text = f["component"], f["text"]
        if f["id"] in explained:
            continue
        # an outage elsewhere: the other organisation's component is down or failing, or a caller sees it fail
        external = ("run by another organisation" in text and (text.startswith("down") or "of requests fail" in text)) or \
                   (f["id"][0] == "D" and text.startswith("down"))
        if external:
            add(comp, "external_outage", [_fix("escalate", comp, f"ask the operator of {comp} to restore service")],
                [x["id"] for x in faults_found if x["id"][0] in "BD" or x["component"] == comp], text)
        elif text.startswith("down"):
            add(comp, "process_down", [_fix("restart", comp)], [x["id"] for x in by_comp[comp]], text)
        elif "lock held by session" in text:
            add(comp, "lock_held", [_fix("release_lock", comp)],
                [x["id"] for x in faults_found if x["component"] in (comp, "payments", "gateway", "clearing")], text)
        elif text.startswith("calls to ") and " are slow" in text:
            dep = text.split()[2].rstrip(":")
            add(dep, "dependency_slow", [_fix("failover", dep, to="standby")], [f["id"]], text)
    for comp, items in by_comp.items():
        pending = [x for x in items if x["id"] not in explained]
        if not pending:
            continue
        change = next((c for c in reversed(changes) if c["component"] == comp), None)
        if change and " config by " in change["text"]:
            key = re.search(r"key=([\w.]+)", change["text"])
            add(comp, "bad_config", [_fix("revert_config", comp, key=key[1] if key else None)],
                [x["id"] for x in pending], change["text"])
        elif change and " deploy by " in change["text"]:
            add(comp, "bad_release", [_fix("rollback", comp)], [x["id"] for x in pending], change["text"])
    dismissed = [{"finding": f["id"], "why": "a knock-on effect of the faults above"}
                 for f in faults_found if f["id"] not in explained]
    return {"healthy": not faults, "summary": f"{len(faults)} fault(s) found by the test model",
            "faults": faults, "dismissed": dismissed}


def answer(system, messages, schema, purpose):
    if purpose in ("assess", "reassess", "coverage"):
        return json.dumps(assess(messages[0]["content"]))
    if purpose == "sbar":
        return json.dumps({"situation": "Test note.", "background": "Test background.",
                           "assessment": messages[0]["content"][:200], "recommendation": "Review the actions."})
    raise ValueError(f"the test model has no answer for {purpose}")


def install(name="rules"):
    llm.register_mock(name, answer)
    return f"mock:{name}"
