"""Invented target systems exercise rules without any scenario labels or private state."""

from copy import deepcopy
import json

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


@pytest.mark.parametrize("signature", ["crash", "bad_update", "bad_setting", "locked_ledger",
                                       "stopped_worker", "slow_screening"])
def test_rule_reason_reaches_confirmation_and_audit(signature, tmp_path, clock):
    """The operator and retained evidence receive the same reason as the handover."""
    adapter = FakeAdapter(signature)
    audit = tmp_path / "audit.jsonl"
    proposals = []
    guarded = Guard(adapter, mode="confirm", audit_path=str(audit),
                    confirm=lambda proposal: proposals.append(proposal) or True)

    result = runbook.run_incident(guarded)

    decisions = [json.loads(line) for line in audit.read_text().splitlines()]
    actions = [entry for entry in decisions if entry.get("event") == "act"]
    assert result["outcome"] == "recovered"
    assert len(proposals) == len(actions) == len(result["actions"]) == 1
    reason = result["actions"][0]["reason"]
    assert reason
    assert proposals[0]["reason"] == actions[0]["reason"] == reason


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


class RollingHistoryAdapter(FakeAdapter):
    """A repaired release leaves old downstream errors in a rolling window."""
    def __init__(self, clock, remaining_config=False):
        super().__init__("bad_update")
        self.clock = clock
        self.remaining_config = remaining_config
        self.repaired_at = None
        self.observations = []

    def observe(self, window_s=10):
        observation = super().observe(window_s)
        self.observations.append((self.clock.monotonic(), window_s))
        front = observation["components"]["front"]
        # The front's recent errors came from its dependency's broken release.
        old_errors_visible = (self.repaired_at is None
                              or self.clock.monotonic() - window_s < self.repaired_at)
        front.update(error_rate=0.4 if old_errors_visible else 0,
                     reject_rate=0.6 if self.remaining_config else 0, config_version=2)
        observation["changes"].append({"component": "front", "kind": "config", "t": 1,
                                       "detail": {"key": "request_cap", "from": 1000,
                                                  "to": 1 if self.remaining_config else 900}})
        return observation

    def act(self, action, target, params=None):
        selected = action, target, params or {}
        self.taken.append(selected)
        if selected == ("rollback", "logic", {}):
            self.signature = None
            self.repaired_at = self.clock.monotonic()
        else:
            assert selected == ("revert_config", "front", {"key": "request_cap"})
            self.remaining_config = False
        return {"ok": True, "refused": False, "detail": "Done."}


@pytest.mark.parametrize("min_window", [2, 30])
def test_repaired_dependency_does_not_blame_benign_downstream_change(clock, min_window):
    adapter = RollingHistoryAdapter(clock)
    adapter.min_window = min_window

    result = runbook.run_incident(adapter)

    assert result["outcome"] == "recovered"
    assert adapter.taken == [("rollback", "logic", {})]
    assert [(r["target"], r["class"]) for r in result["root_causes"]] == [("logic", "bad_release")]
    assert adapter.observations[0][1] == max(10, min_window)
    assert all(at - window >= adapter.repaired_at for at, window in adapter.observations[1:])


def test_fresh_observation_keeps_a_genuine_remaining_config_fault(clock):
    adapter = RollingHistoryAdapter(clock, remaining_config=True)

    result = runbook.run_incident(adapter)

    assert result["outcome"] == "recovered"
    assert adapter.taken == [("rollback", "logic", {}),
                             ("revert_config", "front", {"key": "request_cap"})]
    assert not any(action["refused"] for action in result["actions"])


def test_post_action_window_respects_minimum_and_time_budget(clock):
    adapter = RollingHistoryAdapter(clock)
    adapter.min_window = 30

    result = runbook.run_incident(adapter, budget_s=20)

    assert result["outcome"] == "budget_exhausted"
    assert adapter.taken == [("rollback", "logic", {})]
    assert adapter.observations == [(0, 30)]
    assert clock.now == 20
    assert all(result["sbar"].values())


@pytest.mark.parametrize("front_fault", [False, True])
def test_config_rule_fixes_upstream_before_blame_from_propagated_rejects(clock, front_fault):
    class PropagatedRejects(FakeAdapter):
        def __init__(self):
            super().__init__("bad_setting")
            self.front_fault = front_fault

        def observe(self, window_s=10):
            observation = super().observe(window_s)
            upstream_rejects = 0.7 if self.signature == "bad_setting" else 0
            observation["components"]["front"].update(
                reject_rate=max(upstream_rejects, 0.6 if self.front_fault else 0), config_version=2,
                extra={"dependencies": {"logic": {"error_rate": 0, "reject_rate": upstream_rejects}}})
            observation["changes"].append({"component": "front", "kind": "config", "t": 2,
                "detail": {"key": "front_cap", "from": 1000, "to": 1 if self.front_fault else 900}})
            return observation

        def act(self, action, target, params=None):
            self.taken.append((action, target, params or {}))
            assert action == "revert_config"
            if target == "logic":
                self.signature = None
            else:
                assert target == "front"
                self.front_fault = False
                self.extra_changes.append({"component": "front", "kind": "config", "t": 3,
                    "detail": {"key": "front_cap", "revert": True}})
            return {"ok": True, "refused": False, "detail": "Done."}

    adapter = PropagatedRejects()
    result = runbook.run_incident(adapter)

    expected = [("revert_config", "logic", {"key": "request_cap"})]
    if front_fault:
        expected.append(("revert_config", "front", {"key": "front_cap"}))
    assert result["outcome"] == "recovered"
    assert adapter.taken == expected
    assert not any(action["refused"] for action in result["actions"])


