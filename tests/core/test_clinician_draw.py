"""The clinician-check draw applies the rule declared before the final run (DECISIONS.md, 30 Oct)."""

from copy import deepcopy
import csv
import random

import pytest

from eval.report import build_summary
from eval.storage import read_json, write_json
from scripts import clinician_draw

# (kind, abcde succeeds, special) for each invented case, h-01 onwards.
PLAN = ([("healthy", True, None)] * 3
        + [("must_escalate", True, None), ("must_escalate", False, None)]
        + [("blind", True, None), ("blind", True, None), ("blind", False, None)]
        + [("named", True, None)] * 4 + [("named", False, None)] * 4
        + [("practice", True, None), ("practice", False, None)]
        + [("named", False, "invalid"), ("named", False, "infra")])


def invented_case(index, kind):
    healthy, must = kind == "healthy", kind == "must_escalate"
    faults = {"healthy": [], "must_escalate": [{"type": "network_outage"}], "practice": [{"type": "crash"}],
              "named": [{"type": "poison_payment"}], "blind": [{"type": "poison_payment"}, {"type": "sealed_1"}]}[kind]
    roots = [] if healthy else [{"target": "service-x", "class": "external_outage" if must else "process_down",
                                 "fix": {"action": "escalate" if must else "restart", "target": "service-x"}}]
    return {"id": f"h-{index:02}", "source_id": f"h-{index:02}",
            "input": {"system": "invented", "seed": index, "condition": "default", "faults": faults},
            "target": {"healthy": healthy, "must_escalate": must, "blind": kind == "blind",
                       "root_causes": roots, "acceptable_secondary": []}}


def record(case, arm, *, success=True, green=None, outcome=None):
    target = case["target"]
    if outcome is None:
        if arm in ("noop", "oracle"):
            outcome = "no_incident" if arm == "noop" else "recovered"
        elif target["must_escalate"]:
            outcome = "escalated" if success else "recovered"
        else:
            outcome = ("no_incident" if target["healthy"] else "recovered") if success else "escalated"
    if green is None:
        green = target["healthy"] or arm == "oracle" or (arm == "abcde" and success and not target["must_escalate"])
    escalation = {"components": ["service-x"], "class": None, "reason": "the outside link drops calls",
                  "urgency": "now", "to": "network operator", "ask": "check the link"} if outcome == "escalated" else None
    return {"case": case, "arm": arm, "attempt": 1, "purpose": "main", "error": None,
            "injection_complete": True, "manifest": deepcopy(target["root_causes"]),
            "result": {"outcome": outcome, "root_causes": deepcopy(target["root_causes"]), "actions": [],
                       "escalation": escalation, "calls": [],
                       "sbar": {"situation": "invented situation", "background": "", "assessment": "",
                                "recommendation": ""},
                       "trace": [{"t": 1.5, "phase": "survey", "kind": "tool", "name": "observe",
                                  "summary": "every component read"}]},
            "checker": {"recovered": green, "reasons": [] if green else ["3 of 40 customer journeys failed"],
                        "integrity": {"ok": True, "for_operations": [], "harmful_quarantines": 0},
                        "impact": {"breach_seconds": 10}},
            "actions": [], "audit": [], "timing": {"t0": 100, "horizon": 210}}


def fixture_run(folder, plan=PLAN):
    """Invented retained records, then the two report files as write_report saves them."""
    ids = []
    for index, (kind, success, special) in enumerate(plan, 1):
        case = invented_case(index, kind)
        ids.append(case["id"])
        write_json(folder / "cases" / case["id"] / "abcde" / "record.json",
                   record(case, "abcde", success=success, outcome="harness_timeout" if special == "infra" else None))
        write_json(folder / "cases" / case["id"] / "noop" / "record.json",
                   record(case, "noop", green=True if special == "invalid" else None))
        write_json(folder / "cases" / case["id"] / "oracle" / "record.json", record(case, "oracle"))
    write_json(folder / "manifest.json", {"name": folder.name, "synthetic": True,
                                          "configuration": {"split": "heldout", "arms": ["abcde", "noop", "oracle"],
                                                            "case_ids": ids}})
    summary = build_summary(folder)
    write_json(folder / "metrics.json", summary.pop("measurements"))
    write_json(folder / "summary.json", summary)
    return folder


