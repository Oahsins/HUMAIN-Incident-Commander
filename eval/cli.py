"""Command-line selection, model policy and final-run checks for experiments."""

import argparse
import copy
import json
import os
from pathlib import Path
import sys

from ic.contract import CONDITIONS
from .arms import AI_ARMS, ARMS, load_arm
from .runner import run_cases
from .seals import current_hashes, git, verify_freeze, verify_seals
from .storage import safe_name

ROOT = Path(__file__).resolve().parents[1]


def parser():
    command = argparse.ArgumentParser(prog="python run.py eval", description=__doc__)
    command.add_argument("--split", choices=("dev", "heldout", "transfer"), default="dev")
    command.add_argument("--arms", default="abcde,runbook")
    command.add_argument("--name")
    selection = command.add_mutually_exclusive_group()
    selection.add_argument("--ids")
    selection.add_argument("--limit", type=int)
    command.add_argument("--copies", type=int, default=3)
    command.add_argument("--port-bases")
    command.add_argument("--condition", choices=CONDITIONS)
    command.add_argument("--model")
    command.add_argument("--final", action="store_true")
    command.add_argument("--report")
    command.add_argument("--against")
    return command


def _json_lines(path):
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def select_cases(root, *, split, condition=None, ids=None, limit=None):
    """Selection preserves file order, or the pre-registered robust20 order."""
    root = Path(root)
    folder = root / "scenarios" / split
    filename = {"dev": "dev.jsonl", "heldout": "heldout.jsonl", "transfer": "dispatch.jsonl"}[split]
    robust = split == "heldout" and condition not in {None, "default"}
    if robust and condition in {"four_faults", "extra_service"}:
        filename = "robustness.jsonl"
    cases = _json_lines(folder / filename)
    if robust:
        metadata = json.loads((folder / "SEALED.json").read_text(encoding="utf-8"))
        order = metadata["robust20"]
        if len(set(order)) != len(order):
            raise ValueError("robust20 contains duplicate ids")
        if condition in {"four_faults", "extra_service"}:
            candidates = [c for c in cases if c["input"].get("condition") == condition]
            mapping = {c["source_id"]: c for c in candidates}
            if len(mapping) != len(candidates):
                raise ValueError("duplicate robustness source_id")
            suffix = "-ff" if condition == "four_faults" else "-xs"
            if any(c["id"] != c["source_id"] + suffix for c in candidates):
                raise ValueError("robustness case id does not match source_id and condition")
        else:
            mapping = {c["id"]: c for c in cases}
        if any(case_id not in mapping for case_id in order):
            raise ValueError("a robust20 case is missing")
        cases = [mapping[case_id] for case_id in order]
    if ids:
        wanted = ids.split(",") if isinstance(ids, str) else list(ids)
        missing = set(wanted) - {c["id"] for c in cases}
        if missing:
            raise ValueError("requested case ids are absent from this selection")
        cases = [c for c in cases if c["id"] in wanted]
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be positive")
        cases = cases[:limit]
    cases = copy.deepcopy(cases)
    for case in cases:
        safe_name(case["id"])
        safe_name(case["input"]["system"])
        if condition is not None:
            case["input"]["condition"] = condition
        else:
            case["input"].setdefault("condition", "default")
    if not cases:
        raise ValueError("no cases selected")
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("duplicate case id")
    return cases


def resolve_model(config, names, condition, requested=None, environment=None):
    """A model is required only for AI arms. Swap overrides both other sources."""
    if not set(names) & AI_ARMS:
        return None
    if condition == "model_swap":
        model = config.get("swap")
        if not model or model == config.get("bulk"):
            raise ValueError("model_swap requires a non-empty swap model different from bulk")
    else:
        model = requested or (os.environ if environment is None else environment).get("IC_MODEL") or config.get("bulk")
    if not model:
        raise ValueError("AI evaluation needs --model, IC_MODEL or configs/models.json bulk")
    return model


def main(argv=None):
    arguments = parser().parse_args(argv)
    root = ROOT
    try:
        if arguments.report:
            safe_name(arguments.report)
            if arguments.against:
                safe_name(arguments.against)
            from .report import write_report
            output = write_report(root / "results" / arguments.report,
                against=root / "results" / arguments.against if arguments.against else None)
            print(f"Report written for {arguments.report}.")
            return 0
        if arguments.against:
            raise ValueError("--against requires --report")
        if not arguments.name:
            raise ValueError("--name is required for an evaluation run")
        safe_name(arguments.name)
        names = arguments.arms.split(",")
        if len(set(names)) != len(names) or any(name not in ARMS for name in names):
            raise ValueError("--arms must be a comma-separated list of distinct known arms")
        if arguments.final:
            seal = verify_seals(root, arguments.split)
        else:
            seal = None
        cases = select_cases(root, split=arguments.split, condition=arguments.condition,
                             ids=arguments.ids, limit=arguments.limit)
        if any(c["input"]["condition"] == "model_swap" for c in cases) and set(names) - AI_ARMS:
            raise ValueError("model_swap runs AI arms only")
        config = json.loads((root / "configs" / "models.json").read_text(encoding="utf-8"))
        models = {c["id"]: resolve_model(config, names, c["input"]["condition"], arguments.model) for c in cases}
        # Fail early, before bringing up any system. Oracle is local harness code.
        for name in names:
            if name != "oracle":
                load_arm(name)
        ports = [int(value) for value in arguments.port_bases.split(",")] if arguments.port_bases else (
            [9100, 9200, 9300] if arguments.split == "transfer" else [8100, 8200, 8300])
        hashes = current_hashes()
        freeze = verify_freeze(root, arguments.split, hashes) if arguments.final else None
        provenance = {"git_commit": git(root, "rev-parse", "HEAD"), "hashes": hashes, "seal": seal, "freeze": freeze}
        complete = run_cases(root, name=arguments.name, cases=cases, arm_names=names,
            split=arguments.split, models=models, copies=arguments.copies, port_bases=ports, provenance=provenance)
        print(f"Evaluation {'complete' if complete else 'incomplete'}: {arguments.name}.")
        return 0 if complete else 1
    except (ValueError, KeyError, OSError, ImportError) as exc:
        # Do not dump stack traces or system credentials into a terminal report.
        print(f"Evaluation refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
