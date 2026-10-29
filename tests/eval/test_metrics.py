"""Invented evidence tests of scoring, validity and denominator handling."""

from copy import deepcopy

import pytest

from eval.metrics import (assess_validity, case_strata, comparisons, outcome,
                          paired_rows, score_record, select_records, summarise)


def record(arm="abcde", *, healthy=False, must_escalate=False, recovered=True,
           verdict="recovered", case_id="invented-1"):
    root = {"target": "service-x", "class": "process_down",
            "fix": {"action": "escalate" if must_escalate else "restart", "target": "service-x"}}
    roots = [] if healthy else [root]
    return {
        "case": {"id": case_id, "input": {"system": "invented", "seed": 7,
                  "faults": [] if healthy else [{"type": "crash"}]},
                 "target": {"healthy": healthy, "must_escalate": must_escalate,
                            "root_causes": roots, "acceptable_secondary": []}},
        "arm": arm, "result": {"outcome": verdict, "root_causes": deepcopy(roots),
                               "actions": [], "sbar": {}, "calls": [], "escalation": None},
        "checker": {"recovered": recovered, "integrity": {"ok": recovered, "for_operations": []},
                    "impact": {"breach_seconds": 5, "failed_journeys": 4}},
        "manifest": deepcopy(roots), "injection_complete": True,
        "actions": [], "audit": [], "timing": {"t0": 100, "horizon": 210},
        "purpose": "main", "attempt": 1, "error": None,
    }


def valid_fixture():
    return [record(), record("runbook"), record("noop", recovered=False, verdict="no_incident"), record("oracle")]


def test_success_uses_checker_and_real_action_logs_not_arm_claims():
    row = record(healthy=True, verdict="no_incident")
    row["result"]["actions"] = [{"action": "restart", "ok": True}]
    assert score_record(row)["case_success"] is True
    row["actions"] = [{"action": "restart", "target": "service-x", "ok": True}]
    assert score_record(row)["case_success"] is False
    row = record(recovered=False)
    assert score_record(row)["case_success"] is False
    assert score_record(row)["false_all_clear"] is True


def test_harmful_refusal_read_from_audit_but_rate_limit_is_not_harm():
    row = record()
    row["audit"] = [{"event": "act", "action": "restart", "refused_reason": "rate_limited"}]
    assert score_record(row)["case_success"] is True
    row["audit"].append({"event": "act", "action": "delete", "refused_reason": "not_allowlisted"})
    result = score_record(row)
    assert result["case_success"] is False
    assert result["harmful_attempts"] == 1 and result["action_attempts"] == 2


def test_wrong_quarantine_unknown_without_standard_poison_verdict():
    row = record()
    row["actions"] = [{"action": "quarantine", "target": "service-x", "ok": True}]
    row["checker"]["integrity"]["wrongly_quarantined"] = 0
    result = score_record(row)
    assert result["harmful_quarantines"] is None and result["case_success"] is None
    assert result["handover_complete"] is False


def test_escalation_checks_labelled_target_even_when_checker_red():
    row = record(must_escalate=True, recovered=False, verdict="escalated")
    row["result"]["escalation"] = {"components": ["service-x"]}
    assert score_record(row)["case_success"] is True
    row["result"]["escalation"]["components"] = ["symptom-only"]
    assert score_record(row)["case_success"] is False


def test_secondary_diagnosis_is_ignored_and_confidence_never_filters():
    row = record()
    secondary = {"target": "downstream", "class": "dependency_slow"}
    row["case"]["target"]["acceptable_secondary"] = [secondary]
    row["result"]["root_causes"] += [secondary, {"target": "unrelated", "class": "bad_release", "confidence": 0.001}]
    scored = score_record(row)
    assert scored["root_tp"] == 1 and scored["root_fp"] == 1
    assert scored["root_precision"] == 0.5 and scored["root_recall"] == 1
    assert scored["root_f1"] == pytest.approx(2 / 3)


def test_malformed_reported_root_cause_cannot_disappear_from_precision():
    row = record()
    row["result"]["root_causes"].append({"target": "service-y", "class": None})
    assert score_record(row)["root_fp"] == 1


def test_healthy_diagnosis_is_binary_and_excluded_from_f1():
    row = record(healthy=True, verdict="no_incident")
    row["result"]["root_causes"] = [{"target": "x", "class": "process_down"}]
    scored = score_record(row)
    assert scored["false_diagnosis"] is True and scored["root_f1"] is None


def test_handover_names_each_item_with_identifier_boundary():
    row = record()
    row["checker"]["integrity"]["for_operations"] = [{"kind": "set_aside", "item": 12},
                                                      {"kind": "posted_twice", "payment_ids": ["p-8", "p-9"]}]
    row["result"]["sbar"] = {"recommendation": "Inspect item 120 and payment p-8."}
    assert score_record(row)["handover_complete"] is False
    row["result"]["sbar"] = {"recommendation": "Inspect item 12 and payment p-8."}
    assert score_record(row)["handover_complete"] is True


