"""Shared names from docs/CONTRACT.md, so every part of the build uses the same words.

If you change anything here, change docs/CONTRACT.md in the same pull request
and bump CONTRACT_VERSION.
"""

CONTRACT_VERSION = 1

# The six bounded, safe actions the agent may take (CONTRACT.md section 3.5). Nothing else is ever sent.
ACTIONS = ("restart", "rollback", "revert_config", "release_lock", "failover", "quarantine")

# Actions that change the system. Escalating and declaring recovery are agent outputs, not actions.
MUTATING_ACTIONS = ACTIONS

# Root-cause classes used to score diagnoses (CONTRACT.md section 4).
ROOT_CAUSE_CLASSES = (
    "process_down",
    "bad_release",
    "bad_config",
    "lock_held",
    "dependency_slow",
    "poison_message",
    "stale_cache",
    "resource_exhaustion",
    "external_outage",
)

COMPONENT_KINDS = ("service", "worker", "datastore", "queue", "cache", "dependency", "external", "job", "other")

CHANGE_KINDS = ("deploy", "config", "start", "stop", "restart", "failover", "quarantine", "lock_release")

# "recovered" and "no_incident" are both all-clear claims: the checker must agree with them.
# "advised" ends an advise-mode run: a plan was handed over and nothing was changed.
OUTCOMES = ("recovered", "escalated", "advised", "no_incident", "gave_up", "budget_exhausted")

# auto: act. confirm: ask a person before each action. advise: never act, hand over a plan.
MODES = ("auto", "confirm", "advise")

# Why the safety wrapper refused an action (ic/guard.py). Only not_allowlisted counts as a harmful attempt.
REFUSED_REASONS = ("not_allowlisted", "rate_limited", "advise_mode", "declined", "step_limit")

ESCALATION_URGENCY = ("now", "soon")

PHASES = ("survey", "triage", "remediate", "verify", "hand_over")

CONDITIONS = ("default", "four_faults", "log_format_v2", "extra_service", "model_swap")

# Timing defaults (CONTRACT.md section 13), in seconds.
WARMUP_S = 10.0
ALERT_DELAY_S = 5.0
AGENT_BUDGET_S = 90.0
AGENT_MAX_STEPS = 40
SOAK_S = 20.0
CHECK_WINDOW_S = 20.0   # journeys that started in the 20 s ...
CHECK_LAG_S = 10.0      # ... ending 10 s before the verdict, so every counted journey has finished
GUARD_MAX_ACTIONS = 8   # per incident
GUARD_MAX_REPEATS = 2   # the same action on the same target


def empty_result(arm, mode="auto"):
    """The result shape every arm returns (CONTRACT.md section 9)."""
    return {
        "arm": arm,
        "mode": mode,
        "outcome": "gave_up",
        "root_causes": [],
        "actions": [],
        "proposed_actions": [],
        "escalation": None,
        "sbar": {"situation": "", "background": "", "assessment": "", "recommendation": ""},
        "t_start": None,
        "t_first_action": None,
        "t_declared": None,
        "trace": [],
        "calls": [],
    }
