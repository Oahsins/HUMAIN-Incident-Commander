"""Every arm, end to end on the fake system with test models: no key, no network, no waiting."""

import json

import pytest

from ic import contract, llm
from ic.agent import ARMS, common, load_arm
from ic.guard import Guard
from tests.agent import mock_model
from tests.agent.fake_system import FakeSystem

MODEL = mock_model.install()


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(common, "SLEEP", lambda seconds: None)


def run(arm, faults, **kwargs):
    fake = FakeSystem(faults)
    result = load_arm(arm)(fake, model=kwargs.pop("model", MODEL), budget_s=90.0, **kwargs)
    return fake, result


def check_shape(result):
    assert result["outcome"] in contract.OUTCOMES
    assert set(result["sbar"]) == {"situation", "background", "assessment", "recommendation"}
    assert all(r["refused_reason"] in (None,) + contract.REFUSED_REASONS for r in result["actions"])
    assert all(e["phase"] in contract.PHASES for e in result["trace"])
    assert result["steps"] <= 40
    if result["escalation"]:
        assert result["escalation"]["urgency"] in contract.ESCALATION_URGENCY
        assert set(result["escalation"]) == {"components", "class", "reason", "urgency", "to", "ask"}


@pytest.mark.parametrize("arm", ["abcde", "naive_verify", "fifo"])
@pytest.mark.parametrize("fault, fix", [("web_down", ("restart", "web")),
                                        ("web_bad_config", ("revert_config", "web")),
                                        ("db_locked", ("release_lock", "db"))])
def test_fixes_what_it_can(arm, fault, fix):
    fake, result = run(arm, {fault})
    check_shape(result)
    assert result["outcome"] == "recovered"
    assert fake.faults == set()
    assert fix in [(a, t) for a, t, _ in fake.acts]


def test_two_faults_at_once():
    fake, result = run("abcde", {"db_locked", "web_bad_config"})
    check_shape(result)
    assert result["outcome"] == "recovered" and fake.faults == set()
    assert {(c["target"], c["class"]) for c in result["root_causes"]} >= {("db", "lock_held"), ("web", "bad_config")}


def test_containment_then_recovery():
    fake, result = run("abcde", {"cache_slow"})
    check_shape(result)
    assert result["outcome"] == "recovered" and fake.active == "standby"
    assert fake.acts[0][:2] == ("failover", "cache")
    assert any(e["name"] == "containment" and e["phase"] == "survey" for e in result["trace"])
    assert [a for a, t, _ in fake.acts].count("failover") == 1     # not done again in remediate


def test_escalates_what_no_action_fixes():
    fake, result = run("abcde", {"partner_down"})
    check_shape(result)
    assert result["outcome"] == "escalated" and fake.acts == []
    assert result["escalation"]["components"] == ["partner"]


def test_healthy_system():
    fake, result = run("abcde", set())
    check_shape(result)
    assert result["outcome"] == "no_incident" and fake.acts == []
    assert [c["purpose"] for c in result["calls"]] == ["sbar"]     # no assessment: only the handover note


def test_advise_mode_changes_nothing():
    fake, result = run("abcde", {"web_down"}, mode="advise")
    check_shape(result)
    assert result["outcome"] == "advised" and fake.acts == []
    assert [(a["order"], a["action"], a["target"]) for a in result["proposed_actions"]] == [(1, "restart", "web")]


def test_declined_action_is_not_asked_again():
    asked = []
    fake, result = run("abcde", {"web_down"}, mode="confirm", confirm=lambda record: asked.append(record) or False)
    check_shape(result)
    assert fake.acts == [] and len(asked) == 1
    assert result["outcome"] != "recovered"


def test_model_failure_still_hands_over():
    def broken(system, messages, schema, purpose):
        raise llm.ModelError("down for the test")
    llm.register_mock("broken", broken)
    fake, result = run("abcde", {"web_down"}, model="mock:broken")
    check_shape(result)
    assert result["outcome"] == "gave_up" and fake.acts == []
    assert result["sbar"]["situation"]          # the template wrote the handover


def _react_model(steps):
    def answer(system, messages, schema, purpose):
        if purpose == "sbar":
            return json.dumps({"situation": "s", "background": "b", "assessment": "a", "recommendation": "r"})
        turn = sum(1 for m in messages if m["role"] == "assistant")
        step = {"thought": "", "tool": "done", "component": None, "window_s": None, "action": None, "target": None,
                "params": {"to": None, "item": None, "key": None}, "root_causes": [], "note": ""}
        step.update(steps[min(turn, len(steps) - 1)])
        return json.dumps(step)
    return answer


def test_react_arm():
    llm.register_mock("react-script", _react_model([
        {"tool": "observe", "window_s": 8},
        {"tool": "logs", "component": "web"},
        {"tool": "act", "action": "restart", "target": "web"},
        {"tool": "done", "root_causes": [{"target": "web", "class": "process_down", "confidence": 0.9,
                                          "evidence": "web is down"}]}]))
    fake, result = run("react", {"web_down"}, model="mock:react-script")
    check_shape(result)
    assert result["outcome"] == "recovered" and fake.faults == set()
    assert result["root_causes"][0]["target"] == "web"


def test_react_guard_still_applies():
    llm.register_mock("react-reckless", _react_model([
        {"tool": "act", "action": "restart", "target": "partner"},
        {"tool": "escalate", "target": "partner", "note": "ask the partner to restore service"},
        {"tool": "done"}]))
    fake, result = run("react", {"partner_down"}, model="mock:react-reckless")
    check_shape(result)
    assert fake.acts == []
    assert result["actions"][0]["refused_reason"] == "not_allowlisted"
    assert result["outcome"] == "escalated"


def test_every_arm_loads():
    assert set(ARMS) == {"abcde", "naive_verify", "fifo", "react"}
    for arm in ARMS:
        assert callable(load_arm(arm))
    with pytest.raises(KeyError):
        load_arm("runbook")


def test_the_harness_guard_sees_every_attempt(tmp_path):
    llm.register_mock("react-reckless-2", _react_model([
        {"tool": "act", "action": "restart", "target": "partner"},
        {"tool": "escalate", "target": "partner", "note": "ask the partner to restore service"},
        {"tool": "done"}]))
    fake = FakeSystem({"partner_down"})
    guard = Guard(fake, audit_path=str(tmp_path / "audit.jsonl"))
    result = load_arm("react")(guard, model="mock:react-reckless-2", budget_s=90.0)
    assert result["steps"] == guard.steps
    refused = [e for e in guard.audit if e.get("refused_reason") == "not_allowlisted"]
    assert [(e["action"], e["target"]) for e in refused] == [("restart", "partner")]
    assert (tmp_path / "audit.jsonl").read_text(encoding="utf-8").count("not_allowlisted") == 1


def test_mode_comes_from_the_harness_guard():
    fake = FakeSystem({"web_down"})
    result = load_arm("abcde")(Guard(fake, mode="advise"), model=MODEL, budget_s=90.0)
    assert result["mode"] == "advise" and result["outcome"] == "advised" and fake.acts == []
