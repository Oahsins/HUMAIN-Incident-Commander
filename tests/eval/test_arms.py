"""The oracle follows labels in order without guessing runtime values."""

import pytest

from eval.arms import load_arm, noop, oracle
from ic.guard import Guard
from tests.eval.fakes import Adapter


def test_noop_does_not_observe():
    assert noop(object())["outcome"] == "no_incident"


def test_oracle_runtime_parameter_and_then(tmp_path):
    adapter = Adapter(tmp_path)
    roots = [{"target": "engine", "class": "process_down", "fix": {"action": "quarantine", "target": "engine",
        "params": {"item": None}, "then": [{"action": "restart", "target": "engine", "params": {}}]}}]
    manifest = [{"target": "engine", "class": "process_down", "detail": {"item": 91}}]
    result = oracle(Guard(adapter), root_causes=roots, manifest=manifest)
    assert result["outcome"] == "recovered"
    assert [a["action"] for a in result["actions"]] == ["quarantine", "restart"]
    assert result["actions"][0]["params"] == {"item": 91}
    assert all(a["sent"] for a in result["actions"])
    assert roots[0]["fix"]["params"]["item"] is None


def test_oracle_escalation_is_not_action(tmp_path):
    roots = [{"target": "outside", "class": "external_outage", "fix": {"action": "escalate", "target": "outside"}}]
    result = oracle(Guard(Adapter(tmp_path)), root_causes=roots, manifest=[{"target": "outside", "class": "external_outage"}])
    assert result["outcome"] == "escalated"
    assert result["actions"] == []
    assert result["escalation"]["components"] == ["outside"]


def test_oracle_missing_runtime_value_refuses(tmp_path):
    roots = [{"target": "engine", "class": "process_down", "fix": {"action": "quarantine", "target": "engine", "params": {"item": None}}}]
    with pytest.raises(ValueError, match="parameter item"):
        oracle(Guard(Adapter(tmp_path)), root_causes=roots, manifest=[{"target": "engine", "class": "process_down"}])
    assert not (tmp_path / "actions.jsonl").exists()


def test_oracle_advice_never_acts(tmp_path):
    roots = [{"target": "engine", "class": "process_down", "fix": {"action": "restart", "target": "engine"}}]
    result = oracle(Guard(Adapter(tmp_path), mode="advise"), root_causes=roots, manifest=[{"target": "engine", "class": "process_down"}], mode="advise")
    assert result["outcome"] == "advised"
    assert result["proposed_actions"][0]["sent"] is False
    assert not (tmp_path / "actions.jsonl").exists()


def test_oracle_cannot_claim_recovery_before_action_wait(tmp_path):
    class SlowAdapter(Adapter):
        def describe(self):
            profile = super().describe()
            profile["actions"]["restart"]["est_seconds"] = 10
            return profile
    roots = [{"target": "engine", "class": "process_down", "fix": {"action": "restart", "target": "engine"}}]
    result = oracle(Guard(SlowAdapter(tmp_path)), root_causes=roots, manifest=[{"target": "engine", "class": "process_down"}], budget_s=0.02)
    assert result["outcome"] == "budget_exhausted"
