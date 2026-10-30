"""The sustained check's stopping rule, and what the handover is told about it."""

import pytest

from ic.agent import common, sbar, survey, verify
from ic.contract import empty_result


class StubIncident:
    """Just enough of common.Incident for verify.sustained: a clock that runs out only when told to, and a trace."""

    def __init__(self, remaining=1000.0):
        self.trace = []
        self.left = remaining
        self.waits = []
        self.result = {"actions": [], "root_causes": []}

    def describe(self):
        return {"actions": {"restart": {"est_seconds": 1}}}

    def remaining(self):
        return self.left

    def wait(self, seconds, keep_s=0.0):
        seconds = min(seconds, self.left - keep_s)
        self.waits.append(seconds)
        self.left -= seconds + 0.001          # a sleep always overshoots a little

    def need(self, seconds):
        if self.left < seconds:
            raise common.OutOfTime()

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


def test_the_gap_shrinks_so_the_confirming_look_still_fits(monkeypatch):
    scripted_looks(monkeypatch, "CC")
    roomy = StubIncident()
    assert verify.sustained(roomy, [], keep_s=12.0)[0] and roomy.waits[-1] == verify.CHECK_GAP_S
    scripted_looks(monkeypatch, "CC")
    short = StubIncident(remaining=19.4)    # 18.4 s left after the 1 s settle and the first look
    assert verify.sustained(short, [], keep_s=12.0)[0]
    assert short.waits[-1] == pytest.approx(19.4 - 1.001 - 4 - 12 - verify.TIME_MARGIN_S)
    scripted_looks(monkeypatch, "CC")
    with pytest.raises(common.OutOfTime):  # not even the shortest gap and a look fit: stop, do not overrun
        verify.sustained(StubIncident(remaining=17.5), [], keep_s=12.0)


RESTARTED = {"up": True, "error_rate": 0.0, "extra": {"exits_15m": 3, "last_exit_s_ago": 20, "last_exit_code": 0}}


def test_exits_from_before_the_action_are_history_not_a_crash_loop():
    def signal(acted_ago):
        [(letter, severity, text)] = survey.component_signals("web", RESTARTED, {}, {"kind": "service"}, {},
                                                              acted_ago=acted_ago)
        return severity, text
    assert signal(None)[0] == "fault"                   # exiting again and again, and nothing done yet
    severity, text = signal(5.0)                        # restarted 5 s ago, after the last exit
    assert severity == "info" and "none since the action taken on it 5 s ago" in text
    assert signal(30.0)[0] == "fault"                   # exited again after the action: still a crash loop


def test_the_survey_knows_when_each_component_was_last_acted_on():
    profile = {"components": [{"name": "web", "kind": "service"}]}
    obs = {"t": 1000.0, "components": {"web": RESTARTED}, "baseline": {}}
    assert survey.faults(survey.survey(profile, obs, None)["findings"])
    assert not survey.faults(survey.survey(profile, obs, None, acted_ago={"web": 5.0})["findings"])
    assert verify.acted_ago([{"target": "web", "t": 990.0, "sent": True, "ok": True},
                             {"target": "web", "t": 995.0, "sent": True, "ok": True},
                             {"target": "db", "t": 996.0, "sent": True, "ok": False}], now=1000.0) == {"web": 5.0}


