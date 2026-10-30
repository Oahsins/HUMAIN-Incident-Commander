"""Run fresh systems at a fixed horizon, with hard deadlines and durable evidence.

Each copy takes whole cases in round-robin order. Within a case every arm
uses a new system. Two process boundaries let us stop an over-budget arm
while its system remains alive for the independent verdict.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict, dataclass
import multiprocessing as mp
import os
from pathlib import Path
import random
import shutil
import signal
import threading
import time

import psutil

from ic import contract, inject, systems
from ic.kit.net import CallError
from . import arms
from .storage import (RETRY_OUTCOMES, effective_record, fingerprint, pair_dir,
                      read_json, read_jsonl, run_lock, safe_name, write_json)

API_ERRORS = {"http_429", "http_500", "http_502", "http_503", "http_529", "timeout", "unavailable"}


class RunStop:
    """Make requesting a stop and starting a new pair mutually exclusive."""
    def __init__(self):
        self.event = threading.Event()
        self.launch_lock = threading.Lock()

    def is_set(self):
        return self.event.is_set()

    def set(self):
        with self.launch_lock:
            self.event.set()

    def start(self, process):
        with self.launch_lock:
            if self.is_set():
                return False
            process.start()
            return True


@dataclass(frozen=True)
class Timing:
    warmup_s: float = contract.WARMUP_S
    alert_delay_s: float = contract.ALERT_DELAY_S
    budget_s: float = contract.AGENT_BUDGET_S
    soak_s: float = contract.SOAK_S
    check_window_s: float = contract.CHECK_WINDOW_S
    check_lag_s: float = contract.CHECK_LAG_S
    max_steps: int = contract.AGENT_MAX_STEPS
    arm_grace_s: float = 5.0
    watchdog_s: float = 300.0


def make_guard(adapter, **kwargs):
    from ic.guard import Guard
    return Guard(adapter, **kwargs)


@dataclass(frozen=True)
class Hooks:
    """Explicit injectable interfaces for invented, process-safe test fixtures."""
    platform: object = systems.platform
    checker: object = systems.checker
    inject: object = inject.apply
    load_arm: object = arms.load_arm
    guard: object = make_guard


def classify_result(result):
    result = dict(result)
    calls = result.get("calls") or []
    last = calls[-1] if calls else {}
    if (result.get("outcome") in {"gave_up", "budget_exhausted"}
            and last.get("status") == "failed" and last.get("error") in API_ERRORS):
        result["original_outcome"] = result["outcome"]
        result["outcome"] = "api_error"
    return result


def failed_result(arm, outcome, start=None):
    result = contract.empty_result(arm)
    result.update(outcome=outcome, t_start=start or time.time(), t_declared=time.time())
    return result


def replace_outcome(record, outcome, start=None):
    """Keep known call evidence when a harness failure changes the verdict."""
    previous = record.get("result") or {}
    replacement = failed_result(record["arm"], outcome, start)
    replacement["calls"] = previous.get("calls") or []
    record["result"] = replacement


def classify_read_errors(record):
    """The wrapper records failed reads even when an arm catches the error."""
    read_errors = [entry for entry in record["audit"] if entry.get("event") == "read_error"]
    if read_errors:
        original = record.get("error")
        replace_outcome(record, "harness_error", record["timing"].get("t_alert"))
        record["error"] = {"stage": "arm", "type": "CallError", "kind": read_errors[0].get("kind"),
                           "message": "The guard recorded a target-system read failure."}
        if original is not None:
            record["error"]["original"] = original


def mark_interrupted(directory):
    """A child can receive console Ctrl+C before the coordinating parent does."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    write_json(Path(directory) / "interrupted.json", {"event": "interrupted", "pid": os.getpid(), "t": time.time()})
    # Keep descendants from becoming orphans if this child finishes before the
    # parent notices the marker. The parent also kills any still-running tree.
    parent = psutil.Process()
    children = {}
    direct = set()
    while True:
        new = [child for child in parent.children(recursive=True) if child.pid not in children]
        if not new:
            break
        for child in new:
            try:
                child.suspend()
                children[child.pid] = child
                if child.ppid() == parent.pid:
                    direct.add(child.pid)
            except psutil.NoSuchProcess:
                pass
    for child in reversed(list(children.values())):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    # Direct children may belong to multiprocessing. Only their owning
    # Process.join may reap them on POSIX, or it loses their exit status.
    psutil.wait_procs([child for pid, child in children.items() if pid not in direct], timeout=5)


