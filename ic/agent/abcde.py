"""The incident commander: inject is someone else's job; this is survey, triage, remediate, verify, hand over.

    survey     describe, observe and probe; the ABCDE survey of every component; the one containment
               exception (fail a dependency over when the main journey cannot even start); logs for
               the components with fault findings
    triage     the model names every fault and a fix for each; code checks the answer against the
               profile and orders the fixes upstream first, then by WSJF
    remediate  each fix through the safety wrapper
    verify     sustained: clean looks in a row. If not clean, reassess once or twice with what is
               known now, while the budget allows
    hand over  the outcome, the escalation for anything a person must do, and the SBAR note

Two ablations share this module and change one switch each:
    naive_verify   one look straight after the last action instead of the sustained check
    fifo           fixes in the model's order instead of upstream first and WSJF
"""

from ic.agent import prompts, sbar, triage, verify
from ic.agent import survey as abcde_survey
from ic.agent.common import Incident, OutOfTime

SURVEY_WINDOW_S = 8.0
REASSESS_ROUNDS = 2
HANDOVER_KEEP_S = 12.0      # budget kept for the handover once the work is done
ASSESS_EFFORT = "medium"

ARMS = {
    "abcde": {"order": "triage", "verify": "sustained"},
    "naive_verify": {"order": "triage", "verify": "naive"},
    "fifo": {"order": "fifo", "verify": "sustained"},
}


def run_incident(adapter, *, budget_s=90.0, max_steps=40, model=None, log=None, seed=0, mode="auto", confirm=None,
                 arm="abcde", audit_path=None, **_):
    """Respond to one incident on the system behind `adapter`. Returns the result dict (CONTRACT.md section 9)."""
    settings = ARMS[arm]
    incident = Incident(adapter, arm, budget_s=budget_s, max_steps=max_steps, model=model, log=log, mode=mode,
                        confirm=confirm, seed=seed, audit_path=audit_path)
    state = {"summary": "", "escalations": [], "history": [], "declined": set(), "contained": None}
    try:
        _respond(incident, settings, state)
    except OutOfTime:
        if not incident.result["t_declared"]:
            incident.declare("budget_exhausted")
    except Exception as exc:   # never leave an incident without an outcome and a handover
        incident.note("hand_over", "note", "error", f"the incident commander failed: {type(exc).__name__}: {exc}")
        if not incident.result["t_declared"]:
            incident.declare("gave_up")
    finally:
        if not incident.result["t_declared"]:
            incident.declare(incident.result["outcome"])
        incident.result["escalation"] = sbar.merge_escalations(state["escalations"])
        if incident.result["escalation"] and incident.result["outcome"] in ("gave_up", "budget_exhausted"):
            incident.result["outcome"] = "escalated"
        try:
            sbar.write(incident, state["summary"])
        except OutOfTime:
            incident.result["sbar"] = sbar.template(incident.result, incident.profile or {}, state["summary"])
        incident.result["steps"] = incident.guard.steps
        incident.result["audit"] = incident.guard.audit
    return incident.result


def _survey(incident, phase="survey"):
    profile = incident.describe()
    obs = incident.tool(phase, "observe", SURVEY_WINDOW_S)
    probe = incident.tool(phase, "probe") if (profile.get("capabilities") or {}).get("probe", True) else None
    found = abcde_survey.survey(profile, obs, probe)
    incident.note(phase, "survey", "abcde", f"{len(abcde_survey.faults(found['findings']))} fault findings, "
                                            f"{len(found['findings'])} findings in all, "
                                            f"{found['components_checked']} components checked",
                  findings=found["findings"])
    return obs, probe, found


def _logs(incident, findings, phase="survey"):
    wanted = []
    for finding in abcde_survey.faults(findings):
        component = finding.get("component")
        if component and component not in wanted and (incident.components.get(component) or {}).get("kind") != "external":
            wanted.append(component)
    out = {}
    for component in wanted[:triage.LOG_COMPONENTS]:
        incident.need(HANDOVER_KEEP_S)
        out[component] = triage.log_lines(incident.tool(phase, "logs", component, 60.0, 200))
    return out


