"""Reports use invented retained records, including missing and paired evidence."""

from copy import deepcopy
import csv
import struct

from eval.report import build_summary, update_run_index, write_report
from eval.storage import read_json, write_json


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


def test_dev_without_controls_has_full_tables_and_explicit_limit(tmp_path):
    folder = fixture_run(tmp_path / "results" / "practice", controls=False)
    summary = build_summary(folder)
    assert all(arm["n"] == 4 for arm in summary["arms"])
    assert "not validated: no controls in this run" in summary["notes"]
    # Control omission does not excuse a known injection failure.
    path = folder / "cases" / "fixture-0" / "abcde" / "record.json"
    row = read_json(path)
    row["error"] = {"stage": "inject", "type": "RuntimeError"}
    write_json(path, row)
    summary = build_summary(folder)
    assert all(arm["n"] == 3 for arm in summary["arms"])
    assert summary["exclusions"] == [{"case_id": "fixture-0", "reason": "fault injection raised"}]


def test_heldout_without_controls_never_uses_dev_exemption(tmp_path):
    folder = fixture_run(tmp_path / "results" / "exam", controls=False)
    manifest = read_json(folder / "manifest.json")
    manifest["configuration"]["split"] = "heldout"
    write_json(folder / "manifest.json", manifest)
    summary = build_summary(folder)
    assert all(arm["n"] == 0 for arm in summary["arms"])
    assert "not validated: no controls in this run" not in summary["notes"]


def test_mitigation_and_censor_rate_reach_presentation_schema(tmp_path):
    folder = fixture_run(tmp_path / "results" / "mitigation", controls=False)
    for index in range(4):
        path = folder / "cases" / f"fixture-{index}" / "abcde" / "record.json"
        row = read_json(path)
        row["checker"]["impact"].update(time_to_mitigate_s=index * 10, mitigation_censored=index == 3)
        write_json(path, row)
    arm = next(arm for arm in build_summary(folder)["arms"] if arm["name"] == "abcde")
    assert arm["means"]["time_to_mitigate_s"]["mean"] == 15
    censor = arm["rates"]["mitigation_censored"]
    assert (censor["n"], censor["N"], censor["missing"]) == (1, 4, 0)
    assert censor["estimate"] == 0.25


def test_robustness_pairs_keep_changed_seeds_and_report_them(tmp_path):
    main = fixture_run(tmp_path / "results" / "main")
    changed = fixture_run(tmp_path / "results" / "changed", condition="four_faults", reference_ids=True)
    for path in (changed / "cases").glob("*/*/record.json"):
        row = read_json(path)
        row["case"]["input"]["seed"] += 100
        write_json(path, row)
    summary = build_summary(changed, against=main)
    pairs = [item for item in summary["comparisons"] if "condition vs main" in item["label"]]
    assert all(item["n"] == 4 and len(item["seed_differences"]) == 4 for item in pairs)
    assert any("seeds differ" in note and "condition 100, main 0" in note for note in summary["notes"])
    # A different target system still cannot be paired.
    for path in (changed / "cases").glob("*/*/record.json"):
        row = read_json(path)
        row["case"]["input"]["system"] = "another-system"
        write_json(path, row)
    summary = build_summary(changed, against=main)
    assert all(item["n"] == 0 for item in summary["comparisons"] if "condition vs main" in item["label"])


def test_log_validity_inherits_main_even_when_seeds_differ(tmp_path):
    main = fixture_run(tmp_path / "results" / "main")
    changed = fixture_run(tmp_path / "results" / "changed", condition="log_format_v2", controls=False)
    manifest = read_json(changed / "manifest.json")
    manifest["configuration"]["split"] = "heldout"
    write_json(changed / "manifest.json", manifest)
    for path in (changed / "cases").glob("*/*/record.json"):
        row = read_json(path)
        row["case"]["input"]["seed"] += 10
        write_json(path, row)
    summary = build_summary(changed, against=main)
    assert all(arm["n"] == 4 for arm in summary["arms"])
    assert all(value["inherited_from"].startswith("fixture-") for value in summary["measurements"]["validity"].values())


def test_full_heldout_compares_label_counts_with_public_composition(tmp_path):
    from tests.eval.test_metrics import record
    folder = tmp_path / "results" / "full"
    case_ids = [f"invented-{index}" for index in range(60)]
    for case_id in case_ids:
        write_json(folder / "cases" / case_id / "abcde" / "record.json", record(case_id=case_id))
    manifest = {"name": "full", "synthetic": True,
                "configuration": {"split": "heldout", "arms": ["abcde"], "case_ids": case_ids}}
    write_json(folder / "manifest.json", manifest)
    # No sealed scenario file exists: these are invented retained records.
    # A mistaken public total must not hide the composition discrepancy.
    write_json(tmp_path / "scenarios" / "heldout" / "SEALED.json", {
        "composition": {"total": 59, "singles": 60, "doubles": 0, "triples": 0,
                        "healthy": 1, "must_escalate": 0, "named_heldout": 0, "blind": 0, "practice_only": 60,
                        "unrecognised_stratum": 7}})
    summary = build_summary(folder)
    differences = [note for note in summary["notes"] if "composition difference" in note]
    assert differences == ["SEALED.json composition difference — healthy: labels 0, seal 1.",
                           "SEALED.json composition difference — total: labels 60, seal 59."]
    assert "SEALED.json composition key 'unrecognised_stratum' not compared: unrecognised count." in summary["notes"]
    assert "composition difference" in write_report(folder).read_text(encoding="utf-8")
    # A partial selected exam does not claim a full composition comparison.
    manifest["configuration"]["case_ids"] = manifest["configuration"]["case_ids"][:3]
    write_json(folder / "manifest.json", manifest)
    assert not any("composition difference" in note for note in build_summary(folder)["notes"])


def test_oracle_validation_retry_is_reported_separately_from_arm_retry(tmp_path):
    folder = fixture_run(tmp_path / "results" / "validation-retry")
    directory = folder / "cases" / "fixture-0" / "oracle"
    main = read_json(directory / "record.json")
    main["checker"]["recovered"] = False
    main["result"]["outcome"] = "gave_up"
    write_json(directory / "record.json", main)
    validation = deepcopy(main)
    validation.update(purpose="oracle_recheck", attempt=3,
                      error={"stage": "arm", "type": "CallError", "kind": "refused"})
    validation["result"]["outcome"] = "harness_error"
    write_json(directory / "oracle-validation" / "record.json", validation)
    summary = build_summary(folder)
    assert summary["measurements"]["validity"]["fixture-0"]["valid"] is None
    assert summary["retries"] == []
    assert any("Oracle validation retry" in note and "retry not completed" in note for note in summary["notes"])
    retry = deepcopy(main)
    retry.update(purpose="oracle_recheck_retry", attempt=4)
    retry["checker"]["recovered"] = True
    retry["result"]["outcome"] = "recovered"
    write_json(directory / "oracle-validation" / "retry" / "record.json", retry)
    summary = build_summary(folder)
    assert summary["measurements"]["validity"]["fixture-0"]["valid"] is True
    assert summary["retries"] == []
    assert any("Oracle validation retry" in note and "retry recovered" in note for note in summary["notes"])
    scored = [row for row in summary["measurements"]["cases"] if row["case_id"] == "fixture-0" and row["arm"] == "oracle"]
    assert len(scored) == 1 and scored[0]["outcome"] == "gave_up"