def was_interrupted(process, directory):
    # Windows reports STATUS_CONTROL_C_EXIT; POSIX may report SIGINT.
    return ((Path(directory) / "interrupted.json").exists()
            or process.exitcode in {-signal.SIGINT, 130, 0xC000013A, -1073741510})


def kill_tree(process):
    """Kill only descendants of the process this harness started."""
    if process.pid is None:
        return
    descendants = []
    try:
        parent = psutil.Process(process.pid)
        # Freeze before enumerating. Freeze each generation and rescan: a child
        # may have spawned another process between discovery and suspension.
        parent.suspend()
        discovered = {}
        while True:
            new = [child for child in parent.children(recursive=True) if child.pid not in discovered]
            if not new:
                break
            for child in new:
                try:
                    child.suspend()
                    discovered[child.pid] = child
                except psutil.NoSuchProcess:
                    pass
        descendants = list(discovered.values())
        for child in reversed(descendants):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
    except psutil.NoSuchProcess:
        pass
    # On Unix psutil.wait_procs calls waitpid for our direct child. If it
    # reaps this PID first, multiprocessing loses the exit status and may
    # continue to report is_alive(). Only multiprocessing may reap its child.
    process.join(timeout=5)
    psutil.wait_procs(descendants, timeout=5)


def _arm_worker(adapter, arm, model, seed, timing, audit, output, hooks, oracle_data):
    """The tested function gets only the contract's permitted arguments."""
    started = time.time()
    try:
        guarded = hooks.guard(adapter, mode="auto", max_steps=timing.max_steps, audit_path=str(audit))
        kwargs = {"budget_s": timing.budget_s, "max_steps": timing.max_steps,
                  "model": model, "seed": seed, "mode": "auto", "confirm": None, "log": None}
        if arm == "oracle":
            result = arms.oracle(guarded, root_causes=oracle_data[0], manifest=oracle_data[1], **kwargs)
        else:
            result = hooks.load_arm(arm)(guarded, **kwargs)
        if not isinstance(result, dict) or "outcome" not in result:
            raise ValueError("arm did not return a result")
        payload = {"result": classify_result(result), "error": None}
    except KeyboardInterrupt:
        mark_interrupted(Path(output).parent)
        return
    except CallError as exc:
        payload = {"result": failed_result(arm, "harness_error", started),
                   "error": {"stage": "arm", "type": "CallError", "kind": exc.kind,
                             "message": "The target system could not be read."}}
    except Exception as exc:
        payload = {"result": failed_result(arm, "arm_error", started),
                   "error": {"stage": "arm", "type": type(exc).__name__, "message": "Arm raised an exception."}}
    write_json(output, payload)


def _wait_until(epoch):
    delay = epoch - time.time()
    if delay > 0:
        time.sleep(delay)


def _copy_evidence(control, destination, audit):
    """Copy logs, but never parse the customer traffic log or copy credentials."""
    paths = control.paths()
    return _copy_paths(paths, destination, audit)


def _copy_paths(paths, destination, audit):
    destination = Path(destination)
    for key, name in (("actions", "actions.jsonl"), ("changes", "changes.jsonl"),
                      ("customers_log", "customers.jsonl")):
        source = paths.get(key)
        if key == "customers_log" and not source:
            source = paths.get("traffic_log")
        if source and Path(source).is_file():
            shutil.copy2(source, destination / name)
    log_dir = paths.get("logs")
    if log_dir and Path(log_dir).is_dir():
        shutil.copytree(log_dir, destination / "logs", dirs_exist_ok=True)
    if Path(audit).is_file():
        shutil.copy2(audit, destination / "audit.jsonl")
    return read_jsonl(destination / "actions.jsonl"), read_jsonl(destination / "audit.jsonl")


def _base_record(case, arm, port, attempt, purpose):
    return {"case": case, "arm": arm, "result": failed_result(arm, "harness_error"),
            "checker": None, "manifest": [], "injection_complete": False,
            "telemetry_complete": False,
            "actions": [], "audit": [], "timing": {}, "attempt": attempt,
            "purpose": purpose, "port_base": port, "error": None}


