"""Write the evaluation report (report.md) and its charts from a summary dict.

render_report(summary, output_dir) writes output_dir/report.md, calls
eval.plots.draw_charts for the three PNG charts, and returns the report path.

The report is built for Omar and the hackathon judges. It reads in this order:
scope, what was run, the headline comparison against the scripted runbook
(ties and wins included), every paired comparison, the charts, every arm's
rates and means, every stratum, exclusions, retries, notes, limits and a
glossary. Every rate is shown as n/N with its 95% Wilson interval; a value the
scorer did not supply is shown as "unavailable", never as zero. The report
makes no claim from intervals that overlap or not: arms are compared only by
the paired comparisons the scorer supplies, and only the main held-out run's
primary and secondary rows carry a test. Strata, robustness, practice, pilot
and transfer results are descriptive.
"""

from pathlib import Path

from eval.plots import arm_label, draw_charts, is_synthetic, ordered_arms, stage_label

RATE_METRICS = {
    "case_success": ("Case success (primary endpoint)", "valid cases"),
    "recovery": ("Recovery (checker says recovered)", "fixable cases"),
    "false_all_clear": ("False all-clear (lower is better)", "cases where the arm claimed all clear"),
    "unnecessary_escalation": ("Unnecessary escalation (lower is better)", "fixable or healthy cases"),
    "harmful_action": ("Harmful action (lower is better)", "valid cases with observed harm status"),
    "handover_complete": ("Handover complete",
                          "valid cases with operations-handover evidence (an empty list counts as complete)"),
    "healthy_false_diagnosis": ("False diagnosis on healthy cases (lower is better)", "healthy cases"),
    "correct_escalation": ("Correct escalation", "must-escalate cases"),
    "root_precision": ("Root-cause precision", "reported (target, class) pairs"),
    "root_recall": ("Root-cause recall", "labelled root causes"),
    "harmful_attempts": ("Harmful-action attempts (lower is better)", "as defined by the scorer"),
    "mitigation_censored": ("Mitigation still unresolved at the horizon (lower is better)",
                            "cases with a known mitigation censor status"),
}
MEAN_METRICS = {
    "user_impact_s": ("User-impact seconds (lower is better)", "seconds"),
    "time_to_mitigate_s": ("Time to mitigate (lower is better)", "seconds"),
    "failed_journeys": ("Failed user journeys per case (lower is better)", "count"),
    "tokens": ("Model tokens per case", "tokens"),
    "input_tokens": ("Model input tokens per case", "tokens"),
    "output_tokens": ("Model output tokens per case", "tokens"),
    "cost_usd": ("Model cost per case (USD)", "usd"),
    "model_calls": ("Model calls per case", "count"),
    "root_cause_f1": ("Root-cause F1", "f1"),
    "root_precision": ("Root-cause precision", "f1"),
    "root_recall": ("Root-cause recall", "f1"),
    "successful_actions": ("Successful actions per case", "count"),
    "wasted_actions": ("Wasted actions per case (lower is better)", "count"),
    "harmful_attempts": ("Harmful-action attempts per case (lower is better)", "count"),
    "harmful_quarantines": ("Harmful quarantines per case (lower is better)", "count"),
}
STRATUM_ORDER = ["healthy", "must_escalate", "practice_only", "practice", "practice_types", "named_heldout",
                 "heldout_named", "blind", "single", "double", "triple", "four_plus"]
STRATUM_LABELS = {
    "healthy": "Healthy cases (no fault)",
    "must_escalate": "Must-escalate cases",
    "practice_only": "Practice fault types only (no named held-out or blind fault)",
    "practice": "Practice fault types only",
    "practice_types": "Practice fault types only",
    "named_heldout": "Named held-out fault types",
    "heldout_named": "Named held-out fault types",
    "blind": "Blind fault type",
    "single": "Single-fault and healthy cases",
    "double": "Two-fault cases",
    "triple": "Three-fault cases",
    "four_plus": "Four or more faults",
}
INFRASTRUCTURE_ERRORS = {"harness_timeout", "api_error"}
ARM_NOTES = {
    "abcde": "The full system: fixed ABCDE survey, triage order, sustained verification, SBAR handover.",
    "runbook": "Scripted runbook with no AI; the baseline the system must beat.",
    "react": "Free-form agent with the same tools and model, no fixed survey or triage order.",
    "naive_verify": "The full system, but 'errors stopped' counts as recovered; compared on false all-clears.",
    "fifo": "The full system, fixing problems in the order found.",
    "noop": "Harness reference: does nothing. Used to check that cases are valid.",
    "oracle": "Harness reference: applies the labelled fixes. Used to check that cases are fixable.",
}