def _assess(incident, findings, probe, logs, containment, reassess=False, history=None):
    profile = incident.describe()
    system = prompts.assess_system(profile) + ("\n\n" + prompts.reassess_note() if reassess else "")
    message = triage.assess_message(profile, findings, probe, logs, containment, history)
    answer = incident.ask("triage", "reassess" if reassess else "assess", system,
                          [{"role": "user", "content": message}], prompts.ASSESS_SCHEMA, effort=ASSESS_EFFORT,
                          keep_s=HANDOVER_KEEP_S)
    if answer is None:
        return None
    faults, notes, missing = triage.check_assessment(answer, profile, findings)
    for text in notes:
        incident.note("triage", "note", "check", text)
    if missing and incident.remaining() > HANDOVER_KEEP_S + 25:
        incident.note("triage", "note", "coverage", f"findings not accounted for: {', '.join(missing)}; asking again")
        follow_up = (f"These FAULT findings are in neither 'explains' nor 'dismissed': {', '.join(missing)}. "
                     "Answer again in full, accounting for every FAULT finding.")
        second = incident.ask("triage", "coverage", system,
                              [{"role": "user", "content": message},
                               {"role": "assistant", "content": prompts.compact(answer, 6000)},
                               {"role": "user", "content": follow_up}],
                              prompts.ASSESS_SCHEMA, effort=ASSESS_EFFORT, keep_s=HANDOVER_KEEP_S)
        if second is not None:
            answer = second
            faults, notes, missing = triage.check_assessment(answer, profile, findings)
    if missing:
        incident.note("triage", "note", "coverage", f"still not accounted for: {', '.join(missing)}")
    return {"answer": answer, "faults": faults, "missing": missing}


def _params(incident, fix, obs):
    params = {k: v for k, v in (fix.get("params") or {}).items() if v is not None}
    if fix["action"] == "failover":
        params.setdefault("to", "standby")
    if fix["action"] == "quarantine" and "item" not in params:
        head = (((obs or {}).get("components") or {}).get(fix["target"], {}).get("extra") or {}).get("head_item") or {}
        if head.get("id") is not None:
            params["item"] = head["id"]
    return params


def _remediate(incident, steps, obs, state, journey_down):
    for fault, fix in steps:
        if fix["action"] == "escalate":
            record = sbar.escalation(fault, fix, incident.describe(), journey_down)
            state["escalations"].append(record)
            incident.note("remediate", "note", "escalate",
                          f"escalate {', '.join(record['components'])} ({record['urgency']}) to {record['to']}")
            continue
        params = _params(incident, fix, obs)
        if (fix["action"], fix["target"]) in state["declined"]:
            continue    # a person already said no to this; do not ask again
        if fix["action"] == "failover" and state["contained"] == (fix["target"], params.get("to")):
            continue    # already done as containment
        incident.need(HANDOVER_KEEP_S)
        record = incident.act("remediate", fix["action"], fix["target"], params,
                              reason=f"{fault.get('class')}: {fault.get('evidence', '')}"[:300])
        if record["declined"]:
            state["declined"].add((fix["action"], fix["target"]))
        state["history"].append(f"{record['action']} on {record['target']} {record['params'] or ''}: "
                                f"{'done' if record['ok'] else 'not done'} ({record['detail']})")
        if record["sent"] and record["ok"]:
            spec = (incident.describe().get("actions") or {}).get(fix["action"]) or {}
            incident.wait(min(2.0, float(spec.get("est_seconds") or 1.0)), keep_s=HANDOVER_KEEP_S)


