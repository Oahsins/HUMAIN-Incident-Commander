"""The ABCDE survey: check every component, in a fixed order, before fixing anything.

    A  Access        can users get in and complete the main journey? failing or refused requests, lost traffic
    B  Bottlenecks   slow responses, queues that do not drain, locks, failed writes
    C  Capacity      processes that are down, hung or crashing; busy jobs
    D  Dependencies  how each component sees the things it calls; datastores; systems run by others
    E  Events        what changed recently, and who changed it

The survey is a coverage check. Every finding gets an id (A1, B2, ...), and the
diagnosis must account for every fault finding, so a second or third fault is
not missed once the first one is found.

Nothing here knows which system it is looking at. Each component is judged
against its own warm-up baseline, with the thresholds below.
"""

import time

LETTERS = ("A", "B", "C", "D", "E")
LETTER_NAMES = {"A": "Access", "B": "Bottlenecks", "C": "Capacity", "D": "Dependencies", "E": "Events"}

RATE_SLACK = 0.02          # error or reject rate: more than baseline + 2 percentage points
P95_FACTOR = 2.0           # p95: more than twice the baseline...
P95_SLACK_MS = 250.0       # ...and more than 250 ms above it
QUEUE_AGE_S = 5.0          # work waiting longer than this is a backlog
RPS_DROP = 0.5             # traffic below half the baseline rate
RECENT_EXIT_S = 30.0       # with FLAPPING_EXITS exits in 15 min, the last one this recent: a crash loop
FLAPPING_EXITS = 3
BUSY_CPU_PCT = 50.0        # a job above this is noted (not a fault by itself)
DATA_CHECK = "data check failed: "


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _pct(value):
    return f"{value:.0%}"


def slow(now_ms, base_ms):
    """Is this p95 clearly worse than its baseline?"""
    now_ms, base_ms = _num(now_ms), _num(base_ms)
    if now_ms is None or base_ms is None:
        return False
    return now_ms > max(P95_FACTOR * base_ms, base_ms + P95_SLACK_MS)