# ---------- formatting ----------

def md(text):
    """Make a value safe inside a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def pct(value):
    return "unavailable" if value is None else f"{value:.0%}"


def fmt_value(value, kind):
    if value is None:
        return "unavailable"
    if kind == "seconds":
        return f"{value:,.1f} s"
    if kind == "tokens":
        return f"{value:,.0f}"
    if kind == "usd":
        return "$0" if value == 0 else f"${value:,.4f}"
    if kind == "f1":
        return f"{value:.2f}"
    if kind == "count":
        return f"{value:,.1f}"
    return f"{value:,.3g}"


def mean_kind(metric):
    if metric in MEAN_METRICS:
        return MEAN_METRICS[metric][1]
    return "seconds" if metric.endswith("_s") else "other"


def rate_cells(rate):
    """n/N, estimate and Wilson interval cells for one rate."""
    if not rate:
        return ["not reported", "—", "—"]
    n, total = rate.get("n"), rate.get("N")
    if not total:
        return [f"{n or 0}/{total or 0} (not estimable)", "—", "—"]
    low, high = rate.get("low"), rate.get("high")
    interval = "unavailable" if low is None or high is None else f"{pct(low)}–{pct(high)}"
    return [f"{n}/{total}", pct(rate.get("estimate")), interval]


def mean_cells(mean, kind):
    if not mean:
        return ["—", "not reported", "—"]
    low, high = mean.get("low"), mean.get("high")
    interval = ("unavailable" if low is None or high is None
                else f"{fmt_value(low, kind)}–{fmt_value(high, kind)}")
    n = mean.get("n")
    return ["unavailable" if n is None else str(n), fmt_value(mean.get("mean"), kind), interval]


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(md(c) for c in row) + " |" for row in rows]
    return lines


def metric_keys(dicts, known):
    """Known metrics in their fixed order, then any extra metric keys, sorted."""
    present = {k for d in dicts for k in (d or {})}
    return [k for k in known if k in present] + sorted(present - set(known))


def p_text(p):
    if p is None:
        return "unavailable"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def signed(value, in_seconds):
    """A paired difference: seconds for user impact, percentage points for rates."""
    if value is None:
        return "unavailable"
    return f"{value:+,.1f} s" if in_seconds else f"{value * 100:+.0f} pts"


def difference_text(c):
    endpoint = (c.get("endpoint") or "").lower()
    in_seconds = "second" in endpoint or "impact" in endpoint
    low, high = c.get("low"), c.get("high")
    interval = ("unavailable" if low is None or high is None
                else f"{signed(low, in_seconds)} to {signed(high, in_seconds)}")
    return f"{signed(c.get('difference'), in_seconds)} [{interval}]"


# ---------- sections ----------

def scope_section(summary):
    label = summary.get("scope_label") or "Scope not stated"
    lines = [f"> **Scope: {md(label)}**"]
    if is_synthetic(summary):
        lines += [">", "> Every number in this report is invented to test the layout. "
                       "It is not evidence about any system."]
    return lines + [""]


def run_section(summary, arms):
    manifest = summary.get("manifest") or {}
    commit = manifest.get("git_commit")
    hashes = manifest.get("hashes") or {}
    hash_text = ", ".join(f"{md(k)} `{str(v)[:12]}`" for k, v in sorted(hashes.items())
                          if isinstance(v, str)) or "none recorded"
    shown = {"git_commit", "hashes", "model"}
    hidden = len([k for k in manifest if k not in shown])
    lines = [
        "## What this run is", "",
        f"- **Run:** `{md(summary.get('run', 'unknown'))}`",
        f"- **Stage:** {stage_label(summary)}",
        f"- **Condition:** `{md(summary.get('condition', 'unknown'))}`",
        f"- **Arms:** " + (", ".join(f"{arm_label(a.get('name', '?'))} (n = {a.get('n', '?')})" for a in arms)
                           or "none"),
        f"- **Model:** {md(manifest.get('model') or 'not recorded')}",
        f"- **Code:** commit `{md(str(commit)[:12])}`" if commit else "- **Code:** commit not recorded",
        f"- **Freeze hashes (first 12 characters):** {hash_text}",
    ]
    if hidden:
        lines.append(f"- {hidden} other manifest field(s) not shown in this report.")
    note = STAGE_NOTES.get(summary.get("stage"))
    if note is None and summary.get("split") == "dev" and summary.get("stage") is None:
        note = STAGE_NOTES["dev"]
    if note:
        lines += ["", note]
    return lines + [""]


STAGE_NOTES = {
    "practice": ("These are tuning cases (dev-01 to dev-20): the system was built and tuned on them, so they "
                 "are not exam evidence and may flatter it."),
    "pilot": ("These are pilot cases (dev-21 to dev-30): reserved for the pilot and not tuned on, but still "
              "practice scenarios, not exam evidence."),
    "dev": ("The development split holds tuning cases (dev-01 to dev-20), which the system was tuned on, and "
            "pilot cases (dev-21 to dev-30), which were reserved and not tuned on. Neither is exam evidence."),
}


def comparison_rows(comparisons):
    return [[c.get("family") or "—", c.get("label", "?"), c.get("endpoint", "?"),
             "unavailable" if c.get("n") is None else c.get("n"),
             "unavailable" if c.get("b") is None else c.get("b"),
             "unavailable" if c.get("c") is None else c.get("c"),
             difference_text(c), p_text(c.get("p")), p_text(c.get("p_adjusted")),
             c.get("method") or "not stated"] for c in comparisons]


COMPARISON_HEADER = ["Family", "Comparison", "Endpoint", "Pairs", "b", "c",
                     "Difference [95% CI]", "p", "p (adjusted)", "Method"]
PAIR_NOTE = ("b: pairs where the endpoint is present for the first-named arm and absent for the second; "
             "c: the reverse. For case success, b counts pairs only the first arm succeeded on. For false "
             "all-clear (lower is better), b counts pairs where only the first arm made the false claim, so a "
             "larger b is worse for the first arm. Difference is first minus second: percentage points for "
             "rates, seconds for user impact. Rows without b, c or an interval (such as the Wilcoxon test on "
             "user-impact seconds) show unavailable.")
INFERENTIAL = {"primary", "secondary"}


def comparisons_intro(comparisons):
    families = {c.get("family") for c in comparisons}
    lines = ["Arms are compared only on identical cases."]
    if families & INFERENTIAL:
        lines.append("The primary comparison is tested at alpha 0.05; secondary comparisons are Holm-adjusted "
                     "as one family.")
    if families - INFERENTIAL:
        lines.append("Rows marked descriptive (or with no family) are descriptive only: no test is claimed, "
                     "and a p-value shown as unavailable was not computed.")
    return " ".join(lines)


def headline_section(summary):
    comparisons = summary.get("comparisons") or []
    runbook = [c for c in comparisons if "runbook" in (c.get("label") or "").lower()]
    text = summary.get("runbook_comparison")
    lines = ["## Headline: the system against the scripted runbook", "",
             "The scripted runbook uses no AI. Where it ties or wins, that is reported here first.", ""]
    lines += [f"> {md(text)}" if text else "> No runbook comparison was supplied by the scorer.", ""]
    if runbook:
        lines += table(COMPARISON_HEADER, comparison_rows(runbook)) + ["", PAIR_NOTE]
    else:
        lines.append("No paired comparison against the runbook is in this summary.")
    return lines + [""]


def comparisons_section(summary):
    comparisons = summary.get("comparisons") or []
    order = {"primary": 0, "secondary": 1}
    comparisons = sorted(comparisons, key=lambda c: order.get(c.get("family"), 2))
    lines = ["## All paired comparisons", ""]
    if comparisons:
        lines += [comparisons_intro(comparisons), ""]
        lines += table(COMPARISON_HEADER, comparison_rows(comparisons)) + ["", PAIR_NOTE]
    else:
        lines.append("No paired comparisons are in this summary.")
    return lines + [""]


def charts_section(chart_paths, output_dir):
    names = ["Case success by arm with 95% Wilson intervals",
             "Mean user-impact seconds by arm with 95% bootstrap intervals",
             "Mean model tokens and cost per case by arm with 95% bootstrap intervals"]
    lines = ["## Charts", "",
             "Dot = estimate; line = 95% interval. The tables below hold every number in the charts. "
             "Do not read overlap, or a gap, between intervals as a test.", ""]
    for name, path in zip(names, chart_paths):
        rel = Path(path).relative_to(output_dir) if Path(path).is_relative_to(output_dir) else Path(path).name
        lines += [f"![{name}]({rel.as_posix()})", ""]
    return lines


def results_tables(arms, get_block, n_label):
    """Rates and means tables for a list of (arm, block) where block has rates/means."""
    blocks = [(arm, get_block(arm)) for arm in arms]
    blocks = [(arm, b) for arm, b in blocks if b is not None]
    lines = []
    rate_keys = metric_keys([b.get("rates") for _, b in blocks], RATE_METRICS)
    mean_keys = metric_keys([b.get("means") for _, b in blocks], MEAN_METRICS)
    if rate_keys:
        rows = []
        for key in rate_keys:
            label, denominator = RATE_METRICS.get(key, (key.replace("_", " "), "as defined by the scorer"))
            for arm, b in blocks:
                rate = (b.get("rates") or {}).get(key)
                rows.append([label, arm_label(arm.get("name", "?")),
                             (rate or {}).get("denominator") or denominator, *rate_cells(rate)])
        lines += ["**Rates** (n/N, estimate, 95% Wilson interval)", ""]
        lines += table(["Metric", "Arm", "N counts", "n/N", "Estimate", "Wilson 95%"], rows) + [""]
    if mean_keys:
        rows = []
        for key in mean_keys:
            label = MEAN_METRICS.get(key, (key.replace("_", " "),))[0]
            for arm, b in blocks:
                cells = mean_cells((b.get("means") or {}).get(key), mean_kind(key))
                if key == "time_to_mitigate_s":
                    censor = (b.get("rates") or {}).get("mitigation_censored")
                    counts, estimate, interval = rate_cells(censor)
                    cells[1] += f"; censored {counts} ({estimate}; Wilson 95% {interval})"
                rows.append([label, arm_label(arm.get("name", "?")),
                             *cells])
        lines += ["**Means** (mean per case, 95% bootstrap interval)", ""]
        lines += table(["Metric", "Arm", n_label, "Mean", "Bootstrap 95%"], rows) + [""]
    if not rate_keys and not mean_keys:
        lines += ["No metrics were supplied.", ""]
    return lines


def arms_section(arms):
    lines = ["## Results by arm (all valid cases)", ""]
    if not arms:
        return lines + ["No arms are in this summary.", ""]
    return lines + results_tables(arms, lambda a: a, "Cases with a value")


def strata_section(arms):
    keys = {k for a in arms for k in (a.get("strata") or {})}
    ordered = [k for k in STRATUM_ORDER if k in keys] + sorted(keys - set(STRATUM_ORDER))
    lines = ["## Results by stratum (descriptive)", "",
             "Strata are small, so their intervals are wide. They describe where each arm did well "
             "or badly; they are not tests.", ""]
    if not ordered:
        return lines + ["No strata are in this summary.", ""]
    for key in ordered:
        label = STRATUM_LABELS.get(key, key.replace("_", " ").capitalize())
        with_stratum = [a for a in arms if key in (a.get("strata") or {})]
        sizes = ", ".join(f"{arm_label(a.get('name', '?'))} n = {a['strata'][key].get('n', '?')}"
                          for a in with_stratum)
        lines += [f"### {md(label)}", "", f"Cases: {sizes}.", ""]
        lines += results_tables(with_stratum, lambda a, k=key: a["strata"][k], "Cases with a value")
    return lines


def exclusions_section(summary):
    exclusions = summary.get("exclusions") or []
    lines = ["## Exclusions", "",
             "Cases are excluded by a pre-registered, mechanical validity rule, applied without looking "
             "at any AI arm.", ""]
    if not exclusions:
        return lines + ["No exclusions are listed in this summary. That alone does not show every case was "
                        "valid: see Notes for any validity checks still pending.", ""]
    reasons = {}
    for e in exclusions:
        reasons.setdefault(e.get("case_id", "?"), []).append(e.get("reason") or "not stated")
    lines += [f"{len(reasons)} case(s) excluded. Every N above leaves them out.", ""]
    return lines + table(["Case", "Reason(s)"], [[case, "; ".join(r)] for case, r in reasons.items()]) + [""]


def retry_counts_as(initial):
    if initial in INFRASTRUCTURE_ERRORS:
        return "Infrastructure re-run: reported separately, not counted as a system failure"
    if initial == "harness_error":
        return "Retried once; the retry is scored, and a second harness error counts as a failure"
    return "As scored by the harness"


def retries_section(summary):
    retries = summary.get("retries") or []
    lines = ["## Retries", "",
             "Two kinds of retry are listed. A harness timeout (`harness_timeout`) or a model-provider error "
             "(`api_error`) is re-run once at the end and reported separately; it is never counted as a "
             "failure of the system. An ordinary harness error (`harness_error`) is also retried once, but if "
             "it errors again it counts as a failure. Listed cases are not excluded.", ""]
    if not retries:
        return lines + ["No cases were retried.", ""]
    rows = [[r.get("case_id", "?"), arm_label(r.get("arm", "?")), r.get("initial") or "unavailable",
             r.get("retry") or "unavailable", retry_counts_as(r.get("initial"))] for r in retries]
    return lines + table(["Case", "Arm", "First attempt", "Retry", "How it counts"], rows) + [""]


def notes_section(summary):
    notes = summary.get("notes") or []
    against = summary.get("against")
    lines = ["## Notes", ""]
    lines += [f"- {md(n)}" for n in notes] or ["- No notes were supplied."]
    if against is None:
        lines.append("- This is not a paired robustness run.")
    elif isinstance(against, dict):
        lines.append("- Paired robustness run (descriptive):")
        lines += [f"  - {md(k)}: {md(v)}" for k, v in against.items()]
    else:
        lines.append(f"- Paired with run `{md(against)}`. Each arm's drop is descriptive "
                     "(about ±20 points at n = 20).")
    return lines + [""]


def limits_section(summary):
    lines = ["## Limits and how to read this report", ""]
    if is_synthetic(summary):
        lines.append("- **This preview uses invented data.** No conclusion about any system can be drawn from it.")
    lines += [
        "- The cases run on test systems built for this project. The results say nothing about "
        "production readiness and make no regulatory claim.",
        "- Samples are small. An interval about ±20 points wide is normal at n = 20.",
        "- Arms are compared only by paired tests on identical cases. Whether two intervals overlap "
        "is not a test, and this report draws no conclusion from it.",
        "- Strata, robustness conditions and every metric other than the pre-registered comparisons "
        "are descriptive and are not adjusted for multiple looks.",
        "- \"unavailable\" means the value was not measured or not supplied; 0 means a measured zero. "
        "An arm with no model calls (the runbook) has a measured zero for tokens and cost.",
        "- Wilson and bootstrap intervals treat cases as independent draws.",
        "",
    ]
    return lines


def glossary_section(arms):
    lines = ["## Glossary", "", "**Arms**", ""]
    rows = [[arm_label(a.get("name", "?")), f"`{a.get('name', '?')}`",
             ARM_NOTES.get(a.get("name"), "Arm defined by the harness.")] for a in arms]
    lines += table(["Arm", "Key", "What it is"], rows) if rows else ["No arms."]
    lines += ["", "**Terms**", "",
              "- *Case success*: fixable case recovered by the checker with outcome `recovered` and no harmful "
              "action; must-escalate case escalated to the right component with no harmful action; healthy "
              "case left alone with outcome `no_incident` and the checker green.",
              "- *False all-clear*: the arm said `recovered` or `no_incident` but the checker was red.",
              "- *User-impact seconds*: 5-second buckets that missed the SLO between the first fault and "
              "the horizon, times 5.",
              "- *Wilson 95%*: an interval for a proportion that stays sensible at small n.",
              "- *Bootstrap 95%*: an interval for a mean from resampling cases.",
              "- *McNemar test*: a paired test that uses only the cases where the two arms disagree.", ""]
    return lines


def render_report(summary: dict, output_dir: Path) -> Path:
    """Write report.md and the three charts into output_dir; return the report path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_paths = draw_charts(summary, output_dir)
    arms = ordered_arms(summary)
    lines = [f"# Evaluation report: {md(summary.get('run', 'unknown run'))}", ""]
    lines += scope_section(summary)
    lines += run_section(summary, arms)
    lines += headline_section(summary)
    lines += comparisons_section(summary)
    lines += charts_section(chart_paths, output_dir)
    lines += arms_section(arms)
    lines += strata_section(arms)
    lines += exclusions_section(summary)
    lines += retries_section(summary)
    lines += notes_section(summary)
    lines += limits_section(summary)
    lines += glossary_section(arms)
    path = output_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path
