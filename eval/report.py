"""Turn retained evidence into tables, paired comparisons and an honest run index.

Scoring lives in metrics.py. This file connects those calculations to the
report and plots, without loading an arm, an injector or customer traffic.
"""

import csv
from datetime import datetime, timezone
import io
import os
from pathlib import Path

from . import metrics, stats
from .storage import load_records, read_json, run_lock, write_json


def _presentation_group(group):
    rate_names = {"false_diagnosis": "healthy_false_diagnosis", "harmful_case": "harmful_action"}
    mean_names = {"user_impact_seconds": "user_impact_s", "estimated_cost_usd": "cost_usd",
                  "root_f1": "root_cause_f1"}
    denominators = {
        "case_success": "valid cases with an observed success verdict",
        "recovery": "fixable cases with a checker verdict",
        "false_all_clear": "all-clear claims with a checker verdict",
        "correct_escalation": "valid must-escalate cases",
        "unnecessary_escalation": "valid fixable or healthy cases",
        "false_diagnosis": "valid healthy cases",
        "handover_complete": "valid cases with operations handover evidence",
        "harmful_case": "valid cases with observed harm status",
        "root_precision": "reported root-cause pairs after acceptable secondary pairs are ignored",
        "root_recall": "labelled root-cause pairs",
        "harmful_attempts": "guard-audited action attempts",
    }
    return {
        "n": group["N"],
        "rates": {rate_names.get(key, key): {**value, "estimate": value["rate"],
                  "denominator": denominators.get(key, "observed cases")}
                  for key, value in group["rates"].items()},
        "means": {mean_names.get(key, key): value for key, value in group["means"].items()},
    }


def _condition(records):
    conditions = {r["case"]["input"].get("condition", "default") for r in records}
    return next(iter(conditions)) if len(conditions) == 1 else "mixed"


def _validity(records, reference=None):
    validity = metrics.assess_validity(records)
    if reference is None:
        return validity
    reference_validity = metrics.assess_validity(reference)
    reference_cases = {(r["case"]["id"], r["case"]["input"]["seed"], r["case"]["input"]["system"])
                       for r in reference}
    for record in records:
        case, data = record["case"], record["case"]["input"]
        # These conditions reuse incidents. New fault variants need their own
        # noop/oracle evidence and never inherit a main run's validity.
        if data.get("condition") not in {"model_swap", "log_format_v2"}:
            continue
        source = case.get("source_id", case["id"])
        if (source, data["seed"], data["system"]) not in reference_cases:
            continue
        own = validity[case["id"]]
        inherited = reference_validity.get(source)
        if not own["reasons"] and inherited is not None:
            remaining = [reason for reason in own["pending"] if not reason.startswith(
                ("noop horizon", "oracle horizon", "second oracle horizon"))]
            pending = list(dict.fromkeys(inherited["pending"] + remaining))
            validity[case["id"]] = {**inherited, "pending": pending, "inherited_from": source,
                "valid": False if inherited["reasons"] else (None if pending else inherited["valid"])}
    return validity


def _comparisons(records, validity):
    values = metrics.comparisons(records, validity)
    out = [{**values["primary"], "label": "ABCDE vs runbook", "endpoint": "case success",
            "method": "Exact McNemar; paired bootstrap", "family": "primary", "p_adjusted": None}]
    labels = {
        "named_or_blind": ("ABCDE vs runbook, named held-out or blind", "case success"),
        "react_case_success": ("ABCDE vs ReAct", "case success"),
        "naive_verify_false_all_clear": ("ABCDE vs naive verification", "false all-clear"),
        "runbook_user_impact": ("ABCDE vs runbook", "user-impact seconds"),
    }
    for key, comparison in values["secondary"].items():
        label, endpoint = labels[key]
        out.append({**comparison, "label": label, "endpoint": endpoint, "family": "secondary",
                    "p_adjusted": comparison.get("holm_p"),
                    "method": "Wilcoxon signed-rank" if key == "runbook_user_impact"
                    else "Exact McNemar; paired bootstrap"})
    return out


