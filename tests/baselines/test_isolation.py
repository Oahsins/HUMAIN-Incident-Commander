"""Keep the runbook behind the same public interface and data boundary as every arm."""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_IMPORTS = ("targets", "eval", "ic.agent", "ic.inject", "ic.systems", "ic.kit.client",
                     "ic.kit.supervisor", "ic.kit.store", "psutil", "sqlite3", "subprocess", "socket")
FORBIDDEN_TEXT = ("control.token", "customers.jsonl", "ledger.db", "changes.jsonl", "releases.json",
                  "heldout", "runs/", "X-Control-Token", "X-Admin-Token", "/control/", "IC_ADMIN_TOKEN")


@pytest.mark.parametrize("source", sorted((ROOT / "baselines").rglob("*.py")))
def test_baseline_has_no_privileged_imports_strings_or_file_reads(source):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports = [node.module or ""]
            imports += [f"{node.module}.{alias.name}" for alias in node.names]
        else:
            imports = []
        for name in imports:
            assert not any(name == blocked or name.startswith(blocked + ".") for blocked in FORBIDDEN_IMPORTS), (source, name)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not any(text.lower() in node.value.lower() for text in FORBIDDEN_TEXT), (source, node.lineno)
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            assert name not in ("open", "read_text", "read_bytes", "load", "loads", "__import__", "import_module", "exec", "eval"), (source, node.lineno, name)