def _respond(incident, settings, state):
    profile = incident.describe()
    obs, probe, found = _survey(incident)
    findings = found["findings"]

    containment = None
    candidate = abcde_survey.containment_candidate(profile, obs, probe, findings)
    if candidate:
        target, why = candidate
        record = incident.act("survey", "failover", target, {"to": "standby"}, reason=why, name="containment")
        containment = f"failover {target} to its standby ({record['detail'] or record['refused_reason']})"
        state["history"].append(containment)
        if record["sent"] and record["ok"]:
            state["contained"] = (target, "standby")

    if not abcde_survey.faults(findings) and not candidate:
        # Nothing wrong. One more look so a single quiet moment is not mistaken for health.
        incident.wait(2.0)
        clean, findings, probe = verify.look(incident, phase="survey")
        if clean:
            state["summary"] = "The survey found nothing abnormal in any component, and the main journey passed."
            incident.declare("no_incident")
            return

    logs = _logs(incident, findings)
    assessment = _assess(incident, findings, probe, logs, containment)
    if assessment is None:
        incident.declare("gave_up")
        return
    state["summary"] = assessment["answer"].get("summary", "")
    faults = assessment["faults"]
    incident.result["root_causes"] = triage.root_causes(faults)
    if not faults and not candidate:
        users_hit = [f for f in abcde_survey.faults(findings) if f["letter"] == "A"]
        if not users_hit:
            incident.declare("no_incident")
            return
        # Users are affected but no cause was found: never an all-clear. Hand it to a person.
        state["escalations"].append({
            "components": sorted({f["component"] for f in users_hit if f.get("component")}) or sorted(incident.components),
            "class": None, "reason": "symptoms without an identified cause: " + users_hit[0]["text"],
            "urgency": "now" if found["journey_down"] else "soon", "to": "the on-call engineer",
            "ask": "investigate; the incident commander found users affected but no cause it can act on"})
        incident.declare("escalated")
        return

    journey_down = found["journey_down"]
    steps = triage.plan(faults, profile, settings["order"])
    _remediate(incident, steps, obs, state, journey_down)
    if incident.mode == "advise":
        incident.declare("advised")
        return
    if steps and all(fix["action"] == "escalate" for _, fix in steps) and not state["contained"]:
        incident.declare("escalated")    # nothing the commander may do would change what a check sees
        return

    for round_number in range(REASSESS_ROUNDS + 1):
        ignore = {c for e in state["escalations"] for c in e["components"]}
        check = verify.sustained if settings["verify"] == "sustained" else verify.naive
        ok, findings = check(incident, incident.result["actions"], ignore_components=ignore,
                             keep_s=HANDOVER_KEEP_S)
        if ok:
            incident.declare("escalated" if any(e["urgency"] == "now" for e in state["escalations"]) else "recovered")
            return
        if round_number == REASSESS_ROUNDS or incident.remaining() < HANDOVER_KEEP_S + 30:
            break
        obs, probe, found = _survey(incident, phase="triage")
        logs = _logs(incident, found["findings"], phase="triage")
        assessment = _assess(incident, found["findings"], probe, logs, containment, reassess=True,
                             history=state["history"])
        if assessment is None:
            break
        state["summary"] = assessment["answer"].get("summary", "") or state["summary"]
        faults = assessment["faults"]
        known = {(c["target"], c["class"]) for c in incident.result["root_causes"]}
        incident.result["root_causes"] += [c for c in triage.root_causes(faults) if (c["target"], c["class"]) not in known]
        fresh = [(fault, fix) for fault, fix in triage.plan(faults, profile, settings["order"])
                 if fix["action"] == "escalate" or incident.guard.check(fix["action"], fix["target"]) is None]
        if not fresh:
            break
        _remediate(incident, fresh, obs, state, found["journey_down"])

    if not state["escalations"]:
        # Not recovered and nothing left to try: hand it to a person rather than walk away.
        state["escalations"].append({"components": sorted({c["target"] for c in incident.result["root_causes"]})
                                     or sorted(incident.components), "class": None,
                                     "reason": "the fixes did not bring the system back within the budget",
                                     "urgency": "now", "to": "the on-call engineer",
                                     "ask": "take over the incident; see the actions taken and the findings"})
    incident.declare("escalated")
