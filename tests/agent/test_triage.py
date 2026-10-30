"""Triage: the model's answer is checked against the profile, then ordered upstream first."""

from ic.agent import survey, triage
from tests.agent.fake_system import PROFILE, FakeSystem


def _fault(target, action, cls="process_down", explains=()):
    return {"target": target, "class": cls, "confidence": 0.8, "evidence": "", "explains": list(explains),
            "fix": [{"action": action, "target": target, "note": "", "params": {"to": None, "item": None, "key": None}}]}


def test_check_assessment_drops_what_the_profile_forbids():
    fake = FakeSystem({"web_down", "partner_down"})
    findings = survey.survey(PROFILE, fake.observe(8.0), fake.probe())["findings"]
    fault_ids = [f["id"] for f in survey.faults(findings)]
    answer = {"faults": [_fault("web", "restart", explains=fault_ids[:1]),
                         _fault("partner", "restart"),                   # not allowed on an external system
                         _fault("nowhere", "restart")],                  # not a component
              "dismissed": []}
    faults, notes, missing = triage.check_assessment(answer, PROFILE, findings)
    assert [f["target"] for f in faults] == ["web", "partner"]
    assert faults[1]["fix"] == []
    assert any("not allowed" in n for n in notes) and any("unknown component" in n for n in notes)
    assert missing == sorted(fault_ids[1:])


def test_unknown_class_becomes_none():
    answer = {"faults": [_fault("web", "restart", cls="gremlins")], "dismissed": []}
    faults, _, _ = triage.check_assessment(answer, PROFILE, [])
    assert faults[0]["class"] is None
    assert triage.root_causes(faults) == []


def test_dependents_counts_callers_transitively():
    counts = triage.dependents(PROFILE)
    assert counts["cache"] == 1 and counts["db"] == 1 and counts["web"] == 0


def test_plan_upstream_first_then_escalations_last():
    faults = [_fault("web", "restart"),
              {**_fault("partner", "escalate", cls="external_outage")},
              _fault("db", "release_lock", cls="lock_held")]
    order = [(f["target"], fix["action"]) for f, fix in triage.plan(faults, PROFILE, "triage")]
    assert order == [("db", "release_lock"), ("web", "restart"), ("partner", "escalate")]
    fifo = [(f["target"], fix["action"]) for f, fix in triage.plan(faults, PROFILE, "fifo")]
    assert fifo == [("web", "restart"), ("db", "release_lock"), ("partner", "escalate")]
