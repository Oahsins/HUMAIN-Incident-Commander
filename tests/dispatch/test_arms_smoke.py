"""The baseline runbook's rules and the agent's survey read dispatch without raising (docs/DISPATCH.md).

Each fixture is describe(), observe() and probe() recorded from a live dispatch copy in one state. The only
assertion is that nothing raises: findings and proposals are not inspected, and no action or model is used.
Written after DECISIONS.md fixed dispatch's monitors and constants, so no arm shaped them.
"""

import json
import os

import pytest

from baselines import runbook
from ic.agent import survey

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
STATES = ("healthy", "unit_sync_stopped", "lock_held", "unreadable_report_crash")


def load(state):
    with open(os.path.join(FIXTURES, f"{state}.json"), encoding="utf-8") as handle:
        return json.load(handle)


@pytest.mark.parametrize("state", STATES)
def test_fixture_has_the_three_reads(state):
    fixture = load(state)
    assert set(fixture) >= {"describe", "observe", "probe"}
    assert fixture["describe"]["system"] == "dispatch"


@pytest.mark.parametrize("state", STATES)
def test_runbook_rules_read_dispatch(state):
    fixture = load(state)
    runbook._rules(fixture["describe"], fixture["observe"])


@pytest.mark.parametrize("state", STATES)
def test_agent_survey_reads_dispatch(state):
    fixture = load(state)
    survey.survey(fixture["describe"], fixture["observe"], fixture["probe"])
