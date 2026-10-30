"""An arm sees the system only through the adapter (CONTRACT.md section 9, Isolation).

No file of the agent, the safety wrapper or the model client may import a test
system, the harness, the runbook or the kit's privileged parts, or name the
files and tokens that hold the answers.
"""

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKED = [os.path.join(ROOT, "ic", "guard.py"), os.path.join(ROOT, "ic", "llm.py")] + [
    os.path.join(ROOT, "ic", "agent", name) for name in sorted(os.listdir(os.path.join(ROOT, "ic", "agent")))
    if name.endswith(".py")]
FORBIDDEN_IMPORTS = ("targets", "eval", "baselines", "tests", "ic.inject", "ic.systems", "ic.kit.client",
                     "ic.kit.supervisor", "ic.kit.store", "psutil", "sqlite3", "subprocess", "socket")
FORBIDDEN_STRINGS = ("control.token", "customers.jsonl", "ledger.db", "changes.jsonl", "releases.json", "heldout",
                     "runs/", "X-Control-Token", "X-Admin-Token", "/control/", "IC_ADMIN_TOKEN")


def _tree(path):
    return ast.parse(open(path, encoding="utf-8").read(), filename=path)


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module


def _forbidden(name):
    return any(name == f or name.startswith(f + ".") for f in FORBIDDEN_IMPORTS)


def test_no_forbidden_imports():
    found = [(os.path.relpath(path, ROOT), name) for path in CHECKED for name in _imports(_tree(path))
             if _forbidden(name)]
    assert found == []


def test_no_answer_files_or_tokens_named():
    found = []
    for path in CHECKED:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found += [(os.path.relpath(path, ROOT), s) for s in FORBIDDEN_STRINGS if s in node.value]
    assert found == []


def test_baselines_never_import_the_agent():
    folder = os.path.join(ROOT, "baselines")
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        if name.endswith(".py"):
            assert not [m for m in _imports(_tree(os.path.join(folder, name))) if m.startswith("ic.agent")]
