"""Verify: is the system really back, and does it stay back?

Sustained (the method): wait for the actions to settle, then require
CLEAN_CHECKS clean looks in a row, CHECK_GAP_S apart. A clean look is a
passing probe and a survey with no fault findings, apart from faults already
handed to a person. One bad look resets the count.

Naive (an ablation): one look straight after the last action.
"""

from ic.agent import survey as abcde_survey

CLEAN_CHECKS = 2
CHECK_GAP_S = 4.0
LOOK_WINDOW_S = 4.0        # metrics window for each look: only what happened after the fix
SETTLE_MAX_S = 6.0


def look(incident, phase="verify", window_s=LOOK_WINDOW_S, ignore_components=()):
    """One observe and one probe. Returns (clean, findings, probe)."""
    profile = incident.describe()
    obs = incident.tool(phase, "observe", window_s)
    probe = incident.tool(phase, "probe") if (profile.get("capabilities") or {}).get("probe", True) else None
    result = abcde_survey.survey(profile, obs, probe)
    remaining = [f for f in abcde_survey.faults(result["findings"])
                 if f.get("component") not in ignore_components]
    probe_ok = probe is None or bool(probe.get("ok", all(s.get("ok") for s in probe.get("steps", []))))
    if probe is not None and not probe_ok:
        failing = next((s for s in probe.get("steps", []) if not s.get("ok")), {})
        if failing.get("component") in ignore_components:
            probe_ok = True
    return (probe_ok and not remaining), result["findings"], probe


def settle_seconds(profile, actions):
    seconds = [float(((profile.get("actions") or {}).get(a["action"]) or {}).get("est_seconds") or 1.0)
               for a in actions if a.get("sent")]
    return min(SETTLE_MAX_S, max(seconds, default=0.0) + 1.0)


def sustained(incident, actions, ignore_components=(), keep_s=0.0):
    """True when CLEAN_CHECKS looks in a row are clean. Returns (ok, last_findings)."""
    incident.wait(settle_seconds(incident.describe(), actions), keep_s=keep_s)
    streak, findings, attempts = 0, [], 0
    while streak < CLEAN_CHECKS:
        incident.need(LOOK_WINDOW_S + keep_s)
        attempts += 1
        clean, findings, _ = look(incident, ignore_components=ignore_components)
        streak = streak + 1 if clean else 0
        incident.note("verify", "note", "check", f"look {attempts}: {'clean' if clean else 'not clean'} "
                                                 f"({streak} of {CLEAN_CHECKS} in a row)")
        if streak >= CLEAN_CHECKS:
            return True, findings
        if not clean and attempts >= CLEAN_CHECKS + 1:
            return False, findings
        incident.wait(CHECK_GAP_S, keep_s=keep_s)
    return True, findings


def naive(incident, actions, ignore_components=(), keep_s=0.0):
    """One look right after the actions. Returns (ok, findings)."""
    incident.wait(1.0, keep_s=keep_s)
    clean, findings, _ = look(incident, ignore_components=ignore_components)
    incident.note("verify", "note", "check", f"single look: {'clean' if clean else 'not clean'}")
    return clean, findings
