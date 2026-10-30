"""The agent knows no system: no system's words in its code, and any adapter that keeps the contract will do."""

import os
import re

from ic.kit.conformance import check_adapter
from tests.agent.fake_system import FakeSystem

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENT_FILES = [os.path.join(ROOT, "ic", name) for name in ("guard.py", "llm.py", "demo.py")] + [
    os.path.join(ROOT, "ic", "agent", name) for name in sorted(os.listdir(os.path.join(ROOT, "ic", "agent")))
    if name.endswith(".py")]
# Words that belong to one system: the practice bank's components, settings and money terms, and dispatch's.
SYSTEM_WORDS = re.compile(r"\b(bank|banking|ledger|payments?|gateway|clearing|screening|network|reconciliation|"
                          r"notifications?|transfer_limit|balances?|dispatch|ambulance)\b", re.I)


def test_no_system_words_in_the_agent():
    found = []
    for path in AGENT_FILES:
        for number, line in enumerate(open(path, encoding="utf-8"), 1):
            if SYSTEM_WORDS.search(line):
                found.append(f"{os.path.relpath(path, ROOT)}:{number}: {line.strip()}")
    assert found == [], "\n".join(found)


def test_fake_system_keeps_the_contract():
    assert check_adapter(FakeSystem()) == []