def _robustness(records, validity, reference, reference_validity):
    current = [metrics.score_record(r) for r in metrics.select_records(records)
               if validity.get(r["case"]["id"], {}).get("valid") is True]
    previous = [metrics.score_record(r) for r in metrics.select_records(reference)
                if reference_validity.get(r["case"]["id"], {}).get("valid") is True]
    reference_map = {(r["case_id"], r["seed"], r["system"], r["arm"]): r for r in previous}
    out = []
    for arm in dict.fromkeys(r["arm"] for r in current):
        left, right = [], []
        for row in current:
            if row["arm"] != arm or row["infrastructure_error"]:
                continue
            matched = reference_map.get((row["source_id"], row["seed"], row["system"], arm))
            if (matched is None or matched["infrastructure_error"]
                    or row["case_success"] is None or matched["case_success"] is None):
                continue
            left.append(row["case_success"])
            right.append(matched["case_success"])
        # Paired change is descriptive; do not add another hypothesis test.
        out.append({**stats.paired_bootstrap(left, right), "label": f"{arm}: condition vs main",
                    "endpoint": "case success", "family": "descriptive", "p": None,
                    "p_adjusted": None, "method": "Paired bootstrap, paired by source_id/seed/system",
                    "b": sum(a and not b for a, b in zip(left, right)),
                    "c": sum(not a and b for a, b in zip(left, right)),
                    "current_rate": stats.rate(sum(left), len(left)),
                    "reference_rate": stats.rate(sum(right), len(right))})
    return out


def _baseline_text(summary, validity):
    rows = [row for row in summary["cases"] if validity[row["case_id"]]["valid"] is True]
    left, right = metrics.paired_rows(rows, "abcde", "runbook", "case_success")
    if not left:
        return "No valid paired ABCDE/runbook case-success comparison is available."
    wins = sum(b and not a for a, b in zip(left, right))
    ties = sum(a == b for a, b in zip(left, right))
    def count(n):
        lo, hi = stats.wilson(n, len(left))
        return f"{n}/{len(left)} (95% Wilson {lo:.1%}–{hi:.1%})"
    text = f"The runbook wins on {count(wins)} paired cases and ties on {count(ties)}."
    if wins:
        amap = {(r["case_id"], r["seed"], r["system"]): r for r in rows if r["arm"] == "abcde"}
        ids = [r["case_id"] for r in rows if r["arm"] == "runbook" and r["case_success"] is True
               and amap.get((r["case_id"], r["seed"], r["system"]), {}).get("case_success") is False]
        text += " Runbook wins: " + ", ".join(sorted(ids)) + "."
    return text


def build_summary(run_dir, against=None):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    if manifest is None:
        raise ValueError("run manifest does not exist")
    records = load_records(run_dir, effective=False)
    reference = load_records(against, effective=False) if against is not None else None
    if against is not None and read_json(Path(against) / "manifest.json") is None:
        raise ValueError("comparison run manifest does not exist")
    validity = _validity(records, reference)
    measured = metrics.summarise(records, validity)
    configuration = manifest.get("configuration", {})
    split = configuration.get("split", "unknown")
    case_ids = configuration.get("case_ids", [])
    scope = {"heldout": "Held-out evaluation", "transfer": "Transfer evaluation"}.get(split, "Practice evaluation — not exam evidence")
    if split == "dev" and case_ids:
        # Pilot status comes from ids, not a run name supplied by the caller.
        if all(c in {f"dev-{i:02}" for i in range(21, 31)} for c in case_ids):
            scope = "Pilot evaluation — internal, not exam evidence"
    if manifest.get("synthetic"):
        scope = "Synthetic fixture — not experiment evidence"
    arms = []
    notes = set()
    for arm, group in measured["overall"].items():
        arms.append({"name": arm, **_presentation_group(group),
                     "strata": {key: _presentation_group(value) for key, value in measured["strata"][arm].items()}})
        notes.update(group["coverage_gaps"])
        notes.add(f"{arm}: {group['completed']} completed pairs; {group['pending']} pending validity; "
                  f"{group['excluded']} invalid; {group['infrastructure_errors']} unresolved infrastructure failures.")
    exclusions = [{"case_id": case, "reason": reason}
                  for case, value in validity.items() for reason in value["reasons"]]
    for case, value in validity.items():
        if value["valid"] is None:
            notes.add(f"Pending validity — {case}: " + "; ".join(value["pending"]))
    effective = {(r["case"]["id"], r["arm"]): r for r in metrics.select_records(records)}
    retries = []
    for record in records:
        if record.get("purpose", "main") != "main":
            continue
        initial = metrics.outcome(record["result"])
        if initial in metrics.RETRY_OUTCOMES:
            selected = effective[(record["case"]["id"], record["arm"])]
            retries.append({"case_id": record["case"]["id"], "arm": record["arm"], "initial": initial,
                            "retry": metrics.outcome(selected["result"]) if selected is not record else "not completed"})
    comparisons = _comparisons(records, validity)
    condition = _condition(records)
    if split != "heldout" or condition != "default":
        rows = [row for row in measured["cases"] if validity[row["case_id"]]["valid"] is True]
        for comparison in comparisons:
            if comparison["endpoint"] == "user-impact seconds":
                comparison.update(stats.paired_bootstrap(*metrics.paired_rows(
                    rows, "abcde", "runbook", "user_impact_seconds")))
            comparison.update(p=None, p_adjusted=None, family="descriptive", method="Paired bootstrap")
    if against is not None:
        comparisons += _robustness(records, validity, reference, metrics.assess_validity(reference))
        notes.add("Robustness changes are descriptive; positive difference means higher success under the condition.")
    if split != "heldout" or condition != "default":
        notes.add("Comparisons here are descriptive; the registered hypothesis tests concern the main valid sealed cases.")
    notes.add("Unknown measurements remain unavailable. Rates use their stated observed denominator; missing values are listed in metrics.json.")
    models = sorted({model for model in configuration.get("models", {}).values() if model})
    stage = "pilot" if scope.startswith("Pilot") else {"dev": "practice", "heldout": "exam", "transfer": "transfer"}.get(split)
    return {"run": manifest.get("name", run_dir.name), "split": split, "condition": condition,
            "stage": stage, "scope_label": scope,
            "manifest": {**manifest, "model": ", ".join(models) if models else "none recorded for these arms"},
            "arms": arms, "comparisons": comparisons,
            "exclusions": exclusions, "retries": retries, "notes": sorted(notes),
            "runbook_comparison": _baseline_text(measured, validity),
            "against": Path(against).name if against is not None else None,
            "measurements": measured}