def component_signals(name, entry, base, component, baselines, entry_point=False):
    """[(letter, severity, text)] for one component. severity is "fault" or "info".

    entry_point: users reach the system here (a journey's entry). Lost traffic is a
    fault only there; further in, less traffic usually means its callers are failing.
    """
    found = []
    base = base or {}
    kind = component.get("kind")
    extra = entry.get("extra") or {}
    owned_by_others = kind == "external"

    # C: is it running at all? A job that is not running is normal.
    if kind == "job":
        running = extra.get("running", entry.get("up"))
        if running and _num(entry.get("cpu_pct")) is not None and entry["cpu_pct"] > BUSY_CPU_PCT:
            found.append(("C", "info", f"job running, CPU {entry['cpu_pct']:.0f}%"))
        elif running:
            found.append(("C", "info", "job running"))
        if _num(extra.get("runs")) and extra["runs"] > 1:
            found.append(("C", "info", f"{extra['runs']} copies of the job running"))
        return found
    if entry.get("up") is False:
        detail = extra.get("error") or "not answering"
        found.append(("C" if not owned_by_others else "D", "fault", f"down ({detail})"))
    elif extra.get("not_answering"):
        found.append(("C", "fault", "process running but not answering"))
    exits = _num(extra.get("exits_15m"))
    if exits:
        ago = _num(extra.get("last_exit_s_ago"))
        text = f"process exited {exits:.0f} time(s) in 15 min, last {ago:.0f} s ago (exit code {extra.get('last_exit_code')})"
        # Up again after one exit (restarted, say) is context; exiting again and again is a fault.
        flapping = exits >= FLAPPING_EXITS and ago is not None and ago < RECENT_EXIT_S
        found.append(("C", "fault" if entry.get("up") is False or flapping else "info", text))

    # A (or D for systems run by others): requests failing or refused, traffic lost.
    letter = "D" if owned_by_others else "A"
    suffix = " (run by another organisation)" if owned_by_others else ""
    for key, label in (("error_rate", "of requests fail"), ("reject_rate", "of requests are refused")):
        now, then = _num(entry.get(key)), _num(base.get(key))
        if now is not None and now > (then or 0.0) + RATE_SLACK:
            found.append((letter, "fault", f"{_pct(now)} {label} (baseline {_pct(then or 0.0)}){suffix}"))
    now, then = _num(entry.get("rps")), _num(base.get("rps"))
    if now is not None and then is not None and then >= 1.0 and now < RPS_DROP * then:
        if extra.get("active") == "standby":   # its callers were switched to the standby: expected
            found.append((letter, "info", f"traffic {now:.1f}/s (baseline {then:.1f}/s): moved to its standby"))
        elif entry_point:
            found.append((letter, "fault", f"traffic {now:.1f}/s (baseline {then:.1f}/s){suffix}"))
        else:
            found.append((letter, "info", f"traffic {now:.1f}/s (baseline {then:.1f}/s), less work from its callers"
                                          f"{suffix}"))

    # B: slow, queued, locked.
    if slow(entry.get("p95_ms"), base.get("p95_ms")):
        found.append(("B" if not owned_by_others else "D", "fault",
                      f"p95 {entry['p95_ms']:.0f} ms (baseline {base['p95_ms']:.0f} ms){suffix}"))
    age = _num(extra.get("oldest_pending_s"))
    if age is not None and age > QUEUE_AGE_S:
        text = f"backlog: {extra.get('queue_depth')} items waiting, oldest {age:.0f} s"
        rate = _num(extra.get("processed_per_s"))
        if rate is not None:
            text += f", {rate:.1f} processed/s"
        head = extra.get("head_item") or {}
        if head.get("id") is not None:
            text += f"; first item {head['id']} waiting {head.get('age_s', 0):.0f} s after {head.get('attempts', 0)} attempt(s)"
        found.append(("B", "fault", text))
    for holder in extra.get("lock_holders") or []:
        found.append(("B", "fault", f"lock held by session {holder.get('session')} ({holder.get('mode')}) for "
                                    f"{holder.get('held_s')} s: {holder.get('statement', '')}".rstrip(": ")))
    if _num(extra.get("write_errors")):
        found.append(("B", "fault", f"{extra['write_errors']} failed writes in the window"))

    # D: how this component sees the things it calls, and the data it holds.
    for dep, view in (extra.get("dependencies") or {}).items():
        rate = _num(view.get("error_rate"))
        if rate is not None and rate > RATE_SLACK:
            found.append(("D", "fault", f"calls to {dep} fail: {_pct(rate)}"))
        if slow(view.get("p95_ms"), (baselines.get(dep) or {}).get("p95_ms")):
            found.append(("D", "fault", f"calls to {dep} are slow: p95 {view['p95_ms']:.0f} ms "
                                        f"({dep} itself answered in {baselines[dep]['p95_ms']:.0f} ms at baseline)"))
    for check, problems in (extra.get("integrity") or {}).items():
        if _num(problems):
            found.append(("D", "fault", f"{DATA_CHECK}{check.replace('_', ' ')} = {problems}"))
    if _num(extra.get("quarantined_items")):
        found.append(("D", "info", f"{extra['quarantined_items']} item(s) already set aside"))
    if extra.get("active") == "standby":
        found.append(("D", "info", "served by its standby"))
    return found


def probe_signals(probe):
    """[(letter, severity, component, text)] from one synthetic journey."""
    if not probe:
        return []
    out = []
    failing = [s for s in probe.get("steps", []) if not s.get("ok")]
    if failing:
        first = failing[0]
        out.append(("A", "fault", first.get("step"),
                    f"{probe.get('journey')} journey fails at step '{first.get('step')}': {first.get('detail', '')}"))
    return out


def journey_down(probe):
    """The main journey cannot even start: it fails at its first or second step."""
    steps = (probe or {}).get("steps", [])
    for index, step in enumerate(steps):
        if not step.get("ok"):
            return index <= 1
    return False


