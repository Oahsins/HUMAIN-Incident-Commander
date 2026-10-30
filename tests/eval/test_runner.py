"""Exercise real spawned workers using a wholly invented target system."""

import json
import multiprocessing as mp
from pathlib import Path
import sys
import types
import time

import pytest
import psutil

from eval.runner import Hooks, Timing, case_order, classify_result, kill_tree, replace_outcome, run_cases
from eval.storage import load_records, run_lock
from tests.eval import fakes


def options(tmp_path, monkeypatch, names=("invented", "noop"), cases=None, split="dev"):
    # The report's own tests cover its index; this test isolates execution.
    report = types.ModuleType("eval.report")
    report.update_run_index = lambda path: None
    monkeypatch.setitem(sys.modules, "eval.report", report)
    cases = cases or [fakes.case(i, healthy=i == 3, condition="log_format_v2") for i in range(4)]
    return dict(root=tmp_path, name="fixture-run", cases=cases, arm_names=list(names), split=split,
        models={c["id"]: None for c in cases}, copies=2, port_bases=[8400, 8500], provenance={"git_commit": "fixture", "hashes": {}},
        timing=Timing(warmup_s=0, alert_delay_s=0.02, budget_s=0.2, soak_s=0.05, check_window_s=0.05,
                      check_lag_s=0.02, arm_grace_s=5, watchdog_s=20),
        hooks=Hooks(platform=fakes.platform, checker=fakes.checker, inject=fakes.inject, load_arm=fakes.load_arm))


def test_four_cases_two_copies_and_resume(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch)
    assert run_cases(**kwargs)
    run_dir = tmp_path / "results" / "fixture-run"
    records = load_records(run_dir)
    assert len(records) == 8
    for record in records:
        number = record["case"]["input"]["seed"]
        assert record["port_base"] == [8400, 8500][number % 2]
        assert record["checker"]["since_t"] == record["timing"]["t0"]
        assert record["timing"]["verdict_t"] >= record["timing"]["horizon"] + 0.02
        folder = run_dir / "cases" / record["case"]["id"] / record["arm"]
        assert json.loads((folder / "logs" / "fixture.json").read_text())["condition"] == "log_format_v2"
        assert json.loads((folder / "changes.jsonl").read_text())["allow_sealed"] is False
        assert (folder / "customers.jsonl").exists()
        if record["arm"] == "invented":
            assert record["result"]["outcome"] == "recovered"
            assert len(record["audit"]) == 1
    mtimes = {p: p.stat().st_mtime_ns for p in run_dir.glob("cases/*/*/record.json")}
    assert run_cases(**kwargs)
    assert mtimes == {p: p.stat().st_mtime_ns for p in mtimes}


@pytest.mark.parametrize("split", ["heldout", "transfer"])
def test_sealed_splits_authorise_injection_only_in_fake(tmp_path, monkeypatch, split):
    kwargs = options(tmp_path, monkeypatch, names=("noop",), cases=[fakes.case(1)], split=split)
    assert run_cases(**kwargs)
    path = tmp_path / "results/fixture-run/cases/fixture-1/noop/changes.jsonl"
    assert json.loads(path.read_text())["allow_sealed"] is True


def test_changed_run_input_refused(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("noop",), cases=[fakes.case(1)])
    assert run_cases(**kwargs)
    kwargs["models"] = {"fixture-1": "changed"}
    with pytest.raises(ValueError, match="different inputs"):
        run_cases(**kwargs)


def test_transient_retries_exactly_once_and_retains_both(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("transient",), cases=[fakes.case(1)])
    assert run_cases(**kwargs)
    records = load_records(tmp_path / "results/fixture-run", effective=False)
    assert [r["purpose"] for r in records] == ["main", "retry"]
    assert all(r["result"]["outcome"] == "api_error" for r in records)
    assert all(r["telemetry_complete"] is True for r in records)
    before = [r["result"]["t_declared"] for r in records]
    assert run_cases(**kwargs)
    assert before == [r["result"]["t_declared"] for r in load_records(tmp_path / "results/fixture-run", effective=False)]


def test_arm_deadline_prevents_late_action(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("slow",), cases=[fakes.case(1)])
    kwargs["timing"] = Timing(warmup_s=0, alert_delay_s=0, budget_s=0.05, soak_s=0.05, check_window_s=0.05,
                              check_lag_s=0, arm_grace_s=0.5, watchdog_s=10)
    assert run_cases(**kwargs)
    record = load_records(tmp_path / "results/fixture-run")[0]
    assert record["result"]["outcome"] == "budget_exhausted"
    assert record["telemetry_complete"] is False
    assert record["actions"] == []
    assert record["checker"]["recovered"] is False


