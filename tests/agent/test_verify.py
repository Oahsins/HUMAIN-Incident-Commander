"""The sustained check's stopping rule, and what the handover is told about it."""

import pytest

from ic.agent import common, sbar, verify
from ic.contract import empty_result


class StubIncident:
    """Just enough of common.Incident for verify.sustained: a clock that never runs out and a trace."""

    def __init__(self):
        self.trace = []

    def describe(self):
        return {"actions": {"restart": {"est_seconds": 1}}}

    def wait(self, seconds, keep_s=0.0):
        pass

    def need(self, seconds):
        pass

    def note(self, phase, kind, name, summary, **data):
        self.trace.append({"t": float(len(self.trace)), "phase": phase, "kind": kind, "name": name,
                           "summary": summary})


def scripted_looks(monkeypatch, pattern):
    """Each look comes back clean ("C") or not ("F"), in this order."""
    looks = iter(pattern)
    calls = []

    def look(incident, ignore_components=(), **_):
        calls.append(1)
        clean = next(looks) == "C"
        findings = [] if clean else [{"id": "A1", "letter": "A", "component": "web", "severity": "fault",
                                      "text": "40% of requests fail (baseline 0%)"}]
        return clean, findings, None
    monkeypatch.setattr(verify, "look", look)
    return calls


@pytest.mark.parametrize("pattern, ok, looks", [("CC", True, 2), ("FCC", True, 3), ("FF", False, 2),
                                                 ("FCF", False, 3), ("CFCC", True, 4)])
def test_sustained_stops_after_two_misses_in_a_row(monkeypatch, pattern, ok, looks):
    calls = scripted_looks(monkeypatch, pattern + "C" * 5)
    incident = StubIncident()
    result, _ = verify.sustained(incident, [{"action": "restart", "sent": True}])
    assert result is ok and len(calls) == looks


def test_a_look_that_is_not_clean_says_what_is_still_wrong(monkeypatch):
    scripted_looks(monkeypatch, "FF")
    incident = StubIncident()
    verify.sustained(incident, [])
    assert "still abnormal: web: 40% of requests fail" in incident.trace[-1]["summary"]


def test_the_handover_hears_how_recovery_was_checked():
    result = empty_result("abcde", mode="auto")
    result["outcome"] = "recovered"
    result["trace"] = [{"t": 21.0, "phase": "verify", "kind": "note", "name": "check",
                        "summary": "look 2: clean (2 of 2 in a row)"}]
    text = sbar.facts(result, {"system": "fake"})
    assert "took the actions below itself" in text
    assert "2 of 2 in a row" in text and "1 look(s)" in text


def test_healthy_summary_names_what_was_seen(monkeypatch):
    from tests.agent import mock_model
    from tests.agent.fake_system import FakeSystem
    from ic.agent import load_arm
    monkeypatch.setattr(common, "SLEEP", lambda seconds: None)
    captured = {}
    real = sbar.facts

    def facts(result, profile, summary=""):
        captured["summary"] = summary
        return real(result, profile, summary)
    monkeypatch.setattr(sbar, "facts", facts)
    fake = FakeSystem(set())
    observe = fake.observe

    def with_a_harmless_change(window_s=10.0):
        obs = observe(window_s)
        obs["changes"].append({"id": "c-9", "t": obs["t"] - 5, "component": "web", "kind": "deploy",
                               "actor": "pipeline", "detail": {"from": "1.0", "to": "1.0.1"}})
        return obs
    fake.observe = with_a_harmless_change
    result = load_arm("abcde")(fake, model=mock_model.install(), budget_s=90.0)
    assert result["outcome"] == "no_incident" and fake.acts == []
    assert captured["summary"].startswith("The survey found nothing abnormal")
    assert "Seen, with no symptom: web:" in captured["summary"] and "deploy by pipeline" in captured["summary"]


def damage_finding(count):
    return {"id": "D1", "letter": "D", "component": "db", "severity": "fault",
            "text": f"data check failed: duplicate orders = {count}"}


def test_past_damage_does_not_block_recovery_but_growing_damage_does():
    assert verify.open_faults([damage_finding(3)]) == [damage_finding(3)]          # first look: not yet known
    known = verify.data_counts([damage_finding(3)])
    assert known == {("db", "duplicate orders"): 3.0}
    assert verify.open_faults([damage_finding(3)], tolerate=known) == []           # not growing: past damage
    assert verify.open_faults([damage_finding(4)], tolerate=known) == [damage_finding(4)]   # still happening


def test_sustained_passes_once_the_damage_stops_growing(monkeypatch):
    counts = iter([3, 3, 3])

    def look(incident, ignore_components=(), tolerate=None, **_):
        findings = [damage_finding(next(counts))]
        return not verify.open_faults(findings, ignore_components, tolerate), findings, None
    monkeypatch.setattr(verify, "look", look)
    ok, findings = verify.sustained(StubIncident(), [])
    assert ok and verify.damage(findings) == [damage_finding(3)]


def test_quarantines_and_damage_go_to_a_person():
    profile = {"components": [{"name": "worker"}, {"name": "db"}],
               "escalation_contacts": [{"role": "operations", "for": ["worker"]}]}
    result = {"actions": [{"action": "quarantine", "target": "worker", "params": {"item": 42}, "sent": True,
                           "ok": True},
                          {"action": "quarantine", "target": "worker", "params": {"item": 43}, "sent": False,
                           "ok": False}]}
    [record] = sbar.quarantine_handoffs(result, profile)
    assert record["urgency"] == "soon" and record["to"] == "operations" and "item 42" in record["ask"]
    [record] = sbar.damage_handoffs([damage_finding(3)], profile)
    assert record["components"] == ["db"] and record["to"] == "the operations team"
    assert "duplicate orders = 3" in record["reason"]


def test_a_page_becomes_a_follow_up_once_the_fix_held():
    def page(component):
        return {"components": [component], "class": None, "reason": "", "urgency": "now", "to": "x", "ask": ""}
    actions = [{"action": "failover", "target": "cache", "sent": True, "ok": True},
               {"action": "restart", "target": "web", "sent": True, "ok": False}]
    still = [{"id": "D1", "letter": "D", "component": "partner", "severity": "fault", "text": "down"}]
    cache, web, partner = page("cache"), page("web"), page("partner")
    sbar.settle_urgency([cache, web, partner], actions, still)
    assert cache["urgency"] == "soon"       # failed over and quiet now: the slow primary is follow-up work
    assert web["urgency"] == "now"          # the restart did not go through
    assert partner["urgency"] == "now"      # nothing could be done there, and it is still down
