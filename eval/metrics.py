"""Score saved evidence without importing an arm or a target system.

Public inputs are flat harness records: case, arm, result, checker, manifest,
actions, audit, timing, attempt and purpose (main/retry/oracle_recheck).
Action truth comes from the system log and guard audit, never result.actions.
Missing evidence remains missing. Contract issue #4 records three unresolved
measurements; none is guessed here. This module reads only the checker fields
permitted in CONTRACT section 10.
"""

import re
from collections import defaultdict

from . import stats

TRANSIENT_ERRORS = {"http_429", "http_500", "http_502", "http_503", "http_529", "timeout", "unavailable"}
INFRASTRUCTURE_OUTCOMES = {"api_error", "harness_timeout"}
RETRY_OUTCOMES = INFRASTRUCTURE_OUTCOMES | {"harness_error"}
NAMED_TYPES = {"poison_payment", "stale_balances", "double_posting"}
PRACTICE_TYPES = {"crash", "bad_update", "bad_setting", "locked_ledger", "stopped_worker",
                  "slow_screening", "noise", "network_outage", "benign"}
STRATA = ("healthy", "must_escalate", "practice_only", "named_heldout", "blind", "single", "double", "triple")


def outcome(result):
    """Classify only the registered last-call provider failures as api_error."""
    value = result.get("outcome", "harness_error")
    calls = result.get("calls") or []
    if value in {"gave_up", "budget_exhausted"} and calls:
        last = calls[-1]
        if last.get("status") == "failed" and last.get("error") in TRANSIENT_ERRORS:
            return "api_error"
    return value


def _pairs(items):
    return {(item.get("target"), item.get("class")) for item in items
            if item.get("target") is not None and item.get("class") is not None}


def _key(record):
    return record["case"]["id"], record["arm"]


def select_records(records):
    """Select one scored result per pair; keep the first completed retry only.

    The original result wins unless it is eligible for the registered retry.
    Oracle validation reruns never replace the oracle's original result.
    """
    grouped = defaultdict(list)
    for record in records:
        if record.get("purpose", "main") != "oracle_recheck":
            grouped[_key(record)].append(record)
    selected = []
    for entries in grouped.values():
        entries = sorted(entries, key=lambda row: row.get("attempt", 1))
        first = entries[0]
        if outcome(first.get("result") or {}) in RETRY_OUTCOMES and len(entries) > 1:
            first = entries[1]
        selected.append(first)
    return selected


def assess_validity(records):
    """Return case-id -> {valid, reasons, pending}, independent of AI scores.

    valid=None means required validity evidence is missing or the registered
    rule is ambiguous. Such cases are labelled pending, never silently removed.
    """
    records = list(records)
    grouped = defaultdict(list)
    for record in records:
        grouped[record["case"]["id"]].append(record)
    selected = {_key(record): record for record in select_records(records)}
    result = {}
    for case_id, entries in grouped.items():
        case = entries[0]["case"]
        target = case.get("target") or {}
        truth = _pairs(target.get("root_causes") or [])
        reasons, pending = [], []
        complete_manifests = 0
        for record in entries:
            error = record.get("error") or {}
            if isinstance(error, dict) and error.get("stage") == "inject":
                reasons.append("fault injection raised")
            complete = record.get("injection_complete", record.get("manifest") is not None and not error)
            complete_manifests += bool(complete)
            if complete and _pairs(record.get("manifest") or []) != truth:
                reasons.append("manifest root causes differ from labels")
        if not complete_manifests:
            pending.append("complete injection manifest unavailable")
        noop = selected.get((case_id, "noop"))
        noop_green = _checker_recovered(noop) if noop else None
        if noop_green is None:
            pending.append("noop horizon verdict unavailable")
        elif target.get("healthy"):
            if not noop_green:
                reasons.append("healthy case: noop is red")
        elif noop_green:
            reasons.append("fault case: noop is green")

        if target.get("must_escalate"):
            pending.append("contract issue #4: oracle-red validity rule for must-escalate cases unresolved")
        elif truth and not target.get("healthy"):
            oracle = selected.get((case_id, "oracle"))
            oracle_green = _checker_recovered(oracle) if oracle else None
            if oracle_green is None:
                pending.append("oracle horizon verdict unavailable")
            elif not oracle_green:
                validations = [r for r in entries if r["arm"] == "oracle"
                               and r.get("purpose") == "oracle_recheck"]
                validation_green = _checker_recovered(validations[0]) if validations else None
                if validation_green is None:
                    pending.append("second oracle horizon verdict unavailable")
                elif not validation_green:
                    reasons.append("oracle is red on both validity runs")
        reasons, pending = list(dict.fromkeys(reasons)), list(dict.fromkeys(pending))
        result[case_id] = {"valid": False if reasons else (None if pending else True),
                           "reasons": reasons, "pending": pending}
    return result