def test_local_timeout_config_remains_eligible_when_dependency_is_healthy(clock):
    class LocalTimeout(FakeAdapter):
        def __init__(self):
            super().__init__("bad_setting")
            self.expected = ("revert_config", "logic", {"key": "lookup_wait_s"})

        def observe(self, window_s=10):
            observation = super().observe(window_s)
            if self.signature:
                observation["components"]["logic"].update(error_rate=0.8, reject_rate=0,
                    extra={"dependencies": {"lookup": {"error_rate": 0.8, "reject_rate": 0}}})
                observation["changes"][0]["detail"] = {"key": "lookup_wait_s", "from": 1, "to": 0.002}
            return observation

    adapter = LocalTimeout()
    result = runbook.run_incident(adapter)

    assert result["outcome"] == "recovered"
    assert adapter.taken == [adapter.expected]
    assert result["root_causes"][0]["class"] == "bad_config"


def test_external_outage_is_not_blame_for_a_benign_caller_config(clock):
    class ExternalFailure(FakeAdapter):
        def __init__(self):
            super().__init__("external")

        def observe(self, window_s=10):
            observation = super().observe(window_s)
            observation["components"]["consumer"].update(error_rate=0.8, config_version=2,
                extra={"dependencies": {"outside": {"error_rate": 0.8}}})
            observation["changes"].append({"component": "consumer", "kind": "config", "t": 2,
                "detail": {"key": "batch_count", "from": 50, "to": 60}})
            return observation

    adapter = ExternalFailure()
    result = runbook.run_incident(adapter)

    assert result["outcome"] == "escalated"
    assert result["escalation"]["components"] == ["outside"]
    assert adapter.taken == result["actions"] == []
    assert result["root_causes"][0]["class"] == "external_outage"


class QueueDuringProbe(FakeAdapter):
    """The failed journey creates work; its queue ages while the probe waits."""
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.queue_started = None
        self.fixed = False
        self.expected = ("revert_config", "consumer", {"key": "batch_count"})

    def observe(self, window_s=10):
        observation = super().observe(window_s)
        if not self.fixed:
            observation["components"]["consumer"].update(config_version=2, extra={
                "queue_depth": 0 if self.queue_started is None else 1,
                "oldest_pending_s": 0 if self.queue_started is None else self.clock.monotonic() - self.queue_started,
                "processed_per_s": 0})
            observation["changes"].append({"component": "consumer", "kind": "config", "t": 1,
                "detail": {"key": "batch_count", "from": 50, "to": 0}})
        return observation

    def probe(self, journey=None):
        if not self.fixed:
            self.queue_started = self.clock.monotonic()
            self.clock.sleep(3.5)
        self.probes.append(self.fixed)
        return {"ok": self.fixed, "steps": [{"component": "consumer", "ok": self.fixed}]}

    def act(self, action, target, params=None):
        response = super().act(action, target, params)
        self.fixed = True
        return response


def test_failed_probe_refreshes_queue_before_escalation(clock):
    adapter = QueueDuringProbe(clock)

    result = runbook.run_incident(adapter)

    assert result["outcome"] == "recovered"
    assert adapter.taken == [adapter.expected]
    assert adapter.probes == [False, True, True, True]
    assert result["root_causes"][0]["target"] == "consumer"