def _case_worker(root, name, case, arm, port, split, model, timing, hooks, destination, attempt, purpose):
    try:
        _run_case(root, name, case, arm, port, split, model, timing, hooks, destination, attempt, purpose)
    except KeyboardInterrupt:
        mark_interrupted(destination)


def _run_case(root, name, case, arm, port, split, model, timing, hooks, destination, attempt, purpose):
    os.chdir(root)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    audit_dir = Path(root) / "runs" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if purpose == "main" else f"-{purpose}"
    audit = audit_dir / f"{name}-{case['id']}-{arm}{suffix}.jsonl"
    # Only an incomplete attempt may reach this point. Start its audit afresh.
    audit.write_text("", encoding="utf-8")
    record = _base_record(case, arm, port, attempt, purpose)
    platform = control = arm_process = None
    stage = "start"
    try:
        data = case["input"]
        platform = hooks.platform(data["system"], port_base=port, seed=data["seed"], condition=data.get("condition", "default"))
        platform.start(warmup_s=timing.warmup_s)
        control = platform.control()
        evidence = control.paths()
        # Retain only public evidence paths, never a control token or datastore.
        evidence = {key: evidence.get(key) for key in ("actions", "changes", "customers_log", "traffic_log", "logs")}
        write_json(destination / "evidence-paths.json", {"paths": evidence, "audit": str(audit)})
        stage = "inject"
        scheduled_start = time.time()
        record["manifest"] = hooks.inject(data["system"], control, data.get("faults", []),
            seed=data["seed"], allow_sealed=split in {"heldout", "transfer"}, t0=scheduled_start)
        record["injection_complete"] = True
        stage = "alert"
        first_injection = min((m["t"] for m in record["manifest"]), default=scheduled_start)
        last_injection = max((m["t"] for m in record["manifest"]), default=scheduled_start)
        alert = max(time.time(), last_injection + timing.alert_delay_s)
        _wait_until(alert)
        horizon = alert + timing.budget_s + timing.soak_s
        record["timing"] = {"t0": first_injection, "t_alert": alert, "horizon": horizon}
        write_json(destination / "progress.json", record)
        stage = "arm"
        output = destination / "arm-output.json"
        output.unlink(missing_ok=True)
        # Scenario/manifest data is passed only to the oracle, never a tested arm.
        oracle_data = (case["target"].get("root_causes", []), record["manifest"]) if arm == "oracle" else None
        arm_process = mp.get_context("spawn").Process(target=_arm_worker,
            args=(platform.adapter(), arm, model, data["seed"], timing, audit, output, hooks, oracle_data))
        arm_process.start()
        arm_process.join(timeout=timing.budget_s + timing.arm_grace_s)
        if was_interrupted(arm_process, destination):
            raise KeyboardInterrupt
        if arm_process.is_alive():
            kill_tree(arm_process)
            record["result"] = failed_result(arm, "budget_exhausted", alert)
        else:
            payload = read_json(output)
            if payload is None:
                record["result"] = failed_result(arm, "arm_error", alert)
                record["error"] = {"stage": "arm", "type": "ProcessExit", "message": "Arm process exited without a result."}
            else:
                record["result"], record["error"] = payload["result"], payload["error"]
                record["telemetry_complete"] = payload["error"] is None
        stage = "checker"
        _wait_until(horizon + timing.check_lag_s)
        record["checker"] = hooks.checker(data["system"]).verify(control,
            window_s=timing.check_window_s, lag_s=timing.check_lag_s, since_t=first_injection)
        record["timing"]["verdict_t"] = time.time()
        stage = "evidence"
        record["actions"], record["audit"] = _copy_evidence(control, destination, audit)
    except KeyboardInterrupt:
        # Publish before cleanup, which may itself have to wait on a service.
        mark_interrupted(destination)
        raise
    except Exception as exc:
        replace_outcome(record, "harness_error", record["timing"].get("t_alert"))
        record["error"] = {"stage": stage, "type": type(exc).__name__,
                           "message": f"Harness failed during {stage}; inspect the retained system evidence."}
        if isinstance(exc, CallError):
            record["error"]["kind"] = exc.kind
    finally:
        if arm_process is not None and arm_process.is_alive():
            kill_tree(arm_process)
        if control is not None:
            try:
                record["actions"], record["audit"] = _copy_evidence(control, destination, audit)
            except Exception:
                pass
        if platform is not None:
            try:
                platform.stop()
            except Exception as exc:
                if record["error"] is None:
                    record["error"] = {"stage": "stop", "type": type(exc).__name__, "message": "System cleanup failed."}
                    replace_outcome(record, "harness_error")
    classify_read_errors(record)
    write_json(destination / "result.json", record["result"])
    write_json(destination / "record.json", record)