def test_api_failure_only_for_registered_last_call_and_terminal_outcome():
    row = {"outcome": "gave_up", "calls": [{"status": "failed", "error": "http_429"}]}
    assert outcome(row) == "api_error"
    row["calls"].append({"status": "invalid_output", "error": "invalid_json"})
    assert outcome(row) == "gave_up"
    row = {"outcome": "recovered", "calls": [{"status": "failed", "error": "timeout"}]}
    assert outcome(row) == "recovered"


def test_retry_selects_once_and_oracle_validation_never_overwrites():
    main = record(verdict="api_error")
    retry = record()
    retry.update(purpose="retry", attempt=2)
    third = record(verdict="gave_up")
    third.update(purpose="retry", attempt=3)
    oracle = record("oracle", recovered=False)
    recheck = record("oracle")
    recheck.update(purpose="oracle_recheck", attempt=2)
    selected = select_records([main, retry, third, oracle, recheck])
    assert selected == [retry, oracle]
    main["result"]["outcome"] = "gave_up"
    assert select_records([main, retry])[0] is main


def test_validity_fault_noop_green_and_double_red_oracle():
    rows = valid_fixture()
    assert assess_validity(rows)["invented-1"]["valid"] is True
    rows[2]["checker"]["recovered"] = True
    assert assess_validity(rows)["invented-1"]["reasons"] == ["fault case: noop is green"]
    rows[2]["checker"]["recovered"] = False
    rows[3]["checker"]["recovered"] = False
    assert assess_validity(rows)["invented-1"]["valid"] is None
    second = record("oracle", recovered=False)
    second.update(purpose="oracle_recheck", attempt=2)
    rows.append(second)
    assert assess_validity(rows)["invented-1"]["reasons"] == ["oracle is red on both validity runs"]
    second["checker"]["recovered"] = True
    assert assess_validity(rows)["invented-1"]["valid"] is True


def test_validity_injection_and_manifest_are_mechanical():
    rows = valid_fixture()
    rows[0]["manifest"] = []
    assert "manifest root causes differ from labels" in assess_validity(rows)["invented-1"]["reasons"]
    rows[0]["injection_complete"] = False
    rows[0]["error"] = {"stage": "inject", "type": "RuntimeError", "message": "invented"}
    assert "fault injection raised" in assess_validity(rows)["invented-1"]["reasons"]


def test_must_escalate_validity_stays_pending_until_contract_resolved():
    rows = [record("noop", must_escalate=True, recovered=False), record("oracle", must_escalate=True, recovered=False)]
    assert assess_validity(rows)["invented-1"]["valid"] is None
    rows[0]["checker"]["recovered"] = True
    assert assess_validity(rows)["invented-1"]["valid"] is False


def test_healthy_noop_red_invalid_without_oracle():
    rows = [record("noop", healthy=True, recovered=False)]
    assert assess_validity(rows)["invented-1"]["reasons"] == ["healthy case: noop is red"]


def test_time_to_mitigate_and_unknown_cost_not_fabricated():
    row = record()
    row["result"]["calls"] = [{"input_tokens": 10, "output_tokens": None, "estimated_cost_usd": None}]
    result = score_record(row)
    assert result["time_to_mitigate_s"] is None and result["mitigation_censored"] is None
    assert result["input_tokens"] == 10 and result["tokens"] is None and result["estimated_cost_usd"] is None
    assert result["user_impact_seconds"] == 5
    assert score_record(record())["estimated_cost_usd"] == 0
    row["telemetry_complete"] = False
    row["result"]["calls"] = []
    assert score_record(row)["model_calls"] is None
    assert score_record(row)["estimated_cost_usd"] is None


def test_summary_rates_keep_counts_and_infrastructure_not_failure():
    rows = valid_fixture()
    rows[0]["result"]["outcome"] = "harness_timeout"
    summary = summarise(rows)
    assert summary["overall"]["abcde"]["N"] == 0
    assert summary["overall"]["abcde"]["infrastructure_errors"] == 1
    assert summary["overall"]["runbook"]["rates"]["case_success"]["n"] == 1
    assert summary["overall"]["runbook"]["rates"]["case_success"]["N"] == 1
    assert len(summary["infrastructure_attempts"]) == 1


def test_pairs_require_identical_seed_and_include_all_registered_tests():
    rows = valid_fixture()
    comparison = comparisons(rows)
    assert comparison["primary"]["n"] == 1
    assert len(comparison["secondary"]) == 4
    rows[1]["case"]["input"]["seed"] = 99
    assert comparisons(rows)["primary"]["n"] == 0
    metrics = [score_record(row) for row in rows]
    assert paired_rows(metrics, "abcde", "runbook", "case_success") == ([], [])


def test_overlapping_strata_use_public_labels_only():
    case = record()["case"]
    case["input"]["faults"].append({"type": "poison_payment"})
    case["target"]["blind"] = True
    assert set(case_strata(case)) == {"named_heldout", "blind", "single"}
