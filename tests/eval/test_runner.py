"""Exercise real spawned workers using a wholly invented target system."""

import json
from concurrent.futures import Future
import multiprocessing as mp
from pathlib import Path
import sys
import types
import time

import pytest
import psutil

from eval.runner import Hooks, Timing, case_order, classify_result, kill_tree, replace_outcome, run_cases
from eval.storage import load_records, run_lock
from eval import runner
from eval.storage import write_json, read_json
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


@pytest.mark.parametrize("outcome", ["harness_error", "harness_timeout", "api_error"])
def test_oracle_validation_infrastructure_failure_has_one_separate_retry(tmp_path, monkeypatch, outcome):
    kwargs = options(tmp_path, monkeypatch, names=("oracle",), cases=[fakes.case(1)])
    kwargs["hooks"] = Hooks(platform=fakes.platform, checker=fakes.red_checker, inject=fakes.inject, load_arm=fakes.load_arm)
    original_pair = runner.run_pair

    def fail_validation(root, name, case, arm, port, split, model, timing, hooks, destination,
                        attempt=1, purpose="main", stop=None):
        if purpose != "oracle_recheck":
            return original_pair(root, name, case, arm, port, split, model, timing, hooks,
                                 destination, attempt, purpose, stop)
        if (destination / "record.json").exists():
            return
        record = read_json(destination.parent / "record.json")
        record.update(attempt=attempt, purpose=purpose, error={"type": "InventedFailure"})
        record["result"]["outcome"] = outcome
        write_json(destination / "record.json", record)

    monkeypatch.setattr(runner, "run_pair", fail_validation)
    assert run_cases(**kwargs)
    run_dir = tmp_path / "results/fixture-run"
    records = load_records(run_dir, effective=False)
    assert [r["purpose"] for r in records] == ["main", "oracle_recheck", "oracle_recheck_retry"]
    assert records[1]["result"]["outcome"] == outcome
    assert records[2]["result"]["outcome"] == "recovered"
    effective = load_records(run_dir)[0]
    assert effective["result"]["outcome"] == "recovered"
    assert effective["oracle_validation"]["purpose"] == "oracle_recheck_retry"
    assert [r["purpose"] for r in effective["oracle_validation"]["attempts"]] == ["oracle_recheck", "oracle_recheck_retry"]
    mtimes = {p: p.stat().st_mtime_ns for p in run_dir.rglob("record.json")}
    assert run_cases(**kwargs)
    assert mtimes == {p: p.stat().st_mtime_ns for p in mtimes}


def test_must_escalate_oracle_is_never_rechecked(tmp_path, monkeypatch):
    case = fakes.case(1)
    case["target"]["must_escalate"] = True
    kwargs = options(tmp_path, monkeypatch, names=("oracle",), cases=[case])
    kwargs["hooks"] = Hooks(platform=fakes.platform, checker=fakes.red_checker, inject=fakes.inject, load_arm=fakes.load_arm)
    assert run_cases(**kwargs)
    records = load_records(tmp_path / "results/fixture-run", effective=False)
    assert len(records) == 1
    assert records[0]["checker"]["recovered"] is False


@pytest.mark.parametrize("arm", ["unreachable", "caught_read", "bare_callerror"])
def test_unreachable_read_is_harness_error_even_when_caught(tmp_path, monkeypatch, arm):
    kwargs = options(tmp_path, monkeypatch, names=(arm,), cases=[fakes.case(1)])
    kwargs["hooks"] = Hooks(platform=fakes.unreadable_platform, checker=fakes.checker,
                            inject=fakes.inject, load_arm=fakes.load_arm)
    assert run_cases(**kwargs)
    run_dir = tmp_path / "results/fixture-run"
    records = load_records(run_dir, effective=False)
    assert [r["purpose"] for r in records] == ["main", "retry"]
    assert all(r["result"]["outcome"] == "harness_error" for r in records)
    assert all(r["error"]["type"] == "CallError" and r["error"]["kind"] == "refused" for r in records)
    assert all(any(a.get("event") == "read_error" for a in r["audit"]) == (arm != "bare_callerror") for r in records)
    if arm == "caught_read":
        assert all(r["result"]["calls"][0]["input_tokens"] == 3 for r in records)
    mtimes = {p: p.stat().st_mtime_ns for p in run_dir.rglob("record.json")}
    assert run_cases(**kwargs)
    assert mtimes == {p: p.stat().st_mtime_ns for p in mtimes}