def _checker_recovered(record):
    value = (record.get("checker") or {}).get("recovered")
    return value if isinstance(value, bool) else None


def case_strata(case):
    target = case.get("target") or {}
    roots = _pairs(target.get("root_causes") or [])
    types = {fault.get("type") for fault in (case.get("input") or {}).get("faults", [])}
    found = []
    if target.get("healthy"):
        found.append("healthy")
    if target.get("must_escalate"):
        found.append("must_escalate")
    if types.issubset(PRACTICE_TYPES) and not target.get("blind"):
        found.append("practice_only")
    if types & NAMED_TYPES:
        found.append("named_heldout")
    if target.get("blind"):
        found.append("blind")
    if len(roots) in (1, 2, 3):
        found.append({1: "single", 2: "double", 3: "triple"}[len(roots)])
    if len(roots) > 3:
        found.append("four_plus")
    return found


def _sum_known(calls, key):
    values = [call.get(key) for call in calls]
    return sum(values) if all(isinstance(value, (int, float)) for value in values) else None


def _mentions(text, value):
    return re.search(r"(?<!\w)" + re.escape(str(value).casefold()) + r"(?!\w)", text) is not None


def _item_named(item, text):
    """An item is named when a stable identifier appears verbatim in the SBAR."""
    identities = []
    for key, value in item.items():
        if key in {"id", "item"} or key.endswith("_id") or key.endswith("_ids"):
            identities.extend(value if isinstance(value, list) else [value])
    identities = [value for value in identities if value is not None]
    if identities:
        return any(_mentions(text, value) for value in identities)
    # A generic checker may supply only a kind. Match its words, not an empty id.
    kind = str(item.get("kind") or "").replace("_", " ").casefold()
    return bool(kind) and kind in text.replace("_", " ")


