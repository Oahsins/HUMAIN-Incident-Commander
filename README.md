# ABCDE Incident Commander

An AI incident commander for HUMAIN's Future AI Builders hackathon (Challenge 1: an AI agent that recovers a failing system).

**In 60 seconds**
- **What it is:** an agent that surveys every component of a failing system in a fixed order before fixing anything. It fixes upstream faults first, then the most harmful, using six bounded actions. It hands over with an SBAR, or escalates to a person.
- **Result:** [FILL: the headline sentence from fill-values.md, the same one used on the slides and the project page]
- **See it:** [the 3-minute video]([FILL: video link]) · [the slides]([FILL: slides link]) · or run `python run.py demo`, which needs no API key

It keeps a failing multi-service system running using the method emergency medicine uses for several injuries at once. It surveys every component in a fixed ABCDE order (Access, Bottlenecks, Capacity, Dependencies, Events) before fixing anything, triages the faults by customer impact against time to fix, remediates with six bounded actions only (four can be undone, two lose no committed data), verifies recovery over a sustained window, and hands over with an SBAR, or escalates to a person when no safe action fixes the fault. A safety wrapper refuses any action outside the allowlist, and an independent checker decides whether the system really recovered, mainly from the customers' own log, which the agent never sees, and a full read of the ledger.

The agent is portable: it needs only a 5-function adapter (describe, observe, logs, probe, act). So far it has been tested on two systems, both built on the same kit. A test system also supplies a control layer for fault injection and a checker. The main test system is a small bank around a double-entry ledger. The transfer test runs the frozen agent on dispatch, an emergency-dispatch system built after the freeze ([docs/DISPATCH.md](docs/DISPATCH.md)).

> **Status (31 Oct 2026):** built, frozen and measured. The agent, the bank, the runbook and the scorer were frozen at the `freeze-1` tag on 30 Oct; their hashes are in the [decision log](DECISIONS.md). The final run used the pre-registered core40 cut of the sealed exam, and the transfer run used 20 sealed dispatch incidents. Work started on 29 Oct, before the event, and is disclosed here. The commit history shows the dates.

## How it was built

Omar AlHejji designed the agent and made the calls recorded in the [decision log](DECISIONS.md). The method comes from his years as a paramedic: the primary survey, triage, reassessment and the SBAR handover. AI coding agents wrote the code:
- **Claude Code** wrote the agent, the bank and its checker, the shared kit and the dispatch system.
- **Codex, Session A** wrote and ran the sealed exams: the held-out and blind faults and the 60 bank incidents, then the dispatch exam.
- **Codex, Session B** wrote the scripted runbook and the evaluation harness, ran the pilot and produces the reports. It never saw the sealed files.

Codex commits carry Codex's name, so the history shows who wrote what. Every change reached `main` through a pull request that Omar merged.

## Quick start

Needs Python 3.11 or later, on Windows or Linux.

```
pip install -r requirements.txt -r requirements-eval.txt
python run.py preflight      # laptop checks: Python, packages, model key, free ports, disk space
python run.py up             # starts the bank (port base 8900) and its test customers
python run.py status         # every component and its health
python run.py check          # the independent checker's verdict (wait about 20 s after up)
python run.py demo           # about a minute: starts a fresh bank, injects 2 faults, runs the agent, prints the checker's verdict, stops the bank
python run.py down           # stops the bank if one is still running
```

`python run.py demo` runs live when `ANTHROPIC_API_KEY` is set. Without a key it replays a recorded run of the frozen agent (`replays/demo-frozen.jsonl`) and says so first. The system and the checks run live; only the model's answers are replayed, so the handover quotes the recorded run's times. Without a key, `preflight` reports FAIL for the provider key and exits 1; that is expected, and the rest of the quick start still works. Keys are read only from environment variables, never from files. `requirements-eval.txt` adds matplotlib, which `preflight` checks and the evaluation's charts and tests need.

## Results

**[FILL after the final run: replace every [FILL] from `results/final-1/report.md`, `results/robust-ff/report.md`, `results/robust-ms/report.md` and `results/transfer-1/report.md`, then delete this line.]**

