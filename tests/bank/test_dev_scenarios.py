"""The 32 practice scenarios keep the section 8 format (CONTRACT.md) and match their generator."""

import importlib
import json
import os
import runpy

from ic import contract

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEV = os.path.join(ROOT, "scenarios", "dev", "dev.jsonl")
COMPONENTS = {"gateway", "payments", "screening", "screening-standby", "clearing", "ledger", "network", "reconciliation"}


def _cases():
    with open(DEV, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_thirty_two_cases_in_order():
    assert [c["id"] for c in _cases()] == [f"dev-{n:02d}" for n in range(1, 33)]


def test_every_case_keeps_the_format():
    for c in _cases():
        given, labels = c["input"], c["target"]
        assert given["system"] == "bank" and given["condition"] in contract.CONDITIONS
        for f in given["faults"]:
            assert 0 <= f["at_s"] <= 8, c["id"]
            importlib.import_module(f"targets.bank.faults.dev.{f['type']}")
        assert 1 <= sum(f["type"] == "benign" for f in given["faults"]) <= 3, c["id"]
        for cause in labels["root_causes"]:
            assert cause["target"] in COMPONENTS and cause["class"] in contract.ROOT_CAUSE_CLASSES, c["id"]
            assert cause["fix"]["action"] in contract.ACTIONS + ("escalate",), c["id"]
        assert labels["healthy"] == (not labels["root_causes"]), c["id"]
        assert labels["must_escalate"] == any(r["fix"]["action"] == "escalate" for r in labels["root_causes"])
        assert labels["blind"] is False and labels["acceptable_secondary"] == []


def test_the_generator_writes_the_same_file(tmp_path, monkeypatch):
    before = open(DEV, "rb").read()
    module = runpy.run_path(os.path.join(ROOT, "scenarios", "dev", "make_dev.py"), run_name="not_main")
    out = tmp_path / "dev.jsonl"
    monkeypatch.setitem(module["main"].__globals__, "OUT", str(out))
    module["main"]()
    assert out.read_bytes() == before