def sheet(folder):
    with (folder / "clinician-review.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_the_first_group_that_applies_wins():
    assert clinician_draw.group_of({"strata": ["named_heldout", "blind", "double"]}) == "blind"
    assert clinician_draw.group_of({"strata": ["practice_only", "single"]}) == "practice_only"
    assert clinician_draw.group_of({"strata": ["single"]}) is None


def test_the_declared_draw_on_a_held_out_report(tmp_path, capsys):
    folder = fixture_run(tmp_path / "results" / "final-1")
    assert clinician_draw.main(["--run", str(folder)]) == 0
    rows = sheet(folder)
    assert len(rows) == 12 and len({row["case_id"] for row in rows}) == 12
    assert {"h-19", "h-20"}.isdisjoint(row["case_id"] for row in rows)   # invalid, infrastructure error
    by_group = {}
    for row in rows:
        by_group.setdefault(row["group"], []).append(row)
    pairs = {group: sorted(row["case_success"] for row in members if row["drawn_as"] == "pair")
             for group, members in by_group.items()}
    assert pairs == {"healthy": ["true", "true"], "must_escalate": ["false", "true"], "blind": ["false", "true"],
                     "named_heldout": ["false", "true"], "practice_only": ["false", "true"]}
    fills = [row for row in rows if row["drawn_as"] == "fill"]
    assert len(fills) == 2 and all(row["case_success"] == "false" for row in fills)
    for row in rows:
        assert (row["escalation_urgency_right"] == "n/a") == (row["outcome"] != "escalated")
        assert row["agrees_with_score"] == row["would_accept_handover"] == row["notes"] == ""
        assert row["evidence"].endswith(f"cases/{row['case_id']}/abcde")
    out = capsys.readouterr().out
    assert "18 cases eligible; 1 left out: infrastructure error; 1 left out: not kept by the validity rule" in out
    assert "rehearsal" not in out
    # The order of the random calls is part of the rule, so the ids are pinned.
    assert [row["case_id"] for row in rows] == PINNED


PINNED = ["h-01", "h-03", "h-04", "h-05", "h-06", "h-08", "h-11", "h-13", "h-14", "h-15", "h-17", "h-18"]


def test_the_draw_ignores_row_order_and_repeats_exactly(tmp_path):
    report = read_json(fixture_run(tmp_path / "results" / "final-1") / "metrics.json")
    rows, _ = clinician_draw.eligible(report)
    first = [row["case_id"] for row, _ in clinician_draw.draw(rows)]
    shuffled = rows[:]
    random.Random(1).shuffle(shuffled)
    assert [row["case_id"] for row, _ in clinician_draw.draw(shuffled)] == first
    assert [row["case_id"] for row, _ in clinician_draw.draw(rows)] == first


def test_short_groups_and_the_fill_order():
    def row(case_id, strata, success):
        return {"case_id": case_id, "strata": strata, "case_success": success}
    rows = ([row("a1", ["healthy"], True)]                                  # one case: all it has
            + [row(f"b{i}", ["blind"], False) for i in range(3)]           # one kind: two of it
            + [row(f"p{i}", ["practice_only"], True) for i in range(4)]
            + [row("x1", ["single"], False)])                              # in no group: fill only
    picked = clinician_draw.draw(rows, size=8)
    drawn = {item["case_id"]: kind for item, kind in picked}
    assert len(picked) == 8 and drawn["a1"] == "pair" and drawn["x1"] == "fill"
    assert sum(case_id.startswith("b") for case_id in drawn) == 3          # 2 as the pair, the third as a failure fill
    fills = [item for item, kind in picked if kind == "fill"]
    assert [item["case_success"] for item in fills] == [False, False, True]
    assert len(clinician_draw.draw(rows, size=20)) == len(rows)            # never more than there are


def test_the_sheet_is_written_once(tmp_path, capsys):
    folder = fixture_run(tmp_path / "results" / "final-1")
    clinician_draw.main(["--run", str(folder)])
    path = folder / "clinician-review.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",,,", ",yes,,", 1), encoding="utf-8")
    typed = path.read_text(encoding="utf-8")
    capsys.readouterr()
    clinician_draw.main(["--run", str(folder)])
    assert path.read_text(encoding="utf-8") == typed
    assert "already exists and was left as it is" in capsys.readouterr().out


def test_only_the_held_out_default_run_is_the_declared_draw(tmp_path, capsys):
    folder = fixture_run(tmp_path / "results" / "practice")
    summary = read_json(folder / "summary.json")
    write_json(folder / "summary.json", {**summary, "split": "dev"})
    with pytest.raises(SystemExit):
        clinician_draw.main(["--run", str(folder)])
    assert not (folder / "clinician-review.csv").exists()
    with pytest.raises(SystemExit):
        clinician_draw.main(["--run", str(folder), "--arm", "runbook"])
    clinician_draw.main(["--run", str(folder), "--practice"])
    assert "rehearsal, not the declared draw" in capsys.readouterr().out


def test_show_lays_one_case_out_for_reading(tmp_path, capsys):
    folder = fixture_run(tmp_path / "results" / "final-1")
    clinician_draw.main(["--run", str(folder), "--show", "h-04"])
    out = capsys.readouterr().out
    assert out.startswith("h-04 (abcde): outcome escalated; scored success true")
    for text in ("Group: must_escalate", "Labelled faults, must escalate:", "service-x external_outage, fix escalate",
                 "Escalation: now to network operator about service-x. Ask: check the link.",
                 "Situation: invented situation", "Checker at the horizon: recovered false",
                 "3 of 40 customer journeys failed", "survey/tool observe: every component read"):
        assert text in out