def update_run_index(run_dir):
    """Upsert each arm's row while retaining every other run's history."""
    run_dir = Path(run_dir)
    with run_lock(run_dir.parent / ".index-writer"):
        return _update_run_index(run_dir)


def _update_run_index(run_dir):
    """The index writer holds a separate lock from each named run."""
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    if manifest is None:
        raise ValueError("run manifest does not exist")
    records = metrics.select_records(load_records(run_dir, effective=False))
    configuration = manifest.get("configuration", {})
    path = run_dir.parent / "runs.csv"
    fields = ["run", "time_utc", "git_commit", "agent_hash", "arm", "split", "condition", "n",
              "recovered_n", "recovered_N", "recovered_wilson_low", "recovered_wilson_high",
              "false_all_clear_n", "false_all_clear_N", "false_all_clear_wilson_low", "false_all_clear_wilson_high",
              "infrastructure_errors", "validity"]
    existing = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != fields:
                raise ValueError("runs.csv schema differs; preserve it and reconcile before writing")
            existing = list(reader)
    rows = []
    for arm in configuration.get("arms", sorted({r["arm"] for r in records})):
        scores = [metrics.score_record(r) for r in records if r["arm"] == arm]
        eligible = [r for r in scores if not r["infrastructure_error"]]
        fixable = [r for r in eligible if r["fixable"] and r["checker_recovered"] is not None]
        claims = [r for r in eligible if r["all_clear"] and r["false_all_clear"] is not None]
        recovery = stats.rate(sum(r["checker_recovered"] for r in fixable), len(fixable))
        all_clear = stats.rate(sum(r["false_all_clear"] for r in claims), len(claims))
        rows.append({"run": manifest.get("name", run_dir.name),
                     "time_utc": datetime.fromtimestamp(manifest.get("created_t", 0), timezone.utc).isoformat(),
                     "git_commit": manifest.get("git_commit"), "agent_hash": manifest.get("hashes", {}).get("agent"),
                     "arm": arm, "split": configuration.get("split"), "condition": _condition(records), "n": len(scores),
                     "recovered_n": recovery["n"], "recovered_N": recovery["N"],
                     "recovered_wilson_low": recovery["low"], "recovered_wilson_high": recovery["high"],
                     "false_all_clear_n": all_clear["n"], "false_all_clear_N": all_clear["N"],
                     "false_all_clear_wilson_low": all_clear["low"], "false_all_clear_wilson_high": all_clear["high"],
                     "infrastructure_errors": sum(r["infrastructure_error"] for r in scores),
                     "validity": "raw run ledger; see report for validity exclusions"})
    keys = {(row["run"], row["arm"]) for row in rows}
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows([row for row in existing if (row["run"], row["arm"]) not in keys] + rows)
    temporary = path.with_name(f"runs.{os.getpid()}.tmp")
    temporary.write_text(output.getvalue(), encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return path


def write_report(run_dir, against=None):
    """Write reproducible machine-readable metrics, Markdown and three charts."""
    from .presentation import render_report
    run_dir = Path(run_dir)
    summary = build_summary(run_dir, against)
    write_json(run_dir / "metrics.json", summary.pop("measurements"))
    write_json(run_dir / "summary.json", summary)
    path = render_report(summary, run_dir)
    update_run_index(run_dir)
    return path