@pytest.mark.parametrize("min_window", [2, 6])
@pytest.mark.parametrize("completion", [0.5, 4.0, None], ids=["stopped", "intermittent", "steady"])
def test_failed_probe_keeps_progress_after_worker_change(clock, min_window, completion):
    stopped = completion == 0.5

    class RecentWorkerChange(QueueDuringProbe):
        def __init__(self):
            super().__init__(clock)
            self.min_window = min_window
            self.queue_started = 0.0
            self.observations = []

        def observe(self, window_s=10):
            observation = super().observe(window_s)
            self.observations.append((clock.monotonic(), window_s))
            if not self.fixed:
                # The setting changed at one second. Retain completions after
                # that change even when none fell inside the failed probe.
                completion_visible = completion is None or clock.monotonic() - window_s < completion
                observation["components"]["consumer"]["extra"]["processed_per_s"] = (
                    2.0 if completion_visible else 0.0)
                observation["changes"][0]["t"] = clock.time() - clock.monotonic() + 1.0
                if not stopped:
                    observation["changes"][0]["detail"]["to"] = 60
            return observation

    clock.sleep(5.0)  # The alert follows the setting change.
    adapter = RecentWorkerChange()

    result = runbook.run_incident(adapter)

    assert result["outcome"] == ("recovered" if stopped else "escalated")
    assert adapter.taken == ([adapter.expected] if stopped else [])
    assert not any(action["refused"] for action in result["actions"])
    assert adapter.observations[:2] == [(5.0, 10.0), (8.5, 7.5)]
    assert all(window >= min_window for _, window in adapter.observations)


@pytest.mark.parametrize("change_times,refresh_window", [
    ([1.0, 4.5], 7.5),  # Progress between two changes must remain visible.
    ([-20.0], 10.0),    # An old change does not extend the normal window.
    ([None], 10.0),
    (["missing"], 10.0),
    ([float("nan")], 10.0),
    ([float("inf")], 10.0),
    ([100.0], 10.0),    # A future timestamp cannot justify a narrow window.
])
def test_worker_refresh_keeps_history_when_change_time_is_uncertain(clock, change_times, refresh_window):
    class IntermittentWorker(FakeAdapter):
        def __init__(self):
            super().__init__("unrecognised")
            self.windows = []

        def observe(self, window_s=10):
            observation = super().observe(window_s)
            self.windows.append(window_s)
            observation["components"]["consumer"]["extra"] = {
                "queue_depth": 2, "oldest_pending_s": 4,
                "processed_per_s": 1.0 if clock.monotonic() - window_s < 4.0 else 0.0}
            for index, changed_at in enumerate(change_times):
                change = {"component": "consumer", "kind": "config",
                          "detail": {"key": f"setting_{index}", "from": 50, "to": 60}}
                if changed_at != "missing":
                    change["t"] = (clock.time() - clock.monotonic() + changed_at
                                   if isinstance(changed_at, (int, float)) else changed_at)
                observation["changes"].append(change)
            return observation

        def probe(self, journey=None):
            clock.sleep(3.5)
            return {"ok": False, "steps": [{"component": "consumer", "ok": False}]}

    clock.sleep(5)
    adapter = IntermittentWorker()

    result = runbook.run_incident(adapter)

    assert result["outcome"] == "escalated"
    assert adapter.taken == result["actions"] == []
    assert adapter.windows == [10.0, refresh_window]


def test_worker_refresh_keeps_other_workers_post_change_progress(clock):
    class TwoQueues(FakeAdapter):
        def __init__(self):
            super().__init__("unrecognised")

        def describe(self):
            profile = super().describe()
            profile["components"].append({"name": "other_consumer", "kind": "worker",
                "depends_on": [], "actions": ["revert_config"]})
            return profile

        def observe(self, window_s=10):
            observation = super().observe(window_s)
            for name, changed_at, queued_at, value in (
                    ("consumer", 0.1, 4.0, 60), ("other_consumer", 1.0, 1.0, 0)):
                observation["components"][name]["extra"] = {
                    "queue_depth": 2, "oldest_pending_s": clock.monotonic() - queued_at,
                    "processed_per_s": 1.0 if clock.monotonic() - window_s < 0.5 else 0.0}
                observation["changes"].append({"component": name, "kind": "config",
                    "t": clock.time() - clock.monotonic() + changed_at,
                    "detail": {"key": "batch_count", "from": 50, "to": value}})
            return observation

        def probe(self, journey=None):
            clock.sleep(3.5)
            return {"ok": False, "steps": []}

        def act(self, action, target, params=None):
            raise AssertionError("The global window must retain the other worker's progress.")

    clock.sleep(5)
    adapter = TwoQueues()

    result = runbook.run_incident(adapter)

    assert result["outcome"] == "escalated"
    assert result["actions"] == []


@pytest.mark.parametrize("limits", [{"max_steps": 3}, {"budget_s": 3}])
def test_refresh_after_failed_probe_respects_budgets(clock, limits):
    adapter = QueueDuringProbe(clock)

    result = runbook.run_incident(adapter, **limits)

    assert result["outcome"] == "budget_exhausted"
    assert adapter.taken == result["actions"] == []
    assert all(result["sbar"].values())


def test_failed_probe_without_a_rule_refreshes_only_once(clock):
    adapter = FakeAdapter("unrecognised")

    result = runbook.run_incident(adapter)

    assert result["outcome"] == "escalated"
    assert adapter.taken == result["actions"] == []
    assert adapter.probes == [False]
    assert sum(entry["name"] == "observe" for entry in result["trace"]) == 2


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