Every result comes from the frozen code, scored by the independent checker, never by the agent's own claim. Every rate is n/N with a 95% Wilson interval. N is 40 minus exclusions for the main exam, and 20 minus exclusions for each robustness condition and for the transfer run. Arms are compared only by paired tests on identical cases, as the analysis plan fixed before the freeze ([CONTRACT section 16](docs/CONTRACT.md)). Where the scripted runbook ties or wins, that is reported too. The full reports hold every arm, metric, stratum and exclusion: [main exam](results/final-1/report.md), [four faults](results/robust-ff/report.md), [model swap](results/robust-ms/report.md), [transfer](results/transfer-1/report.md).

### Main exam: 40 sealed incidents (core40), 7 arms

The incidents were written by a separate Codex session and sealed 39 minutes before the agent's code first reached GitHub (seal 1 in [pull request #6](https://github.com/Oahsins/HUMAIN-Incident-Commander/pull/6), opened at 01:44 Riyadh on 30 Oct; the agent's first commit, [448b19d](https://github.com/Oahsins/HUMAIN-Incident-Commander/commit/448b19d91e9c35159d8e8b269c649a6b0bc9e5f5), is from 02:23). By design, three of the four new fault types (poison payment, stale balances, double posting) were named in the plan the agent was built from, and its prompt describes their fault classes; only the blind type was never named to the agent's builder. Of the full 60, 40 contain a named type, 8 the blind type and 5 practice faults only (`scenarios/heldout/SEALED.json`). As designed ([CONTRACT section 14](docs/CONTRACT.md)), there are 13 single cases, 17 two-fault cases and 10 three-fault cases. The 13 single cases include 4 healthy cases with no fault and 4 that must be escalated. [FILL] cases were excluded by the pre-registered validity rule ([FILL: reasons]).

| Arm | What it is | Case success | 95% Wilson |
|---|---|---|---|
| `abcde` | The full agent | [FILL] / [FILL] | [FILL] |
| `runbook` | A scripted runbook, no AI | [FILL] / [FILL] | [FILL] |
| `react` | A free-form baseline, not a one-part ablation: same model, tools and guard; no fixed survey, ordering, coverage check or off-list filter | [FILL] / [FILL] | [FILL] |
| `naive_verify` | The full agent, but "errors stopped" counts as recovered | [FILL] / [FILL] | [FILL] |
| `fifo` | The full agent, fixing faults in the order found | [FILL] / [FILL] | [FILL] |
| `noop` | Does nothing (validity check) | [FILL] / [FILL] | [FILL] |
| `oracle` | Applies the labelled fixes (validity check) | [FILL] / [FILL] | [FILL] |

**Primary comparison.** The comparison is `abcde` against `runbook` on case success, with an exact two-sided McNemar test on all valid cases.
- b = [FILL]
- c = [FILL]
- Difference: [FILL] points (95% paired bootstrap [FILL])
- p = [FILL]

**Secondary comparisons** (Holm-adjusted as one family):

| Comparison | Endpoint | b | c | Difference [95% CI] | p (adjusted) |
|---|---|---|---|---|---|
| `abcde` vs `runbook`, cases with a named held-out or blind fault | Case success | [FILL] | [FILL] | [FILL] | [FILL] |
| `abcde` vs `react` | Case success | [FILL] | [FILL] | [FILL] | [FILL] |
| `abcde` vs `naive_verify` | False all-clear | [FILL] | [FILL] | [FILL] | [FILL] |
| `abcde` vs `runbook` | User-impact seconds (Wilcoxon) | - | - | [FILL] | [FILL] |

**Where the runbook ties or wins:** [FILL, from the report's headline section].

**By fault type** (descriptive, case success, from the report's registered strata). The runbook's six rules were written for the practice fault types only.

| Cases | `abcde` | `runbook` | `react` |
|---|---|---|---|
| Practice fault types only | [FILL] / [FILL] | [FILL] / [FILL] | [FILL] / [FILL] |
| A named held-out type | [FILL] / [FILL] | [FILL] / [FILL] | [FILL] / [FILL] |
| The blind type | [FILL] / [FILL] | [FILL] / [FILL] | [FILL] / [FILL] |

### Robustness: robust20, descriptive

Two more pre-registered conditions, a changed log format and an extra service, were built but cut before the run by the plan's cut order ([decision log](DECISIONS.md), GO/NO-GO 3).

| Condition | Arm | Success | Paired change vs the main run |
|---|---|---|---|
| Four faults at once | `abcde` | [FILL] / [FILL] | [FILL] |
| Four faults at once | `runbook` | [FILL] / [FILL] | [FILL] |
| Model swap (Claude Haiku 5.5, not tuned on) | `abcde` | [FILL] / [FILL] | [FILL] |

### Transfer: dispatch, a system built after the freeze, descriptive

The frozen agent and the frozen runbook ran on 20 sealed dispatch incidents, which another builder wrote from dispatch's adapter and control interfaces. A unit-sync outage fixed later than about 70 s can still score red, because its backlog is dispatched again ahead of fresh calls ([decision log](DECISIONS.md), dispatch row 4). For that reason, misses are read beside time to mitigate.

| Arm | Success | 95% Wilson |
|---|---|---|
| `abcde` | [FILL] / [FILL] | [FILL] |
| `runbook` | [FILL] / [FILL] | [FILL] |

### Exploratory, declared before the final run

- **Omar's own unblinded review of 12 drawn `abcde` cases (exploratory):** [FILL].
- **Off-list proposals by arm, with a `react` sensitivity row:** [FILL].

## Limitations

- **Small test systems, built for this project.** The bank and dispatch are far simpler than production systems, and both were built with AI coding agents on the same kit. The faults are real events on running processes, but on systems we built.
- **40 incidents, not 60.** The final run started late, so it used the pre-registered core40 cut. Intervals are about ±15 points. If the runbook wins 5% of pairs, the primary test at 40 pairs detects a 25-point gain 74% of the time (92% at 60) and a 10-point gain 17% of the time, so a tie means "not shown", not "no effect".
- **Some scores need context.**
  - Time to mitigate follows the service target only, so a silent fault can score 0 s while the checker is red.
  - `react` fails a case on any off-list attempt that reaches the guard. `abcde`'s code drops off-list proposals before the guard, so that rule can fail `react` but never `abcde`; the exploratory table shows `react` both ways.
- **More tuning for the agent.** Beyond the 20 practice cases both tuned on, the agent was also tuned on harder incidents built from practice fault types, one with four faults at once ([decision log](DECISIONS.md), 30 Oct).
- **What the checker cannot see.** A payment lost silently before the scored window changes neither the verdict nor the handover score ([decision log](DECISIONS.md), 30 Oct).
- **"No incident" can skip the checks.** If the model dismisses every finding and none shows customers affected, the agent declares "no incident" without the two confirming checks (`ic/agent/abcde.py`).
- **The guard's limits are simple.** They count per incident, and the guard checks each action and its target, not its parameters (`ic/guard.py`).
- **The agent misreads one dispatch signal.** Dispatch's integrity counts show the present state, so a count that stays above 0 without growing is a problem still there; the frozen agent reads it as past damage from its second look on ([decision log](DECISIONS.md), dispatch row 1, amendment F7).
- **An untested attack path.** Customer text can reach logs that the model reads (prompt injection). It is not in the exam.
- **Two paths skip the safety check.**
  - The manual `run.py act` command and the bank's ops endpoint skip the guard.
  - Separately, the emergency failover does not check that the standby is up.
- **The keyless demo is a replay.** Without a key, the model's answers come from a recorded run. Only the system, the actions and the checks are live.

## Tests

After installing both requirement files, `python -m pytest -q` runs the fast tier: about 900 tests, under a minute. With `IC_SLOW=1` it adds the live tier, which starts real copies of the bank and dispatch. CI runs both tiers on Ubuntu and Windows with Python 3.11. Dispatch's long tier and 10-minute soak are run by hand (see `tests/dispatch/test_live.py`).

To check that a run used the frozen code, `python run.py hash` prints the freeze hashes. Compare them with the freeze record in the [decision log](DECISIONS.md).

## Documents

- [Build plan](docs/BUILD-PLAN.md): timetable, roles, go/no-go checks, cut lines, test design
- [Interface contract](docs/CONTRACT.md): how the agent, the test systems, the faults, the checker and the evaluation fit together
- [Dispatch](docs/DISPATCH.md): the transfer system, its facts and its fault channels
- [Adding a system](docs/ADDING-A-SYSTEM.md): how to connect the agent to a system that already runs, or build a new test system on `ic/kit`
- [Decision log](DECISIONS.md)
- [Codex handoff](docs/CODEX-HANDOFF.md): the tasks Codex owns on the Windows laptop