def survey(profile, obs, probe, *, now=None, change_horizon_s=900.0):
    """Run the five checks over every component. Returns {"findings", "coverage", "journey_down"}."""
    now = now or obs.get("t") or time.time()
    components = {c["name"]: c for c in profile["components"]}
    baselines = obs.get("baseline") or {}
    entry_points = {j.get("entry") for j in profile.get("journeys") or [] if j.get("entry")}
    if not entry_points:   # no journeys described: components nothing depends on are where users arrive
        called = {d for c in components.values() for d in c.get("depends_on") or []}
        entry_points = set(components) - called
    raw = []
    for name, comp in components.items():
        entry = (obs.get("components") or {}).get(name)
        if entry is None:
            raw.append(("C", "fault", name, "missing from observe()"))
            continue
        for letter, severity, text in component_signals(name, entry, baselines.get(name), comp, baselines,
                                                        entry_point=name in entry_points):
            raw.append((letter, severity, name, text))
    for letter, severity, step, text in probe_signals(probe):
        raw.append((letter, severity, step if step in components else None, text))
    for change in obs.get("changes") or []:
        age = now - change.get("t", now)
        if age <= change_horizon_s:
            detail = change.get("detail") or {}
            detail_text = ", ".join(f"{k}={v}" for k, v in detail.items()) if isinstance(detail, dict) else str(detail)
            raw.append(("E", "info", change.get("component"),
                        f"{age:.0f} s ago: {change.get('kind')} by {change.get('actor')}"
                        + (f" ({detail_text})" if detail_text else "")))
    findings, counters = [], {letter: 0 for letter in LETTERS}
    for letter in LETTERS:   # the fixed order
        for item_letter, severity, component, text in raw:
            if item_letter != letter:
                continue
            counters[letter] += 1
            findings.append({"id": f"{letter}{counters[letter]}", "letter": letter, "component": component,
                             "severity": severity, "text": text})
    coverage = {letter: sorted(components) for letter in LETTERS}
    return {"findings": findings, "coverage": coverage, "journey_down": journey_down(probe),
            "components_checked": len(components)}


def faults(findings):
    return [f for f in findings if f["severity"] == "fault"]


def data_check(finding):
    """(component, check, count) for a failed data check, else None. A count over a trailing window stays
    up after its cause is fixed, so verify compares it from one look to the next."""
    text = finding.get("text", "")
    if finding.get("severity") != "fault" or not text.startswith(DATA_CHECK):
        return None
    check, _, count = text[len(DATA_CHECK):].rpartition(" = ")
    try:
        return finding.get("component"), check, float(count)
    except ValueError:
        return None


def table(findings, letters=LETTERS):
    """The survey as plain text, one line per finding, in ABCDE order."""
    lines = []
    for letter in letters:
        items = [f for f in findings if f["letter"] == letter]
        lines.append(f"{letter} {LETTER_NAMES[letter]}: " + ("nothing abnormal" if not items else ""))
        for f in items:
            where = f"{f['component']}: " if f.get("component") else ""
            lines.append(f"  [{f['id']}] {'FAULT' if f['severity'] == 'fault' else 'info '} {where}{f['text']}")
    return "\n".join(lines)


def containment_candidate(profile, obs, probe, findings):
    """The one action allowed before the survey ends: fail a dependency over when the main journey is down.

    Only when the journey fails at its first or second step, and a component that
    has a standby (and may fail over) is down or answering its callers slowly, and
    is still on its primary. Returns (target, reason) or None.
    """
    if not journey_down(probe):
        return None
    baselines = obs.get("baseline") or {}
    entries = obs.get("components") or {}
    for comp in profile["components"]:
        if not comp.get("standby") or "failover" not in comp.get("actions", []):
            continue
        name = comp["name"]
        if ((entries.get(name) or {}).get("extra") or {}).get("active") == "standby":
            continue
        if (entries.get(name) or {}).get("up") is False:
            return name, f"{name} is down and the main journey fails"
        for caller in entries.values():
            view = ((caller.get("extra") or {}).get("dependencies") or {}).get(name)
            if view and slow(view.get("p95_ms"), (baselines.get(name) or {}).get("p95_ms")):
                return name, f"calls to {name} are slow (p95 {view['p95_ms']:.0f} ms) and the main journey fails"
    return None
