# ABCDE Incident Commander

My entry for HUMAIN's Future AI Builders hackathon, Challenge 1: an AI agent that recovers a failing system.

- Live console, nothing to install: https://oahsins.github.io/HUMAIN-Incident-Commander/
- Run it in your browser: [open in GitHub Codespaces](https://codespaces.new/Oahsins/HUMAIN-Incident-Commander?quickstart=1) (a free GitHub account is enough)
- Demo video (3 minutes) and slides: on the project page

## What it does

I'm a paramedic. At a scene with several injuries, you don't start on the first one you see. You check everything in a fixed order, deal with the most dangerous problem first, check again, and hand over with a short structured report called an SBAR. I wanted to see whether an AI agent could work a failing computer system the same way.

When something breaks, the agent:

1. Surveys every component in a fixed order, A to E: Access, Bottlenecks, Capacity, Dependencies, Events.
2. Triages the faults: upstream faults first, then the most harmful.
3. Remediates with six bounded actions only. Four of them can be undone, and the other two lose no committed data. A guard refuses anything that isn't on the list.
4. Verifies the fix, and only says "recovered" after two clean checks in a row.
5. Hands over with an SBAR note, or escalates to a person when no safe action can fix the fault.

The AI proposes and plain code checks. Claude reads the survey, names each fault and its fix, and writes the handover. The code runs the survey, checks the AI's answer, orders the fixes, blocks anything off the list and judges recovery.

The agent only needs five functions from a system: describe, observe, logs, probe and act. I tested it on two systems built on the same kit: a small bank built around a double-entry ledger, and an emergency dispatch system that was built after the agent was frozen ([docs/DISPATCH.md](docs/DISPATCH.md)). The agent's own claim is never the score. A separate checker decides whether the system really recovered. On the bank, it scores the customers' own log and reads the whole ledger.

## Results

- On 40 sealed incidents it had never seen, the agent succeeded on 39 of 40 and a scripted runbook on 19 of 40 (paired test, p < 0.001).
- On the blind fault type, which neither had practised: 5 of 5 against 2 of 5.
- With four faults at once, it succeeded on 19 of 20.
- On dispatch, a system it was never tuned on, it succeeded on 13 of 20, and the runbook on 9 of 20.
- On a smaller model it was not tuned on, it did worse: 15 of 20, and 2 of its 15 all-clear claims were false.
- The same agent fixing faults in the order it found them, instead of in triage order, succeeded on 40 of 40. So this exam doesn't show that the triage order itself helps.

Every table is in [Full results](#full-results) below.

## Quick start

You need Python 3.11 or later, on Windows or Linux. If you'd rather not install anything, the Codespaces link above sets everything up and opens the incident console in your browser.

```
pip install -r requirements.txt -r requirements-eval.txt
python run.py demo           # about a minute: starts a fresh bank, injects 2 faults, runs the agent, prints the checker's verdict, stops the bank
```

The demo works without an API key. It then replays the model's answers from a recorded run of the frozen agent (`replays/demo-frozen.jsonl`), and says so first. The bank, the actions and the checks still run live. Only the model's answers are replayed, which is why the handover quotes the recorded run's times. With `ANTHROPIC_API_KEY` set, it runs live. Keys are only read from environment variables, never from files.

The other commands:

```
python run.py preflight      # laptop checks: Python, packages, model key, free ports, disk space
python run.py up             # starts the bank (port base 8900) and its test customers
python run.py status         # every component and its health
python run.py check          # the checker's verdict (wait about 20 s after up)
python run.py down           # stops the bank if one is still running
```

Without a key, `preflight` reports FAIL for the provider key and exits 1. That's expected, and the rest still works. `requirements-eval.txt` adds matplotlib, which `preflight` checks and the evaluation's charts and tests need.

### Incident console

Run `python console/app.py`, then open http://127.0.0.1:8088. Pick one of the 32 practice incidents and a mode (auto, confirm or advise), press Run, and watch the frozen agent's survey, actions, rechecks, handover and the checker's verdict come in live. It drives the same `run.py` commands as above.

The same page can also run a set of ticked cases one after another (auto or advise), filling a scoreboard with the agent's outcome, the actions it sent and the checker's verdict. Its Self-test button runs the repository's own tests (`python -m pytest -q`, about a minute, no key). A Dispatch filter adds three practice incidents on the second system (`scenarios/dev/dispatch-practice.jsonl`, added on 31 Oct and not part of any exam).

The two-fault demo runs without a key, as a replay. Every other case needs an Anthropic key, typed into the page or set as `ANTHROPIC_API_KEY`. The key goes only to that run and is never saved.

### Tests

`python -m pytest -q` runs the fast tests: about 900 of them, in under a minute. With `IC_SLOW=1` it adds the live tests, which start real copies of the bank and dispatch. GitHub Actions runs both on Ubuntu and Windows with Python 3.11. Dispatch's long tests and its 10-minute soak are run by hand (see `tests/dispatch/test_live.py`).

To check that a run used the frozen code, `python run.py hash` prints the freeze hashes. Compare them with the freeze record in the [decision log](DECISIONS.md).

## Built with

- Python 3.11 or later, mostly the standard library. Every service of the bank and of dispatch runs on `http.server` and calls the others with `urllib` (the shared kit is in `ic/kit/`). The bank's ledger uses `sqlite3`. The evaluation runs each arm on each incident in its own process (`multiprocessing`) and stops it at its time limit.
- `psutil`, `rich`, `pytest` and `matplotlib` (`requirements.txt`, `requirements-eval.txt`).
- Claude, called through the Anthropic Messages API over HTTPS with no SDK (`ic/llm.py`). The models are set in `configs/models.json`, and their prices in `configs/prices.json`.
- Playwright with Chromium, on Node 18 or later, for the browser demo (`browser-demo/`).
- GitHub Actions runs the tests on every pull request. GitHub Codespaces gives a ready-to-run copy (`.devcontainer/`), and GitHub Pages serves the console page (`docs/`).

## How I built it

I designed the agent and made the calls recorded in the [decision log](DECISIONS.md). The method comes from my years as a paramedic: the primary survey, triage, reassessment and the SBAR handover. AI coding agents wrote the code:

- Claude Code wrote the agent, the bank and its checker, the shared kit, the dispatch system and the console.
- Codex (Session A) wrote and ran the sealed exams: the held-out and blind faults and the 60 bank incidents, then the dispatch exam.
- Codex (Session B) wrote the scripted runbook and the evaluation harness, ran the pilot and produces the reports. It never saw the sealed files.

Codex's commits carry its name, so the history shows who wrote what. Every change reached `main` through a pull request that I merged. I started on 29 Oct 2026, before the event, and the commit history shows the dates.

## Full results

Every result here comes from the frozen code and is scored by the checker, never by the agent's own claim. Each rate is n/N with a 95% Wilson interval. N is 40 minus exclusions for the main exam, and 20 minus exclusions for each robustness condition and for the transfer run. Arms are only compared with paired tests on the same cases, as the analysis plan fixed before the freeze ([CONTRACT section 16](docs/CONTRACT.md)). Where the scripted runbook ties or wins, I report that too. The full reports have every arm, metric, stratum and exclusion: [main exam](results/final-1/report.md), [four faults](results/robust-ff/report.md), [model swap](results/robust-ms/report.md), [transfer](results/transfer-1/report.md).

The agent, the bank, the runbook and the checker were frozen at the `freeze-1` tag on 30 Oct, and their hashes are in the [decision log](DECISIONS.md). The final run used the pre-registered core40 cut of the sealed exam, and the transfer run used 20 sealed dispatch incidents. The AI arms (`abcde`, `react`, `naive_verify`, `fifo`), and `abcde` in the four-faults and model-swap runs, first ran without the model key, so none of their model calls reached the provider. As CONTRACT section 11 requires for a model-provider failure, they were re-run on the same cases and seeds from the same frozen code. I logged that decision before any re-run result existed ([decision log](DECISIONS.md), 31 Oct). The runbook, `noop` and `oracle` make no model calls, so they keep their first runs.

### Main exam: 40 sealed incidents, 7 arms

A separate Codex session wrote the incidents and sealed them 39 minutes before the agent's code first reached GitHub. Seal 1 is in [pull request #6](https://github.com/Oahsins/HUMAIN-Incident-Commander/pull/6), opened at 01:44 Riyadh on 30 Oct. The agent's first commit, [448b19d](https://github.com/Oahsins/HUMAIN-Incident-Commander/commit/448b19d91e9c35159d8e8b269c649a6b0bc9e5f5), is from 02:23.

By design, three of the four new fault types (poison payment, stale balances, double posting) were named in the plan the agent was built from, and its prompt describes their fault classes. Only the blind type was never named to the agent's builder. Of the full 60 incidents, 40 contain a named type, 8 the blind type and 5 practice faults only (`scenarios/heldout/SEALED.json`). The core40 cut has 13 single cases, 17 two-fault cases and 10 three-fault cases, as designed ([CONTRACT section 14](docs/CONTRACT.md)). The 13 single cases include 4 healthy cases with no fault and 4 that must be escalated. No case was excluded by the pre-registered validity rule.

| Arm | What it is | Case success | 95% Wilson |
|---|---|---|---|
| `abcde` | The full agent | 39 / 40 | 87%–100% |
| `runbook` | A scripted runbook, no AI | 19 / 40 | 33%–63% |
| `react` | A free-form baseline, not a one-part ablation: same model, tools and guard; no fixed survey, ordering, coverage check or off-list filter | 23 / 40 | 42%–71% |
| `naive_verify` | The full agent, but "errors stopped" counts as recovered | 33 / 40 | 68%–91% |
| `fifo` | The full agent, fixing faults in the order found | 40 / 40 | 91%–100% |
| `noop` | Does nothing (validity check) | 4 / 40 | 4%–23% |
| `oracle` | Applies the labelled fixes (validity check) | 36 / 40 | 77%–96% |

The primary test, fixed before the run, is `abcde` against `runbook` on case success, with an exact two-sided McNemar test on all valid cases. It gave b = 20 and c = 0, a difference of +50 points (95% paired bootstrap +35 to +65), and p < 0.001.

The secondary tests are Holm-adjusted as one family:

| Comparison | Endpoint | b | c | Difference [95% CI] | p (adjusted) |
|---|---|---|---|---|---|
| `abcde` vs `runbook`, cases with a named held-out or blind fault | Case success | 20 | 0 | +71 pts [+54 pts to +86 pts] | <0.001 |
| `abcde` vs `react` | Case success | 16 | 0 | +40 pts [+25 pts to +55 pts] | <0.001 |
| `abcde` vs `naive_verify` | False all-clear | 0 | 0 | +0 pts [+0 pts to +0 pts] | 1.000 |
| `abcde` vs `runbook` | User-impact seconds (Wilcoxon) | - | - | - | 0.197 |

In these tests, b is the number of cases only `abcde` succeeded on, and c the number only the other arm succeeded on. Each difference is `abcde` minus the other arm. False all-clear works the other way, because lower is better: there b counts the cases where only `abcde` gave a false all-clear, so a larger b or a positive difference counts against `abcde`. The Wilcoxon test has no b, c or difference.

The runbook won 0 of the 40 paired cases (95% Wilson 0.0%–8.8%) and tied on 20 of 40 (95% Wilson 35.2%–64.8%).

By fault type (descriptive, case success, from the report's registered strata). The runbook's six rules were written for the practice fault types only.

| Cases | `abcde` | `runbook` | `react` |
|---|---|---|---|
| Practice fault types only | 4 / 4 | 4 / 4 | 4 / 4 |
| A named held-out type | 25 / 26 | 5 / 26 | 13 / 26 |
| The blind type | 5 / 5 | 2 / 5 | 3 / 5 |

### Four faults at once and a model swap (robust20, descriptive)

Two more pre-registered conditions, a changed log format and an extra service, were built but cut before the run, following the plan's cut order ([decision log](DECISIONS.md), GO/NO-GO 3).

| Condition | Arm | Success | Paired change vs the main run |
|---|---|---|---|
| Four faults at once | `abcde` | 19 / 20 | -5 pts [-15 pts to +0 pts] |
| Four faults at once | `runbook` | 9 / 20 | +0 pts [+0 pts to +0 pts] |
| Model swap (a smaller model, not tuned on; see `configs/models.json`) | `abcde` | 15 / 20 | -25 pts [-45 pts to -5 pts] |

Each change is in points, paired case by case with the main run. A negative change is a drop.

### Dispatch: a system built after the freeze (descriptive)

The frozen agent and the frozen runbook ran on 20 sealed dispatch incidents, which another builder wrote from dispatch's adapter and control interfaces. One catch: a unit-sync outage fixed later than about 70 s can still score red, because its backlog is dispatched again ahead of fresh calls ([decision log](DECISIONS.md), dispatch row 4). So I read the misses beside time to mitigate.

| Arm | Success | 95% Wilson |
|---|---|---|
| `abcde` | 13 / 20 | 43%–82% |
| `runbook` | 9 / 20 | 26%–66% |

### Exploratory, declared before the final run

- My own unblinded review of 12 drawn `abcde` cases: pending. The 12 cases were redrawn from the re-run by the declared rule.
- Off-list proposals by arm, with a `react` sensitivity row. No arm proposed an off-list action and none made a harmful-action attempt, so every arm had off-list proposals in 0 of 40 cases (95% Wilson 0%–8.8%). Off-list counts the guard's `not_allowlisted` refusals plus the "dropped fix" notes from the agent's triage step. The runbook is zero by construction.

| Arm | Off-list proposals | Harmful-action attempts | 95% Wilson |
|---|---|---|---|
| `abcde` | 0 | 0 / 85 | 0%–4.3% |
| `runbook` | 0 | 0 / 60 | 0%–6.0% |
| `react` | 0 | 0 / 70 | 0%–5.2% |
| `naive_verify` | 0 | 0 / 83 | 0%–4.4% |
| `fifo` | 0 | 0 / 86 | 0%–4.3% |
| `noop` | 0 | 0 / 0 | not estimable |
| `oracle` | 0 | 0 / 80 | 0%–4.6% |

If off-list refusals didn't count as harm (harmful quarantines still would), `react` would still succeed on 23 of 40 (95% Wilson 42%–71%). No case score changes, so its gap to `abcde` stays at 40 points (95% CI 25 to 55, exact McNemar p = 0.00003). That row is outside the registered Holm family. The registered `react` test is the one in the secondary tests above.

## Limitations

- The test systems are small and were built for this project. The bank and dispatch are far simpler than production systems, and both were built with AI coding agents on the same kit. The faults are real events on running processes, but on systems we built.
- The triage order isn't shown to help here. `fifo`, the same agent fixing faults in the order it found them, succeeded on 40 of 40, against 39 of 40 for the full agent. That row is descriptive, not one of the pre-registered tests, but it means I can't claim the triage order itself improves results on this exam.
- It's 40 incidents, not 60. The final run started late, so it used the pre-registered core40 cut, and the intervals are about ±15 points. If the runbook wins 5% of pairs, the primary test at 40 pairs detects a 25-point gain 74% of the time (92% at 60) and a 10-point gain 17% of the time. So a tie would mean "not shown", not "no effect".
- Some scores need context. Time to mitigate follows the service target only, so a silent fault can score 0 s while the checker is red. Also, `react` fails a case on any off-list attempt that reaches the guard. `abcde`'s code drops off-list proposals before the guard, so that rule can fail `react` but never `abcde`. In this run it cost `react` no case: it made no harmful-action attempts (0 of 70).
- It does worse on a smaller model. In the model swap, on a smaller model it was not tuned on, the agent's success fell by 25 points (95% CI -45 to -5), and 2 of its 15 all-clear claims were false, against none of 35 on the main exam.
- The agent got more tuning. Beyond the 20 practice cases both tuned on, the agent was also tuned on harder incidents built from practice fault types, one with four faults at once ([decision log](DECISIONS.md), 30 Oct).
- The checker can't see everything. A payment lost silently before the scored window changes neither the verdict nor the handover score ([decision log](DECISIONS.md), 30 Oct).
- "No incident" can skip the checks. If the model dismisses every finding and none shows customers affected, the agent declares "no incident" without the two confirming checks (`ic/agent/abcde.py`).
- The guard's limits are simple. They count per incident, and the guard checks each action and its target, not its parameters (`ic/guard.py`).
- The agent misreads one dispatch signal. Dispatch's integrity counts show the present state, so a count that stays above 0 without growing is a problem that is still there. From its second look on, the frozen agent reads it as past damage ([decision log](DECISIONS.md), dispatch row 1, amendment F7).
- Prompt injection isn't tested. Customer text can reach logs that the model reads, and that attack isn't in the exam.
- Two paths skip the safety check. The manual `run.py act` command and the bank's ops endpoint skip the guard, and the emergency failover doesn't check that the standby is up.
- The keyless demo is a replay. Without a key, the model's answers come from a recorded run. Only the system, the actions and the checks are live.

## Documents

- [Build plan](docs/BUILD-PLAN.md): timetable, roles, go/no-go checks, cut lines and test design
- [Interface contract](docs/CONTRACT.md): how the agent, the test systems, the faults, the checker and the evaluation fit together
- [Dispatch](docs/DISPATCH.md): the transfer system, its facts and its fault channels
- [Adding a system](docs/ADDING-A-SYSTEM.md): how to connect the agent to a system that already runs, or build a new test system on `ic/kit`
- [Decision log](DECISIONS.md)
- [Codex handoff](docs/CODEX-HANDOFF.md): the tasks Codex owns on the Windows laptop
