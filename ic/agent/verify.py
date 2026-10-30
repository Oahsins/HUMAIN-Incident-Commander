"""Verify: is the system really back, and does it stay back?

Sustained (the method): wait for the actions to settle, then require
CLEAN_CHECKS clean looks in a row, CHECK_GAP_S apart (closer, down to
MIN_GAP_S, when only that fits the next look into the budget). A clean look is
a passing probe and a survey with no fault findings, apart from faults already
handed to a person. One bad look resets the count; MISSES_TO_STOP bad looks in
a row end the check, so the time left goes to a reassessment.

Each look reads the survey knowing when the commander last acted on each
component, so a crash loop that ended with its restart is history, not a fault.

A failed data check counts over a trailing window, so it stays up after its
cause is fixed. From the second look on, a data check whose count has not grown
since the look before is past damage, not an open fault: it does not block
recovery, and the arm hands it to a person (damage()).

Naive (an ablation): one look straight after the last action.
"""

import time

from ic.agent import survey as abcde_survey

CLEAN_CHECKS = 2
MISSES_TO_STOP = 2         # not clean this many looks in a row: stop and reassess
CHECK_GAP_S = 4.0
MIN_GAP_S = 1.0            # the shortest gap, when only that fits the next look into the budget
TIME_MARGIN_S = 0.5        # left over after a shortened gap, so the next look still clears need()
LOOK_WINDOW_S = 4.0        # metrics window for each look: only what happened after the fix
SETTLE_MAX_S = 6.0


def open_faults(findings, ignore_components=(), tolerate=None):
    """Fault findings still open: not on a component handed to a person, and not past damage."""
    tolerate = tolerate or {}
    out = []
    for finding in abcde_survey.faults(findings):
        if finding.get("component") in ignore_components:
            continue
        check = abcde_survey.data_check(finding)
        if check and check[:2] in tolerate and check[2] <= tolerate[check[:2]]:
            continue
        out.append(finding)
    return out


def data_counts(findings):
    """{(component, check): count} for every failed data check."""
    return {c[:2]: c[2] for c in map(abcde_survey.data_check, findings) if c}


def damage(findings, ignore_components=()):
    """The failed data checks left at the end of a passing check: past damage for a person to put right."""
    return [f for f in findings if abcde_survey.data_check(f) and f.get("component") not in ignore_components]


def acted_ago(actions, now=None):
    """{component: seconds since the incident commander last acted on it successfully}, by the commander's clock."""
    now = time.time() if now is None else now
    return {a["target"]: now - a["t"] for a in actions or [] if a.get("sent") and a.get("ok") and a.get("target")}


def probe_passed(probe):
    return probe is None or bool(probe.get("ok", all(s.get("ok") for s in probe.get("steps", []))))


def look(incident, phase="verify", window_s=LOOK_WINDOW_S, ignore_components=(), tolerate=None):
    """One observe and one probe. Returns (clean, findings, probe)."""
    profile = incident.describe()
    obs = incident.tool(phase, "observe", window_s)
    probe = incident.tool(phase, "probe") if (profile.get("capabilities") or {}).get("probe", True) else None
    result = abcde_survey.survey(profile, obs, probe, acted_ago=acted_ago(incident.result["actions"]))
    remaining = open_faults(result["findings"], ignore_components, tolerate)
    probe_ok = probe_passed(probe)
    if probe is not None and not probe_ok:
        failing = next((s for s in probe.get("steps", []) if not s.get("ok")), {})
        if failing.get("component") in ignore_components:
            probe_ok = True
    return (probe_ok and not remaining), result["findings"], probe


def still_abnormal(findings, ignore_components=(), tolerate=None, limit=3):
    """The first few open fault findings after a look, for the trace and the handover."""
    left = open_faults(findings, ignore_components, tolerate)
    if not left:
        return ""
    text = "; ".join((f"{f['component']}: " if f.get("component") else "") + f["text"] for f in left[:limit])
    return f"; still abnormal: {text}" + (f" (+{len(left) - limit} more)" if len(left) > limit else "")


def settle_seconds(profile, actions):
    seconds = [float(((profile.get("actions") or {}).get(a["action"]) or {}).get("est_seconds") or 1.0)
               for a in actions if a.get("sent")]
    return min(SETTLE_MAX_S, max(seconds, default=0.0) + 1.0)


def sustained(incident, actions, ignore_components=(), keep_s=0.0):
    """True when CLEAN_CHECKS looks in a row are clean. Returns (ok, last_findings)."""
    incident.wait(settle_seconds(incident.describe(), actions), keep_s=keep_s)
    streak, misses, findings, attempts, counts = 0, 0, [], 0, None
    while streak < CLEAN_CHECKS:
        incident.need(LOOK_WINDOW_S + keep_s)
        attempts += 1
        tolerate = counts
        clean, findings, _ = look(incident, ignore_components=ignore_components, tolerate=tolerate)
        counts = data_counts(findings)
        streak, misses = (streak + 1, 0) if clean else (0, misses + 1)
        incident.note("verify", "note", "check", f"look {attempts}: {'clean' if clean else 'not clean'} "
                                                 f"({streak} of {CLEAN_CHECKS} in a row)"
                                                 + still_abnormal(findings, ignore_components, tolerate))
        if streak >= CLEAN_CHECKS:
            return True, findings
        # Settled and still not clean twice running: the fixes did not work, so stop looking and reassess
        # while there is budget left for it.
        if misses >= MISSES_TO_STOP or (not clean and attempts >= CLEAN_CHECKS + 1):
            return False, findings
        gap = min(CHECK_GAP_S, incident.remaining() - LOOK_WINDOW_S - keep_s - TIME_MARGIN_S)
        incident.wait(max(MIN_GAP_S, gap), keep_s=keep_s)
    return True, findings


def naive(incident, actions, ignore_components=(), keep_s=0.0):
    """One look right after the actions. Returns (ok, findings)."""
    incident.wait(1.0, keep_s=keep_s)
    clean, findings, _ = look(incident, ignore_components=ignore_components)
    incident.note("verify", "note", "check", f"single look: {'clean' if clean else 'not clean'}"
                                             + still_abnormal(findings, ignore_components))
    return clean, findings
