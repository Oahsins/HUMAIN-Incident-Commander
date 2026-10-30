# Scripted runbook

`runbook.py` is the non-AI comparison arm. It reads only the five public adapter
methods through the safety wrapper. It uses no model, private system state,
scenario labels or system-specific component names.

Each pass reads the current observations and runs the synthetic journey. It
checks these rules in a fixed order and takes the first eligible correction:

1. A datastore lock blocks writes: release it.
2. A changed release coincides with local failures: roll back.
3. A setting change coincides with errors, rejects or a stalled queue: revert it.
4. A process is down or unresponsive: restart it.
5. An operator stopped a worker: restart it.
6. Callers see a slow or failing dependency with a usable standby: fail over.

The next pass waits for the action's advertised settling time and at least the
adapter's minimum observation window. After an action, observations include
only traffic since that action returned, capped at the usual ten-second window
(or the adapter's longer minimum). This stops old downstream errors being blamed
on an unrelated change after a repair. A rule cannot
repeat the same action on the same target consecutively. A release change alone,
a small configuration change alone or a busy scheduled job does not trigger a
correction. The runbook checks component action lists before sending commands.
It defers a caller's configuration change when a failing dependency edge is
corroborated by the dependency's own symptoms. A failing edge to a healthy
dependency still permits a local configuration fix, such as a timeout change.
An external component reports only its callers' view. If a local numeric setting
fell below one tenth of its previous positive value, that mirrored failure does
not block a setting reversal. Small changes still defer to an apparent external
outage, and an independently failing internal dependency still takes precedence.
If the external outage remains after the reversal, the runbook escalates.
For a down worker, a recorded stop takes priority over setting changes until
that worker is started or restarted by any actor. If it crashes again, an
unresolved setting can be reverted before another restart. A change made after
its last exit cannot explain that exit; an earlier setting remains eligible
for reversal if it could have caused the crash.
Quarantine remains available in the common safety wrapper, but none of these
six practice signatures justifies using it.

Recovery requires three consecutive passing probes spanning at least ten
seconds, with no remaining matching rule. A healthy survey returns `no_incident`.
If a probe fails and the earlier observations match no rule, the runbook takes
one fresh observation before escalating. A queue may have stalled while that
probe waited. For an aged worker queue with a setting change, the fresh window
excludes completions before its earliest severe unresolved change, when one
exists. Earlier harmless changes to that worker's other settings do not mask
the stall. Other workers' unresolved changes still bound the global window,
retaining their progress even if no work finished during the probe.
The usual window and the adapter's minimum still bound the read; unknown change
or observation times retain the usual window. Change ages use the target's
observation clock plus local monotonic elapsed time, so a clock offset does not
discard valid progress. A queue still making progress does not trigger
a setting reversal just because its setting changed. This extra read uses the
same step and time budgets.
An unresolved failed journey goes to a human with a short SBAR. Advise mode
returns the proposed actions without calling `act`; confirm mode honours the
confirmation decision. Time and step limits still return an SBAR.

Run the fast, invented-system tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/baselines -q --tb=line
```

Run the six single-fault practice smoke checks on the reserved live-test copy:

```powershell
.\.venv\Scripts\python.exe -m tests.baselines.live_practice
```

The latter starts and stops one copy on port base 8700 and records local evidence
in `runs/c2-practice.json`. It checks the selected correction and the runbook's
own recovery declaration. It does not replace the independent checker or an
evaluation run, and its results are practice evidence only.
