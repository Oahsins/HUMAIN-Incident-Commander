"""Draw the 12 cases for the clinician check declared before the final run.

DECISIONS.md (30 Oct, "Two exploratory analyses declared before the final run")
and CONTRACT section 16 item 8 fix the rule: `abcde` on run `final-1`, split
heldout, condition default, valid cases only, infrastructure errors left out.
This script applies it to the report that `python run.py eval --report final-1`
writes, so anyone who runs it on that report gets the same 12 ids. It changes
no score and touches no frozen file.

    python scripts/clinician_draw.py                  # print the draw, write the answer sheet
    python scripts/clinician_draw.py --show h-07      # one case, laid out for reading

The answer sheet is results/final-1/clinician-review.csv. It is written once and
never overwritten, so answers already typed into it are safe.
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval import metrics
from eval.storage import pair_dir, read_json

ARM = "abcde"
GROUPS = ("healthy", "must_escalate", "blind", "named_heldout", "practice_only")
SEED = 20261030
SIZE = 12
SHEET = "clinician-review.csv"
ANSWERS = ("agrees_with_score", "would_accept_handover", "escalation_urgency_right",
           "escalation_recipient_right", "notes")
FIELDS = ("case_id", "group", "drawn_as", "outcome", "case_success", "checker_recovered",
          "handover_complete", "evidence") + ANSWERS


def group_of(row):
    """The first registered group that applies to a case, or None."""
    return next((name for name in GROUPS if name in row["strata"]), None)


def eligible(report, arm=ARM):
    """The scored rows the rule may draw from, and why the others were left out."""
    validity = report["validity"]
    kept, left_out = [], Counter()
    for row in report["cases"]:
        if row["arm"] != arm:
            continue
        if row["infrastructure_error"]:
            left_out["infrastructure error"] += 1
        elif (validity.get(row["case_id"]) or {}).get("valid") is not True:
            left_out["not kept by the validity rule"] += 1
        elif not isinstance(row["case_success"], bool):
            left_out["case success unknown"] += 1
        else:
            kept.append(row)
    return kept, left_out


def draw(rows, seed=SEED, size=SIZE):
    """Apply the declared rule; return [(row, "pair" | "fill")] in draw order.

    The order of the random calls is part of the rule. Rows are sorted by case
    id. For each group in GROUPS order: rng.choice of its successes, then of its
    failures; rng.sample of two when it has only one kind; all of it when it has
    fewer than two cases. Then rng.sample of the remaining failures, then of the
    remaining successes, until there are `size`.
    """
    rng = random.Random(seed)
    pool = sorted(rows, key=lambda row: row["case_id"])
    picked = []
    for group in GROUPS:
        members = [row for row in pool if group_of(row) == group]
        wins = [row for row in members if row["case_success"]]
        losses = [row for row in members if not row["case_success"]]
        if len(members) < 2:
            chosen = members
        elif wins and losses:
            chosen = [rng.choice(wins), rng.choice(losses)]
        else:
            chosen = rng.sample(members, 2)
        picked += [(row, "pair") for row in chosen]
    for success in (False, True):
        taken = {row["case_id"] for row, _ in picked}
        rest = [row for row in pool if row["case_id"] not in taken and row["case_success"] is success]
        picked += [(row, "fill") for row in rng.sample(rest, min(max(size - len(picked), 0), len(rest)))]
    return picked


def load_report(run_dir):
    """metrics.json and summary.json as the report wrote them, and the hash of metrics.json."""
    path = Path(run_dir) / "metrics.json"
    if not path.exists():
        raise SystemExit(f"{path} does not exist: run `python run.py eval --report {Path(run_dir).name}` first")
    data = path.read_bytes()
    summary = read_json(Path(run_dir) / "summary.json") or {}
    return json.loads(data), summary, hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def scored_record(run_dir, case_id, arm=ARM):
    """The record the report scored for this case: the original, or its one retry."""
    folder = pair_dir(run_dir, case_id, arm)
    records = [read_json(folder / "record.json"), read_json(folder / "retry" / "record.json")]
    selected = metrics.select_records([record for record in records if record is not None])
    return selected[0] if selected else None


def _text(value):
    return "" if value is None else str(value).lower() if isinstance(value, bool) else str(value)


def sheet_rows(run_dir, picked, arm=ARM):
    """One answer row per drawn case, in case id order; escalation questions only where one was written."""
    rows = []
    for row, drawn_as in sorted(picked, key=lambda item: item[0]["case_id"]):
        record = scored_record(run_dir, row["case_id"], arm) or {}
        escalated = bool((record.get("result") or {}).get("escalation"))
        rows.append({
            "case_id": row["case_id"], "group": group_of(row) or "none", "drawn_as": drawn_as,
            "outcome": row["outcome"], "case_success": _text(row["case_success"]),
            "checker_recovered": _text(row["checker_recovered"]),
            "handover_complete": _text(row["handover_complete"]),
            "evidence": pair_dir(run_dir, row["case_id"], arm).as_posix(),
            **{name: "" for name in ANSWERS},
            **({} if escalated else {"escalation_urgency_right": "n/a", "escalation_recipient_right": "n/a"}),
        })
    return rows


def write_sheet(path, rows):
    """Write the answer sheet only if it does not exist yet; return whether it was written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("x", encoding="utf-8", newline="")
    except FileExistsError:
        return False
    with handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return True