def test_crashed_arm_marks_unknown_telemetry_and_preserves_audit(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("crashed",), cases=[fakes.case(1)])
    assert run_cases(**kwargs)
    record = load_records(tmp_path / "results/fixture-run")[0]
    assert record["result"]["outcome"] == "arm_error"
    assert record["telemetry_complete"] is False
    assert len(record["actions"]) == 1
    assert len(record["audit"]) == 1


def test_harness_failure_preserves_known_model_calls():
    calls = [{"status": "ok", "input_tokens": 12, "output_tokens": 4, "estimated_cost_usd": 0.1}]
    record = {"arm": "abcde", "result": {"outcome": "recovered", "calls": calls}, "telemetry_complete": True}
    replace_outcome(record, "harness_error")
    assert record["result"]["outcome"] == "harness_error"
    assert record["result"]["calls"] == calls
    assert record["telemetry_complete"] is True


def test_watchdog_has_one_retry(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("slow",), cases=[fakes.case(1)])
    kwargs["timing"] = Timing(watchdog_s=0.05)
    assert run_cases(**kwargs)
    records = load_records(tmp_path / "results/fixture-run", effective=False)
    assert [r["purpose"] for r in records] == ["main", "retry"]
    assert all(r["result"]["outcome"] == "harness_timeout" for r in records)
    assert all(r["telemetry_complete"] is False for r in records)


def test_red_oracle_validation_retained_and_not_repeated(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("oracle",), cases=[fakes.case(1)])
    kwargs["hooks"] = Hooks(platform=fakes.platform, checker=fakes.red_checker, inject=fakes.inject, load_arm=fakes.load_arm)
    assert run_cases(**kwargs)
    run_dir = tmp_path / "results/fixture-run"
    records = load_records(run_dir, effective=False)
    assert [r["purpose"] for r in records] == ["main", "oracle_recheck"]
    assert all(r["checker"]["recovered"] is False for r in records)
    declared = records[-1]["result"]["t_declared"]
    assert run_cases(**kwargs)
    assert load_records(run_dir, effective=False)[-1]["result"]["t_declared"] == declared


def test_injection_error_is_distinct_and_retried_once(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("noop",), cases=[fakes.case(1)])
    kwargs["hooks"] = Hooks(platform=fakes.platform, checker=fakes.checker, inject=fakes.broken_inject, load_arm=fakes.load_arm)
    assert run_cases(**kwargs)
    records = load_records(tmp_path / "results/fixture-run", effective=False)
    assert len(records) == 2
    assert all(r["error"]["stage"] == "inject" and r["injection_complete"] is False for r in records)


def test_case_order_reproducible():
    cases = [fakes.case(1), fakes.case(2)]
    assert case_order(cases, ["a", "b", "c"]) == case_order(cases, ["a", "b", "c"])
    assert [c["id"] for c, _ in case_order(cases, ["a", "b"])] == ["fixture-1", "fixture-2"]


def test_run_lock_excludes_second_writer_and_releases(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(ValueError, match="already active"):
            with run_lock(tmp_path):
                pytest.fail("second writer entered")
    with run_lock(tmp_path):
        assert (tmp_path / ".lock-owner.json").exists()


def test_watchdog_cleanup_kills_live_child_and_grandchild(tmp_path):
    process = mp.get_context("spawn").Process(target=fakes.spawning_parent, args=(str(tmp_path),))
    process.start()
    path = tmp_path / "nested-pids.json"
    deadline = time.monotonic() + 10
    try:
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert path.exists(), "nested fixture did not start"
        pids = json.loads(path.read_text())
        assert all(psutil.pid_exists(pid) for pid in pids)
        kill_tree(process)
        assert not process.is_alive()
        assert process.exitcode is not None
        # The owning multiprocessing object must retain its child's exit
        # status, including on Unix where another waiter could consume it.
        process.join(timeout=0)
        assert process.exitcode is not None
        assert all(not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE for pid in pids)
    finally:
        if process.is_alive():
            kill_tree(process)


@pytest.mark.parametrize("error,expected", [("http_429", "api_error"), ("http_400", "gave_up"), ("invalid_json", "gave_up")])
def test_api_classification_only_from_last_failed_call(error, expected):
    assert classify_result({"outcome": "gave_up", "calls": [{"status": "failed", "error": error}]})["outcome"] == expected
    assert classify_result({"outcome": "recovered", "calls": [{"status": "failed", "error": error}]})["outcome"] == "recovered"