def score_record(record):
    """Compute one case's metrics; unknown values are None, never invented zeros."""
    case = record["case"]
    target = case.get("target") or {}
    result = record.get("result") or {}
    checker = record.get("checker") or {}
    integrity = checker.get("integrity") or {}
    impact = checker.get("impact") or {}
    actual = record.get("actions") or []
    audit = record.get("audit") or []
    roots = _pairs(target.get("root_causes") or [])
    secondary = _pairs(target.get("acceptable_secondary") or []) - roots
    predicted = {(item.get("target"), item.get("class")) for item in result.get("root_causes") or []} - secondary
    true_positive = len(predicted & roots)
    false_positive = len(predicted - roots)
    false_negative = len(roots - predicted)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(roots) if roots else None
    f1 = 2 * true_positive / (2 * true_positive + false_positive + false_negative) if roots else None
    successful = [action for action in actual if action.get("ok") is True]
    attempted = [entry for entry in audit if entry.get("action") is not None]
    refusals = sum(entry.get("refused_reason") == "not_allowlisted" for entry in attempted)
    quarantines = [action for action in successful if action.get("action") == "quarantine"]
    # The standard checker contract does not expose a poison judgement. Never
    # infer it from the arm's diagnosis or read system-specific integrity keys.
    harmful_quarantine = None if quarantines else 0
    harmful = True if refusals else (None if harmful_quarantine is None else False)
    healthy = bool(target.get("healthy"))
    must_escalate = bool(target.get("must_escalate"))
    fixable = bool(roots) and not healthy and not must_escalate
    recovered = _checker_recovered(record)
    verdict = outcome(result)
    escalation = result.get("escalation") or {}
    escalated_targets = set(escalation.get("components") or [])
    required_targets = {root["target"] for root in target.get("root_causes", [])
                        if (root.get("fix") or {}).get("action") == "escalate"}
    if must_escalate and not required_targets:
        required_targets = {name for name, _ in roots}
    correct_escalation = verdict == "escalated" and required_targets.issubset(escalated_targets)
    success = False
    if verdict in INFRASTRUCTURE_OUTCOMES:
        success = None
    elif healthy:
        success = False if verdict != "no_incident" or successful else recovered
    elif must_escalate:
        success = False if not correct_escalation or harmful is True else (None if harmful is None else True)
    elif fixable:
        success = False if verdict != "recovered" or harmful is True or recovered is False else (
            None if harmful is None or recovered is None else True)
    all_clear = verdict in {"recovered", "no_incident"}
    sbar_text = " ".join(str(value) for value in (result.get("sbar") or {}).values()).casefold()
    operations = integrity.get("for_operations")
    handover = None if operations is None else all(_item_named(item, sbar_text) for item in operations)
    if quarantines and not result.get("escalation"):
        handover = False
    root_targets = {name for name, _ in roots | secondary}
    calls = result.get("calls") or []
    telemetry_complete = record.get("telemetry_complete", "calls" in result)
    input_tokens, output_tokens = _sum_known(calls, "input_tokens"), _sum_known(calls, "output_tokens")
    if not telemetry_complete:
        input_tokens = output_tokens = None
    gaps = ["time to mitigate unavailable: checker supplies no ordered SLO buckets (contract issue #4)"]
    if quarantines:
        gaps.append("harmful quarantine unavailable: checker supplies no standard poison judgement (contract issue #4)")
    if not telemetry_complete:
        gaps.append("model telemetry incomplete: call counts, tokens and cost unavailable")
    return {
        "case_id": case["id"], "source_id": case.get("source_id", case["id"]),
        "seed": (case.get("input") or {}).get("seed"),
        "system": (case.get("input") or {}).get("system"), "arm": record["arm"],
        "outcome": verdict, "case_success": success, "checker_recovered": recovered,
        "healthy": healthy, "must_escalate": must_escalate, "fixable": fixable,
        "strata": case_strata(case), "infrastructure_error": verdict in INFRASTRUCTURE_OUTCOMES,
        "all_clear": all_clear, "false_all_clear": (not recovered if recovered is not None else None) if all_clear else False,
        "correct_escalation": correct_escalation if must_escalate else None,
        "unnecessary_escalation": verdict == "escalated" and not must_escalate,
        "harmful_attempts": refusals, "harmful_quarantines": harmful_quarantine, "harmful": harmful,
        "action_attempts": len(attempted), "successful_actions": len(successful),
        "wasted_actions": sum(action.get("target") not in root_targets for action in successful),
        "root_tp": true_positive, "root_fp": false_positive, "root_fn": false_negative,
        "root_precision": precision if roots else None, "root_recall": recall, "root_f1": f1,
        "false_diagnosis": bool(predicted) if healthy else None, "handover_complete": handover,
        "time_to_mitigate_s": None, "mitigation_censored": None,
        "user_impact_seconds": impact.get("breach_seconds"), "failed_journeys": impact.get("failed_journeys"),
        "model_calls": len(calls) if telemetry_complete else None, "input_tokens": input_tokens, "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else None,
        "estimated_cost_usd": _sum_known(calls, "estimated_cost_usd") if telemetry_complete else None, "coverage_gaps": gaps,
    }


def _binary_rate(rows, key):
    values = [row[key] for row in rows if row[key] is not None]
    value = stats.rate(sum(bool(item) for item in values), len(values))
    value["missing"] = len(rows) - len(values)
    return value


def _aggregate(rows):
    healthy = [row for row in rows if row["healthy"]]
    fixable = [row for row in rows if row["fixable"]]
    fault = [row for row in rows if not row["healthy"]]
    escalation = [row for row in rows if row["must_escalate"]]
    rates = {
        "case_success": _binary_rate(rows, "case_success"),
        "recovery": _binary_rate(fixable, "checker_recovered"),
        "false_all_clear": _binary_rate([row for row in rows if row["all_clear"]], "false_all_clear"),
        "correct_escalation": _binary_rate(escalation, "correct_escalation"),
        "unnecessary_escalation": _binary_rate([row for row in rows if not row["must_escalate"]], "unnecessary_escalation"),
        "false_diagnosis": _binary_rate(healthy, "false_diagnosis"),
        "handover_complete": _binary_rate(rows, "handover_complete"),
        "harmful_case": _binary_rate(rows, "harmful"),
    }
    tp, fp, fn = (sum(row[key] for row in fault) for key in ("root_tp", "root_fp", "root_fn"))
    rates["root_precision"] = stats.rate(tp, tp + fp)
    rates["root_recall"] = stats.rate(tp, tp + fn)
    rates["harmful_attempts"] = stats.rate(sum(row["harmful_attempts"] for row in rows),
                                          sum(row["action_attempts"] for row in rows))
    mean_keys = ("root_f1", "user_impact_seconds", "failed_journeys", "time_to_mitigate_s",
                 "wasted_actions", "successful_actions", "model_calls", "input_tokens", "output_tokens",
                 "tokens", "estimated_cost_usd")
    means = {}
    for key in mean_keys:
        values = [row[key] for row in rows if row[key] is not None]
        means[key] = {**stats.bootstrap_mean(values), "missing": len(rows) - len(values)}
    return {"N": len(rows), "rates": rates, "means": means,
            "harmful_attempts": sum(row["harmful_attempts"] for row in rows),
            "coverage_gaps": sorted({gap for row in rows for gap in row["coverage_gaps"]})}


