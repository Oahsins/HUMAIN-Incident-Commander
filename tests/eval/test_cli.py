"""CLI policy tests never load the real sealed or pilot scenarios."""

import json
import pytest

from eval import cli
from tests.eval.fakes import case


def write_lines(path, cases):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(c) for c in cases) + "\n", encoding="utf-8")


def test_model_selection_and_swap_override():
    settings = {"bulk": "p:bulk", "swap": "p:swap"}
    assert cli.resolve_model(settings, ["noop", "runbook"], "default", environment={}) is None
    assert cli.resolve_model(settings, ["abcde"], "default", "p:cli", {"IC_MODEL": "p:env"}) == "p:cli"
    assert cli.resolve_model(settings, ["abcde"], "default", environment={"IC_MODEL": "p:env"}) == "p:env"
    assert cli.resolve_model(settings, ["abcde"], "default", environment={}) == "p:bulk"
    assert cli.resolve_model(settings, ["abcde"], "model_swap", "p:cli", {"IC_MODEL": "p:env"}) == "p:swap"
    with pytest.raises(ValueError, match="different"):
        cli.resolve_model({"bulk": "same", "swap": "same"}, ["abcde"], "model_swap")
    with pytest.raises(ValueError, match="needs"):
        cli.resolve_model({"bulk": None}, ["abcde"], "default", environment={})


def test_dev_condition_and_selection_preserve_file_order(tmp_path):
    write_lines(tmp_path / "scenarios/dev/dev.jsonl", [case(2), case(1), case(3)])
    selected = cli.select_cases(tmp_path, split="dev", ids="fixture-1,fixture-2", condition="extra_service")
    assert [c["id"] for c in selected] == ["fixture-2", "fixture-1"]
    assert all(c["input"]["condition"] == "extra_service" for c in selected)
    assert len(cli.select_cases(tmp_path, split="dev", limit=1)) == 1


@pytest.mark.parametrize("condition", ["log_format_v2", "model_swap", "four_faults", "extra_service"])
def test_robust20_order_and_source_pairing(tmp_path, condition):
    folder = tmp_path / "scenarios/heldout"
    cases = [case(1), case(2), case(3)]
    write_lines(folder / "heldout.jsonl", cases)
    (folder / "SEALED.json").write_text(json.dumps({"robust20": ["fixture-3", "fixture-1"]}))
    variants = []
    for original in cases:
        for cond, suffix in (("four_faults", "-ff"), ("extra_service", "-xs")):
            variant = case(original["input"]["seed"], condition=cond)
            variant.update(source_id=original["id"], id=original["id"] + suffix)
            variants.append(variant)
    write_lines(folder / "robustness.jsonl", variants)
    selected = cli.select_cases(tmp_path, split="heldout", condition=condition)
    assert [c.get("source_id", c["id"]) for c in selected] == ["fixture-3", "fixture-1"]
    assert all(c["input"]["condition"] == condition for c in selected)


def test_transfer_path(tmp_path):
    write_lines(tmp_path / "scenarios/transfer/dispatch.jsonl", [case(1)])
    assert cli.select_cases(tmp_path, split="transfer")[0]["id"] == "fixture-1"


def test_missing_ai_stops_before_run(tmp_path, monkeypatch, capsys):
    write_lines(tmp_path / "scenarios/dev/dev.jsonl", [case(1)])
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/models.json").write_text('{"bulk":"mock:fixture"}')
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    def missing(name):
        raise ValueError("AI arms are not installed; merge the agent pull request first")
    monkeypatch.setattr(cli, "load_arm", missing)
    assert cli.main(["--name", "fixture", "--arms", "abcde"]) == 2
    assert "not installed" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()
