"""Invented target systems exercise rules without any scenario labels or private state."""

from copy import deepcopy

import pytest

from baselines import runbook
from ic.guard import Guard


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return 1_800_000_000.0 + self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    for name in ("time", "monotonic", "sleep"):
        monkeypatch.setattr(runbook, name, getattr(clock, name))
    return clock


class FakeAdapter:
    """A renamed topology; taking the correct action clears its only problem."""
    def __init__(self, signature=None):
        self.signature = signature
        self.taken = []
        self.probes = []
        self.min_window = 2
        self.max_mode = "auto"
        self.persist = False
        self.extra_changes = []
        self.expected = {
            "crash": ("restart", "front", {}),
            "bad_update": ("rollback", "logic", {}),
            "bad_setting": ("revert_config", "logic", {"key": "request_cap"}),
            "locked_ledger": ("release_lock", "storage", {}),
            "stopped_worker": ("restart", "consumer", {}),
            "slow_screening": ("failover", "lookup", {"to": "standby"}),
        }.get(signature)

    def describe(self):
        components = [
            {"name": "front", "kind": "service", "depends_on": ["logic"], "actions": ["restart", "rollback", "revert_config"]},
            {"name": "logic", "kind": "service", "depends_on": ["lookup", "storage"], "actions": ["restart", "rollback", "revert_config"]},
            {"name": "lookup", "kind": "dependency", "depends_on": [], "actions": ["restart", "failover"], "standby": "reserve"},
            {"name": "reserve", "kind": "dependency", "depends_on": [], "actions": ["restart"]},
            {"name": "storage", "kind": "datastore", "depends_on": [], "actions": ["release_lock"]},
            {"name": "consumer", "kind": "worker", "depends_on": ["storage", "outside"], "actions": ["restart", "rollback", "revert_config", "quarantine"]},
            {"name": "outside", "kind": "external", "depends_on": [], "actions": []},
            {"name": "scheduled", "kind": "job", "depends_on": ["storage"], "actions": []},
        ]
        return {"system": "invented", "contract_version": 1,
                "components": components, "journeys": [{"name": "journey", "default": True, "entry": "front"}],
                "capabilities": {"act": True, "probe": True, "changes": True, "max_mode": self.max_mode, "min_window_s": self.min_window},
                "slo": {"success_rate": 0.99, "p95_ms": 1000},
                "actions": {a: {"est_seconds": 1, "params": {}} for a in ("restart", "rollback", "revert_config", "release_lock", "failover", "quarantine")}}

    def observe(self, window_s=10.0):
        assert window_s >= self.min_window
        metrics = {c["name"]: {"up": True, "error_rate": 0, "reject_rate": 0, "p95_ms": 100,
                              "release": "1.0", "config_version": 1, "extra": {}}
                   for c in self.describe()["components"]}
        baseline = deepcopy(metrics)
        metrics["scheduled"].update(up=None, cpu_pct=99)
        changes = []
        if self.signature == "crash":
            metrics["front"]["up"] = False
        elif self.signature == "bad_update":
            metrics["logic"].update(release="1.1", error_rate=0.4)
            changes.append({"component": "logic", "kind": "deploy", "t": 1, "detail": {"from": "1.0", "to": "1.1"}})
        elif self.signature == "bad_setting":
            metrics["logic"].update(config_version=2, reject_rate=0.7)
            changes.append({"component": "logic", "kind": "config", "t": 1, "detail": {"key": "request_cap", "from": 1000, "to": 1}})
        elif self.signature == "locked_ledger":
            metrics["storage"]["extra"] = {"lock_holders": [{"session": "session-1", "held_s": 7}], "write_errors": 8}
        elif self.signature == "stopped_worker":
            metrics["consumer"]["up"] = False
            changes.append({"component": "consumer", "kind": "stop", "t": 1, "detail": {}})
        elif self.signature == "slow_screening":
            metrics["logic"]["extra"] = {"dependencies": {"lookup": {"n": 20, "p95_ms": 2000, "error_rate": 0.8}}}
            metrics["lookup"]["extra"]["active"] = "primary"
        elif self.signature == "external":
            metrics["outside"].update(up=False, error_rate=1)
        elif self.signature == "noise":
            metrics["front"].update(release="1.1", config_version=2)
            changes += [{"component": "front", "kind": "deploy", "t": 1, "detail": {"from": "1.0", "to": "1.1"}},
                        {"component": "front", "kind": "config", "t": 2, "detail": {"key": "timeout", "from": 2, "to": 3}}]
        return {"t": 1, "window_s": window_s, "components": metrics, "baseline": baseline, "changes": changes + self.extra_changes}

    def probe(self, journey=None):
        ok = self.signature in (None, "noise", "bad_update", "bad_setting")
        self.probes.append(ok)
        return {"journey": "journey", "ok": ok, "ms": 100,
                "steps": [{"component": "consumer", "ok": ok, "ms": 100}]}

    def logs(self, component, since_s=60, limit=200):
        return []

    def act(self, action, target, params=None):
        selected = action, target, params or {}
        assert selected == self.expected
        self.taken.append(selected)
        if not self.persist:
            self.signature = None
        return {"ok": True, "refused": False, "action": action, "target": target, "detail": "Done."}


@pytest.mark.parametrize("signature", ["crash", "bad_update", "bad_setting", "locked_ledger", "stopped_worker", "slow_screening"])
def test_each_practice_signature_has_one_right_action(signature, clock):
    adapter = FakeAdapter(signature)
    result = runbook.run_incident(adapter)
    assert adapter.taken == [adapter.expected]
    assert result["outcome"] == "recovered"
    assert result["calls"] == []
    assert not any(action["refused"] for action in result["actions"])
    assert all(action["sent"] and action["ok"] for action in result["actions"])
    assert adapter.probes[-3:] == [True, True, True]
    assert result["t_declared"] - result["t_first_action"] >= 10
    assert all(result["sbar"].values())