def run_pair(root, name, case, arm, port, split, model, timing, hooks, destination, attempt=1, purpose="main", stop=None):
    destination = Path(destination)
    if stop is not None and stop.is_set():
        return
    if read_json(destination / "record.json") is not None:
        return
    destination.mkdir(parents=True, exist_ok=True)
    expected_root = (Path(root) / "results" / name / "cases").resolve()
    if not destination.resolve().is_relative_to(expected_root):
        raise ValueError("case output path escapes its run")
    # A crash can leave partial evidence. It must not contaminate a resumed try.
    for filename in ("result.json", "progress.json", "arm-output.json", "evidence-paths.json", "actions.jsonl", "changes.jsonl", "customers.jsonl", "audit.jsonl", "interrupted.json"):
        (destination / filename).unlink(missing_ok=True)
    logs = destination / "logs"
    if logs.exists():
        if logs.is_symlink() or not logs.resolve().is_relative_to(expected_root):
            raise ValueError("case log directory escapes its run")
        shutil.rmtree(logs)
    process = mp.get_context("spawn").Process(target=_case_worker,
        args=(str(root), name, case, arm, port, split, model, timing, hooks, str(destination), attempt, purpose))
    if stop is None:
        process.start()
    elif not stop.start(process):
        return
    cancelled = False
    try:
        deadline = time.monotonic() + timing.watchdog_s
        while process.is_alive():
            if was_interrupted(process, destination):
                raise KeyboardInterrupt
            if stop is not None and stop.is_set():
                cancelled = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            process.join(timeout=min(0.1, remaining))
        if was_interrupted(process, destination):
            raise KeyboardInterrupt
        cancelled = cancelled or (stop is not None and stop.is_set())
    except BaseException:
        cancelled = True
        if stop is not None:
            stop.set()
        raise
    finally:
        if cancelled:
            if process.is_alive():
                kill_tree(process)
            # A child may have reached its atomic write while Ctrl+C arrived.
            # It is still in flight until this parent accepts its result.
            for filename in ("result.json", "record.json"):
                (destination / filename).unlink(missing_ok=True)
    if cancelled:
        return
    if process.is_alive():
        kill_tree(process)
        outcome, message = "harness_timeout", "Per-case watchdog expired."
    else:
        outcome, message = "harness_error", "Case process exited without a complete result."
    if read_json(destination / "record.json") is None:
        record = read_json(destination / "progress.json") or _base_record(case, arm, port, attempt, purpose)
        returned = read_json(destination / "arm-output.json")
        if returned is not None:
            record["result"] = returned["result"]
        replace_outcome(record, outcome, record["timing"].get("t_alert"))
        record["telemetry_complete"] = False
        record["error"] = {"stage": "watchdog" if outcome == "harness_timeout" else "process", "type": "ProcessExit", "message": message}
        evidence = read_json(destination / "evidence-paths.json")
        if evidence:
            try:
                record["actions"], record["audit"] = _copy_paths(evidence["paths"], destination, evidence["audit"])
            except (OSError, ValueError):
                pass
        classify_read_errors(record)
        write_json(destination / "result.json", record["result"])
        write_json(destination / "record.json", record)
    completed = read_json(destination / "record.json")
    print(f"{name}: {case['id']} / {arm} / {purpose}: {completed['result']['outcome']}", flush=True)


def case_order(cases, names):
    rng = random.Random(0)
    plan = []
    for case in cases:
        shuffled = list(names)
        rng.shuffle(shuffled)
        plan.append((case, shuffled))
    return plan