def test_ctrl_c_kills_inflight_tree_stops_queue_and_resumes_first_attempt(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("noop",), cases=[fakes.case(i) for i in range(1, 5)])
    kwargs["hooks"] = Hooks(platform=fakes.interrupt_platform, checker=fakes.checker,
                            inject=fakes.inject, load_arm=fakes.load_arm)
    original_result = Future.result
    captured = []

    def interrupt_result(future, timeout=None):
        assert timeout is not None and timeout <= 0.2
        paths = [tmp_path / f"runs/invented-{port}/interrupt-pids.json" for port in (8400, 8500)]
        deadline = time.monotonic() + 10
        while not all(path.exists() for path in paths) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert all(path.exists() for path in paths), "invented descendant processes did not start"
        for path in paths:
            captured.extend(json.loads(path.read_text()))
        raise KeyboardInterrupt

    monkeypatch.setattr(Future, "result", interrupt_result)
    with pytest.raises(KeyboardInterrupt):
        run_cases(**kwargs)
    run_dir = tmp_path / "results/fixture-run"
    assert json.loads((run_dir / "manifest.json").read_text())["complete"] is False
    assert not list(run_dir.glob("cases/*/*/record.json"))
    assert not (run_dir / "cases/fixture-3").exists()
    assert not (run_dir / "cases/fixture-4").exists()
    assert all(not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE for pid in captured)
    monkeypatch.setattr(Future, "result", original_result)
    kwargs["hooks"] = Hooks(platform=fakes.platform, checker=fakes.checker, inject=fakes.inject, load_arm=fakes.load_arm)
    assert run_cases(**kwargs)
    records = load_records(run_dir, effective=False)
    assert len(records) == 4
    assert all(r["attempt"] == 1 and r["purpose"] == "main" for r in records)


def test_injection_error_is_distinct_and_retried_once(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("noop",), cases=[fakes.case(1)])
    kwargs["hooks"] = Hooks(platform=fakes.platform, checker=fakes.checker, inject=fakes.broken_inject, load_arm=fakes.load_arm)
    assert run_cases(**kwargs)
    records = load_records(tmp_path / "results/fixture-run", effective=False)
    assert len(records) == 2
    assert all(r["error"]["stage"] == "inject" and r["injection_complete"] is False for r in records)


@pytest.mark.parametrize("source", ["case", "arm"])
def test_child_interrupt_cannot_publish_a_failure_or_start_next_pair(tmp_path, monkeypatch, source):
    arm = "noop" if source == "case" else "interrupted"
    kwargs = options(tmp_path, monkeypatch, names=(arm,), cases=[fakes.case(1), fakes.case(2)])
    kwargs["copies"] = 1
    kwargs["hooks"] = Hooks(platform=fakes.child_interrupt_platform if source == "case" else fakes.platform,
                            checker=fakes.checker, inject=fakes.inject, load_arm=fakes.load_arm)
    with pytest.raises(KeyboardInterrupt):
        run_cases(**kwargs)
    run_dir = tmp_path / "results/fixture-run"
    assert not list(run_dir.glob("cases/*/*/record.json"))
    assert not (run_dir / "cases/fixture-2").exists()
    assert json.loads((run_dir / "manifest.json").read_text())["complete"] is False
    if source == "case":
        pids = json.loads((tmp_path / "runs/invented-8400/child-interrupt-pids.json").read_text())
        assert all(not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE for pid in pids)
    kwargs["hooks"] = Hooks(platform=fakes.platform, checker=fakes.checker, inject=fakes.inject,
                            load_arm=fakes.load_arm if source == "case" else fakes.resumed_arm)
    assert run_cases(**kwargs)
    assert all(record["attempt"] == 1 for record in load_records(run_dir, effective=False))


def test_read_error_classification_preserves_later_exception(tmp_path, monkeypatch):
    kwargs = options(tmp_path, monkeypatch, names=("caught_read_then_error",), cases=[fakes.case(1)])
    kwargs["hooks"] = Hooks(platform=fakes.unreadable_platform, checker=fakes.checker,
                            inject=fakes.inject, load_arm=fakes.load_arm)
    assert run_cases(**kwargs)
    records = load_records(tmp_path / "results/fixture-run", effective=False)
    assert len(records) == 2
    for record in records:
        assert record["result"]["outcome"] == "harness_error"
        assert record["error"]["type"] == "CallError"
        assert record["error"]["kind"] == "refused"
        assert record["error"]["original"]["type"] == "ValueError"
        assert record["error"]["original"]["stage"] == "arm"


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