def test_a_page_for_a_component_that_recovered_with_the_other_fixes_is_dropped():
    def page(component, urgency="now"):
        return {"components": [component], "class": None, "reason": "", "urgency": urgency, "to": "x", "ask": ""}
    incident = StubIncident()
    incident.profile = {"components": [{"name": "worker", "depends_on": ["partner", "vendor"]}, {"name": "partner"},
                                       {"name": "vendor"}, {"name": "other", "depends_on": ["remote"]},
                                       {"name": "remote"}]}
    incident.result = empty_result("abcde", mode="auto")
    incident.result["actions"] = [{"action": "revert_config", "target": "worker", "sent": True, "ok": True}]
    incident.result["root_causes"] = [{"target": "partner", "class": "external_outage"},
                                      {"target": "worker", "class": "bad_config"}]
    last_look = [{"id": "D1", "letter": "D", "component": "vendor", "severity": "fault", "text": "down"},
                 {"id": "D2", "letter": "D", "component": "partner", "severity": "info", "text": "served normally"}]
    partner, vendor, worker, note, remote = (page("partner"), page("vendor"), page("worker"),
                                             page("partner", "soon"), page("remote"))
    escalations = [partner, vendor, worker, note, remote]
    assert sbar.withdraw_cleared(incident, escalations, last_look) == ["partner"]
    # still down / acted on (settle_urgency's job) / a follow-up / quiet, but nothing that calls it was fixed
    assert escalations == [vendor, worker, note, remote]
    assert incident.result["root_causes"] == [{"target": "worker", "class": "bad_config"}]
    incident.result["trace"] = incident.trace
    assert "Not escalated after all: no page for partner" in sbar.facts(incident.result, {"system": "fake"})


def test_when_nothing_is_left_to_try_and_users_get_through_it_checks_again(monkeypatch):
    from tests.agent import mock_model
    from tests.agent.fake_system import FakeSystem
    from ic.agent import load_arm
    monkeypatch.setattr(common, "SLEEP", lambda seconds: None)
    real, checks = verify.sustained, []

    def sustained(incident, actions, **kw):    # the first check fails on symptoms that are fading
        checks.append(1)
        return (False, []) if len(checks) == 1 else real(incident, actions, **kw)
    monkeypatch.setattr(verify, "sustained", sustained)
    fake = FakeSystem({"web_down"})
    result = load_arm("abcde")(fake, model=mock_model.install(), budget_s=90.0)
    assert len(checks) == 2 and result["outcome"] == "recovered" and result["escalation"] is None
    assert any(e["summary"].startswith("nothing new to try") for e in result["trace"])


def test_exits_without_a_time_do_not_break_the_survey():
    entry = {"up": True, "extra": {"exits_15m": 2}}
    [(letter, severity, text)] = survey.component_signals("web", entry, {}, {"kind": "service"}, {})
    assert severity == "info" and text == "process exited 2 time(s) in 15 min (exit code None)"


def run_capped(monkeypatch, **capabilities):
    from tests.agent import mock_model
    from tests.agent.fake_system import PROFILE, FakeSystem
    from ic.agent import load_arm
    monkeypatch.setattr(common, "SLEEP", lambda seconds: None)
    fake = FakeSystem({"web_down"})
    profile = {**PROFILE, "capabilities": {**PROFILE["capabilities"], **capabilities}}
    fake.describe = lambda: profile
    windows, observe = [], fake.observe
    fake.observe = lambda window_s=10.0: windows.append(window_s) or observe(window_s)
    return fake, windows, load_arm("abcde")(fake, model=mock_model.install(), budget_s=90.0)


@pytest.mark.parametrize("capabilities", [{"max_mode": "advise"}, {"act": False}])
def test_a_read_only_system_gets_advice_and_no_action(monkeypatch, capabilities):
    fake, _, result = run_capped(monkeypatch, **capabilities)
    assert result["mode"] == "advise" and result["outcome"] == "advised"
    assert fake.acts == [] and result["proposed_actions"]


def test_a_confirm_cap_with_nobody_to_ask_declines_every_action(monkeypatch):
    fake, _, result = run_capped(monkeypatch, max_mode="confirm")
    assert result["mode"] == "confirm" and fake.acts == []
    assert result["actions"] and all(a["declined"] and not a["sent"] for a in result["actions"])


def test_observe_windows_are_never_shorter_than_the_system_can_measure(monkeypatch):
    _, windows, _ = run_capped(monkeypatch, min_window_s=30)
    assert windows and min(windows) == 30.0