@pytest.mark.parametrize("signature", [None, "noise"])
def test_healthy_and_harmless_changes_do_nothing(signature, clock):
    adapter = FakeAdapter(signature)
    result = runbook.run_incident(adapter)
    assert result["outcome"] == "no_incident"
    assert result["actions"] == adapter.taken == result["root_causes"] == []


def test_external_fault_is_escalated(clock):
    result = runbook.run_incident(FakeAdapter("external"))
    assert result["outcome"] == "escalated"
    assert result["escalation"]["components"] == ["outside"]
    assert result["actions"] == []


@pytest.mark.parametrize("cap", [False, True])
def test_advise_never_calls_act_and_has_full_records(cap, clock):
    adapter = FakeAdapter("bad_setting")
    if cap:
        adapter.max_mode = "advise"
    result = runbook.run_incident(adapter, mode="auto" if cap else "advise")
    assert result["outcome"] == "advised"
    assert result["mode"] == "advise"
    assert result["actions"] == adapter.taken == []
    proposal = result["proposed_actions"][0]
    assert proposal["order"] == 1 and proposal["sent"] is False
    assert proposal["action"] == "revert_config"


def test_supplied_guard_keeps_its_advise_mode(clock):
    adapter = FakeAdapter("crash")
    result = runbook.run_incident(Guard(adapter, mode="advise"))
    assert result["outcome"] == "advised"
    assert adapter.taken == []


def test_confirm_decline_never_sends_an_action(clock):
    adapter = FakeAdapter("crash")
    proposals = []
    result = runbook.run_incident(adapter, mode="confirm", confirm=lambda p: proposals.append(p) or False)
    assert len(proposals) == 1
    assert result["actions"][0]["declined"] is True
    assert result["actions"][0]["sent"] is False
    assert adapter.taken == []


def test_confirm_accept_sends_once(clock):
    adapter = FakeAdapter("crash")
    proposals = []
    result = runbook.run_incident(adapter, mode="confirm", confirm=lambda p: proposals.append(p) or True)
    assert result["outcome"] == "recovered"
    assert len(proposals) == len(adapter.taken) == 1


def test_target_confirm_cap_is_enforced(clock):
    adapter = FakeAdapter("crash")
    adapter.max_mode = "confirm"
    result = runbook.run_incident(adapter)
    assert result["mode"] == "confirm"
    assert result["actions"][0]["declined"]
    assert adapter.taken == []


def test_action_finishing_after_deadline_is_still_recorded(clock):
    adapter = FakeAdapter("crash")
    original = adapter.act

    def slow_action(*args, **kwargs):
        clock.sleep(20)
        return original(*args, **kwargs)

    adapter.act = slow_action
    result = runbook.run_incident(adapter, budget_s=10)
    assert result["outcome"] == "budget_exhausted"
    assert result["actions"][0]["sent"]
    assert result["t_first_action"] == result["t_start"]


def test_supplied_guard_receives_actions_and_audit(tmp_path, clock):
    adapter = FakeAdapter("crash")
    audit = tmp_path / "audit.jsonl"
    result = runbook.run_incident(Guard(adapter, audit_path=str(audit)))
    assert result["outcome"] == "recovered"
    assert '"restart"' in audit.read_text()


def test_repeating_failed_fix_is_escalated(clock):
    adapter = FakeAdapter("crash")
    adapter.persist = True
    result = runbook.run_incident(adapter)
    assert result["outcome"] == "escalated"
    assert len(adapter.taken) == 1
    assert not any(action["refused"] for action in result["actions"])


@pytest.mark.parametrize("kwargs", [{"max_steps": 2}, {"budget_s": 0}, {"budget_s": 8}])
def test_budgets_end_with_a_handover(kwargs, clock):
    result = runbook.run_incident(FakeAdapter("crash"), **kwargs)
    assert result["outcome"] == "budget_exhausted"
    assert all(result["sbar"].values())


def test_minimum_observation_window_and_future_arguments(clock):
    adapter = FakeAdapter()
    adapter.min_window = 30
    assert runbook.run_incident(adapter, future_option=True)["outcome"] == "no_incident"


def test_config_chooses_severe_change_over_later_benign_change(clock):
    adapter = FakeAdapter("bad_setting")
    adapter.extra_changes = [{"component": "logic", "kind": "config", "t": 2,
                              "detail": {"key": "poll_interval", "from": 0.2, "to": 0.25}}]
    assert runbook.run_incident(adapter)["outcome"] == "recovered"


def test_several_faults_are_reobserved_and_fixed_without_refusals(clock):
    class Compound(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.remaining = ["crash", "bad_setting", "stopped_worker", "slow_screening"]

        def observe(self, window_s=10):
            observation = super().observe(window_s)
            for signature in self.remaining:
                other = FakeAdapter(signature).observe(window_s)
                observation["changes"].extend(other["changes"])
                for name, metrics in other["components"].items():
                    if metrics != other["baseline"][name]:
                        observation["components"][name].update(metrics)
            return observation

        def probe(self, journey=None):
            return {"ok": not self.remaining, "steps": []}

        def act(self, action, target, params=None):
            chosen = (action, target, params or {})
            signature = next(s for s in self.remaining if FakeAdapter(s).expected == chosen)
            self.remaining.remove(signature)
            self.taken.append(chosen)
            return {"ok": True, "refused": False, "detail": "Done."}

    adapter = Compound()
    result = runbook.run_incident(adapter)
    assert result["outcome"] == "recovered"
    assert len(result["actions"]) == 4
    assert not any(a["refused"] for a in result["actions"])