def run_cases(root, *, name, cases, arm_names, split, models, copies, port_bases,
              provenance, timing=None, hooks=None):
    """Return true only when all requested pairs have durable results."""
    root = Path(root).resolve()
    timing, hooks = timing or Timing(), hooks or Hooks()
    safe_name(name)
    if not cases or not arm_names:
        raise ValueError("select at least one case and arm")
    if copies < 1 or copies > len(port_bases):
        raise ValueError("copies must be between 1 and the number of port bases")
    if len(set(c["id"] for c in cases)) != len(cases):
        raise ValueError("case ids must be unique")
    for case in cases:
        safe_name(case["id"])
    for arm in arm_names:
        safe_name(arm)
    ports = port_bases[:copies]
    if any(p < 1024 or p > 65526 for p in ports) or any(abs(a-b) < 10 for i,a in enumerate(ports) for b in ports[i+1:]):
        raise ValueError("port ranges must be valid and must not overlap")
    run_dir = root / "results" / name
    configuration = {"split": split, "case_ids": [c["id"] for c in cases], "scenario_hash": fingerprint(cases),
        "arms": list(arm_names), "models": models, "copies": copies, "port_bases": ports,
        "timing": asdict(timing), "provenance": provenance}
    with run_lock(run_dir):
        previous = read_json(run_dir / "manifest.json")
        if previous is not None and previous["configuration"] != configuration:
            raise ValueError("run name already exists with different inputs, settings or source hashes")
        manifest = previous or {"name": name, "created_t": time.time(), "configuration": configuration,
                                "git_commit": provenance.get("git_commit"), "hashes": provenance.get("hashes", {}),
                                "split": split, "arms": list(arm_names),
                                "condition": cases[0]["input"].get("condition", "default") if len({c["input"].get("condition", "default") for c in cases}) == 1 else "mixed"}
        manifest["complete"] = False
        write_json(run_dir / "manifest.json", manifest)
        plan = case_order(cases, arm_names)
        stop = RunStop()

        def copy_work(copy, phase):
            for case, ordered_arms in plan[copy::copies]:
                for arm in ordered_arms:
                    if stop.is_set():
                        return
                    directory = pair_dir(run_dir, case["id"], arm)
                    primary = read_json(directory / "record.json")
                    destination, attempt, purpose = directory, 1, "main"
                    if phase == "retry":
                        if primary is None or primary["result"]["outcome"] not in RETRY_OUTCOMES | {"harness_error"}:
                            continue
                        destination, attempt, purpose = directory / "retry", 2, "retry"
                    elif phase == "oracle":
                        effective = effective_record(directory)
                        if (arm != "oracle" or case["target"].get("must_escalate")
                            or not case["target"].get("root_causes") or effective is None
                            or effective["result"]["outcome"] in RETRY_OUTCOMES | {"harness_error"}
                            or not isinstance(effective.get("checker"), dict)
                            or effective["checker"].get("recovered") is not False
                            or case["input"].get("condition", "default") not in {"default", "four_faults", "extra_service"}):
                            continue
                        destination, attempt, purpose = directory / "oracle-validation", 3, "oracle_recheck"
                    elif phase == "oracle_retry":
                        validation = read_json(directory / "oracle-validation" / "record.json")
                        if (arm != "oracle" or case["target"].get("must_escalate") or validation is None
                            or validation["result"]["outcome"] not in RETRY_OUTCOMES | {"harness_error"}):
                            continue
                        destination = directory / "oracle-validation" / "retry"
                        attempt, purpose = 4, "oracle_recheck_retry"
                    model = models.get(case["id"])
                    run_pair(root, name, case, arm, ports[copy], split, model, timing, hooks,
                             destination, attempt, purpose, stop)

        try:
            for phase in ("main", "retry", "oracle", "oracle_retry"):
                pool = ThreadPoolExecutor(max_workers=copies)
                try:
                    futures = [pool.submit(copy_work, copy, phase) for copy in range(copies)]
                    for future in futures:
                        while True:
                            try:
                                # An unlimited wait can hide Ctrl+C on Windows.
                                future.result(timeout=0.1)
                                break
                            except FutureTimeout:
                                if future.done():
                                    # Distinguish a worker's TimeoutError from
                                    # a timed wait that raced its completion.
                                    future.result(timeout=0)
                                    break
                                continue
                except BaseException:
                    stop.set()
                    raise
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)
        finally:
            complete = not stop.is_set() and all(read_json(pair_dir(run_dir, c["id"], a) / "record.json") is not None for c in cases for a in arm_names)
            manifest["complete"] = complete
            manifest["updated_t"] = time.time()
            write_json(run_dir / "manifest.json", manifest)
            from .report import update_run_index
            update_run_index(run_dir)
    return complete