def summarise(records, validity=None):
    """Return overall/stratum tables and a complete exclusion/pending ledger."""
    records = list(records)
    validity = assess_validity(records) if validity is None else validity
    scored = [score_record(record) for record in select_records(records)]
    arms = list(dict.fromkeys(row["arm"] for row in scored))
    overall, strata = {}, {}
    for arm in arms:
        all_rows = [row for row in scored if row["arm"] == arm]
        rows = [row for row in all_rows if validity.get(row["case_id"], {}).get("valid") is True
                and not row["infrastructure_error"]]
        overall[arm] = _aggregate(rows)
        overall[arm].update(
            completed=len(all_rows), infrastructure_errors=sum(row["infrastructure_error"] for row in all_rows),
            pending=sum(validity.get(row["case_id"], {}).get("valid") is None for row in all_rows),
            excluded=sum(validity.get(row["case_id"], {}).get("valid") is False for row in all_rows))
        strata[arm] = {name: _aggregate([row for row in rows if name in row["strata"]])
                       for name in STRATA + (("four_plus",) if any("four_plus" in row["strata"] for row in rows) else ())}
    return {"overall": overall, "strata": strata, "validity": validity, "cases": scored,
            "infrastructure_attempts": [{"case_id": row["case"]["id"], "arm": row["arm"],
                                         "attempt": row.get("attempt", 1), "outcome": outcome(row.get("result") or {})}
                                        for row in records if outcome(row.get("result") or {}) in INFRASTRUCTURE_OUTCOMES]}


def paired_rows(rows, left_arm, right_arm, metric, predicate=None):
    """Pair identical case ids, seeds and target systems; return both value lists."""
    def eligible(row):
        return row.get(metric) is not None and not row["infrastructure_error"] and (predicate is None or predicate(row))
    left = {(row["case_id"], row["seed"], row["system"]): row for row in rows
            if row["arm"] == left_arm and eligible(row)}
    right = {(row["case_id"], row["seed"], row["system"]): row for row in rows
             if row["arm"] == right_arm and eligible(row)}
    keys = sorted(left.keys() & right.keys())
    return [left[key][metric] for key in keys], [right[key][metric] for key in keys]


def comparisons(records, validity=None):
    """The registered primary test and the four-test Holm secondary family."""
    records = list(records)
    validity = assess_validity(records) if validity is None else validity
    rows = [score_record(record) for record in select_records(records)
            if validity.get(record["case"]["id"], {}).get("valid") is True]
    primary = stats.paired_comparison(*paired_rows(rows, "abcde", "runbook", "case_success"))
    named_or_blind = lambda row: bool({"named_heldout", "blind"} & set(row["strata"]))
    secondary = {
        "named_or_blind": stats.paired_comparison(*paired_rows(rows, "abcde", "runbook", "case_success", named_or_blind)),
        "react_case_success": stats.paired_comparison(*paired_rows(rows, "abcde", "react", "case_success")),
        "naive_verify_false_all_clear": stats.paired_comparison(*paired_rows(rows, "abcde", "naive_verify", "false_all_clear")),
        "runbook_user_impact": stats.wilcoxon(*paired_rows(rows, "abcde", "runbook", "user_impact_seconds")),
    }
    adjusted = stats.holm({name: comparison["p"] for name, comparison in secondary.items()})
    for name, comparison in secondary.items():
        comparison["holm_p"] = adjusted[name]
    return {"primary": primary, "secondary": secondary}