def show(run_dir, case_id, arm=ARM):
    """One case as the reviewer reads it: labels, claims, actions, handover, trace and verdict."""
    record = scored_record(run_dir, case_id, arm)
    if record is None:
        raise SystemExit(f"no record for {case_id} ({arm}) in {run_dir}")
    case, result = record["case"], record.get("result") or {}
    target, checker = case.get("target") or {}, record.get("checker") or {}
    integrity, row = checker.get("integrity") or {}, metrics.score_record(record)
    lines = [f"{case_id} ({arm}): outcome {row['outcome']}; scored success {_text(row['case_success'])}; "
             f"checker recovered {_text(row['checker_recovered'])}; handover complete {_text(row['handover_complete'])}",
             f"Group: {group_of(row) or 'none'} (strata: {', '.join(row['strata'])})", "",
             "Labelled faults" + (": none, a healthy case" if target.get("healthy") else
                                  ", must escalate:" if target.get("must_escalate") else ":")]
    lines += [f"  {item.get('target')} {item.get('class')}, fix {(item.get('fix') or {}).get('action')}"
              for item in target.get("root_causes") or []]
    lines.append("Root causes the agent named:")
    lines += [f"  {item.get('target')} {item.get('class')} (confidence {item.get('confidence')}): {item.get('evidence') or ''}"
              for item in result.get("root_causes") or []] or ["  none"]
    lines.append("Actions it tried:")
    lines += [f"  {action.get('action')} {action.get('target')}: "
              + (f"refused ({action.get('refused_reason')})" if action.get("refused") else
                 "done" if action.get("ok") else "sent, failed" if action.get("sent") else "not sent")
              + (f". Why: {action['reason']}" if action.get("reason") else "")
              for action in result.get("actions") or []] or ["  none"]
    escalation = result.get("escalation")
    lines.append("Escalation: " + ("none" if not escalation else
                 f"{escalation.get('urgency')} to {escalation.get('to')} about {', '.join(escalation.get('components') or [])}. "
                 f"Ask: {escalation.get('ask')}. Reason: {escalation.get('reason')}"))
    lines.append("Handover (SBAR):")
    lines += [f"  {key.capitalize()}: {value}" for key, value in (result.get("sbar") or {}).items()]
    lines.append(f"Checker at the horizon: recovered {_text(checker.get('recovered'))}")
    lines += [f"  {reason}" for reason in checker.get("reasons") or []]
    lines += [f"  for operations: {item}" for item in integrity.get("for_operations") or []]
    if integrity.get("harmful_quarantines"):
        lines.append(f"  items set aside that were not poison: {integrity['harmful_quarantines']}")
    lines.append("Trace:")
    lines += [f"  {entry.get('t') or 0:6.1f} s {entry.get('phase')}/{entry.get('kind')} {entry.get('name') or ''}: "
              f"{entry.get('summary') or ''}" for entry in result.get("trace") or []] or ["  none"]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Draw the 12 cases for the clinician check declared before the final run.")
    parser.add_argument("--run", default="results/final-1", help="the report folder (default results/final-1)")
    parser.add_argument("--show", metavar="CASE_ID", help="print one case laid out for reading, then stop")
    parser.add_argument("--practice", action="store_true",
                        help="rehearse on another run: any split or condition, never the declared draw")
    parser.add_argument("--arm", default=ARM, help="with --practice only: the arm to draw from")
    args = parser.parse_args(argv)
    run_dir = Path(args.run)
    if args.arm != ARM and not args.practice:
        parser.error("the declared draw uses abcde; --arm is for rehearsals with --practice")
    if args.show:
        print(show(run_dir, args.show, args.arm))
        return 0
    report, summary, digest = load_report(run_dir)
    split, condition = summary.get("split"), summary.get("condition")
    declared = split == "heldout" and condition == "default" and args.arm == ARM
    if not declared and not args.practice:
        raise SystemExit(f"{run_dir} is split {split}, condition {condition}: the declared draw is from the "
                         "held-out run under the default condition (add --practice to rehearse)")
    rows, left_out = eligible(report, args.arm)
    picked = draw(rows)
    print(f"Clinician check draw: run {summary.get('run', run_dir.name)}, split {split}, condition {condition}, "
          f"arm {args.arm}, seed {SEED}" + ("" if declared else " (rehearsal, not the declared draw)"))
    print(f"metrics.json sha256 {digest}")
    print(f"{len(rows)} cases eligible" + "".join(f"; {count} left out: {reason}" for reason, count in sorted(left_out.items())))
    for group in GROUPS:
        members = [row for row in rows if group_of(row) == group]
        wins = sum(row["case_success"] for row in members)
        print(f"  {group}: {len(members)} cases, {wins} succeeded, {len(members) - wins} failed")
    if len(picked) < SIZE:
        print(f"Only {len(picked)} cases could be drawn.")
    for row, drawn_as in picked:
        print(f"  {row['case_id']}  {group_of(row) or 'none':<13}  {drawn_as:<4}  success {_text(row['case_success'])}")
    path = run_dir / SHEET
    if write_sheet(path, sheet_rows(run_dir, picked, args.arm)):
        print(f"Wrote {path.as_posix()}: fill in the last five columns.")
    else:
        print(f"{path.as_posix()} already exists and was left as it is.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
