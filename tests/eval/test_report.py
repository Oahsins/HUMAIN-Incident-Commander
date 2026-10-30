"""Reports use invented retained records, including missing and paired evidence."""

from copy import deepcopy
import csv
import struct

from eval.report import build_summary, update_run_index, write_report
from eval.storage import write_json


def fixture_run(folder, *, condition="default", reference_ids=False, controls=True):
    names = ["abcde", "runbook"] + (["noop", "oracle"] if controls else [])
    ids = []
    for index in range(4):
        source_id = f"fixture-{index}"
        case_id = source_id + ("-ff" if reference_ids else "")
        ids.append(case_id)
        healthy = index == 3
        roots = [] if healthy else [{"target": "fixture-service", "class": "process_down",
                                     "fix": {"action": "restart", "target": "fixture-service", "params": {}}}]
        case = {"id": case_id, "source_id": source_id,
                "input": {"system": "fixture", "seed": index, "condition": condition,
                          "faults": [] if healthy else [{"type": "crash"}]},
                "target": {"healthy": healthy, "must_escalate": False, "root_causes": roots}}
        for arm in names:
            green = healthy or arm == "oracle" or (arm == "abcde" and index != 1) or (arm == "runbook" and index != 0)
            outcome = "no_incident" if healthy or arm == "noop" else "recovered" if green else "escalated"
            record = {
                "case": case, "arm": arm, "attempt": 1, "purpose": "main", "error": None,
                "injection_complete": True, "manifest": deepcopy(roots),
                "result": {"outcome": outcome, "root_causes": deepcopy(roots), "calls": [],
                           "sbar": {"assessment": "Synthetic fixture."}},
                "checker": {"recovered": green, "integrity": {"ok": True, "for_operations": []},
                            "impact": {"breach_seconds": 0 if healthy else 10 + 5 * index}},
                "actions": [], "audit": [], "timing": {"t0": 100, "horizon": 210},
            }
            write_json(folder / "cases" / case_id / arm / "record.json", record)
    write_json(folder / "manifest.json", {
        "name": folder.name, "synthetic": True, "created_t": 100, "git_commit": "fixture-commit",
        "hashes": {"agent": "synthetic"},
        "configuration": {"split": "dev", "arms": names, "case_ids": ids},
    })
    return folder


def test_report_writes_markdown_three_real_pngs_and_index(tmp_path):
    folder = fixture_run(tmp_path / "results" / "fixture-report")
    report = write_report(folder)
    text = report.read_text(encoding="utf-8")
    assert "Synthetic fixture" in text
    assert "|" in text and "Wilson" in text
    assert "runbook wins" in text.lower()
    assert "3/4" in text
    for name in ("case_success.png", "user_impact.png", "tokens_cost.png"):
        data = (folder / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert all(size > 100 for size in struct.unpack(">II", data[16:24]))
    assert (folder / "metrics.json").exists()
    assert (folder / "summary.json").exists()
    assert (folder.parent / "runs.csv").exists()


def test_index_resume_preserves_other_runs_and_does_not_duplicate(tmp_path):
    first = fixture_run(tmp_path / "results" / "first")
    second = fixture_run(tmp_path / "results" / "second")
    update_run_index(first)
    update_run_index(second)
    update_run_index(first)
    with (first.parent / "runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 8
    assert {r["run"] for r in rows} == {"first", "second"}
    assert all("recovered_wilson_low" in r for r in rows)


def test_source_id_pairing_and_robustness_are_descriptive(tmp_path):
    main = fixture_run(tmp_path / "main")
    changed = fixture_run(tmp_path / "changed", condition="four_faults", reference_ids=True)
    summary = build_summary(changed, against=main)
    paired = [c for c in summary["comparisons"] if "condition vs main" in c["label"]]
    assert len(paired) == 4
    assert all(c["n"] == 4 and c["difference"] == 0 for c in paired)
    assert all(c["family"] == "descriptive" and c["p"] is None for c in summary["comparisons"])


def test_log_condition_inherits_controls_but_keeps_injection_gap(tmp_path):
    from eval.storage import read_json
    main = fixture_run(tmp_path / "main")
    changed = fixture_run(tmp_path / "changed", condition="log_format_v2", controls=False)
    summary = build_summary(changed, against=main)
    assert all(a["n"] == 4 for a in summary["arms"])
    for arm in ("abcde", "runbook"):
        path = changed / "cases" / "fixture-0" / arm / "record.json"
        record = read_json(path)
        record["injection_complete"] = False
        record["manifest"] = []
        write_json(path, record)
    summary = build_summary(changed, against=main)
    assert summary["measurements"]["validity"]["fixture-0"]["valid"] is None


def test_partial_run_indexes_without_completed_records(tmp_path):
    folder = tmp_path / "partial"
    write_json(folder / "manifest.json", {"name": "partial", "created_t": 100,
        "configuration": {"split": "dev", "arms": ["runbook"], "case_ids": ["fixture-0"]}})
    assert build_summary(folder)["arms"] == []
    assert update_run_index(folder).exists()
