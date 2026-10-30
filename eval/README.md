# Evaluation harness

This folder runs each arm on a fresh copy of a target system, then asks the
independent checker for the verdict at the same fixed horizon. It does not
read an agent implementation or infer recovery from an arm's own claim.

## File guide

| File | Job |
|---|---|
| `cli.py` | Select cases, arms, models, ports and final-run checks |
| `runner.py` | Start fresh copies, inject faults, enforce deadlines, retain evidence and stop processes |
| `arms.py` | The do-nothing reference and labelled-fix oracle; lazy loading of other arms |
| `storage.py` | Atomic result files, run locks and resuming completed pairs |
| `seals.py` | Check the newest sealed inventory and frozen source hashes |
| `metrics.py` | Score retained evidence and apply case validity rules |
| `stats.py` | Wilson intervals, paired bootstrap, exact McNemar, Holm and Wilcoxon |
| `report.py` | Connect scoring to reports, robustness pairs and the run index |
| `presentation.py`, `plots.py` | Write readable Markdown and three PNG charts |

## Run from the repository root

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-eval.txt
.\.venv\Scripts\python.exe -m pytest tests/eval -q --tb=line
```

After the runbook PR has been merged, a development evaluation can use:

```powershell
.\.venv\Scripts\python.exe run.py eval --split dev --ids dev-01 --arms runbook,noop,oracle --copies 1 --port-bases 8400,8500,8600 --name practice-1
.\.venv\Scripts\python.exe run.py eval --report practice-1
```

AI arms require an explicit model, `IC_MODEL`, or the configured bulk model.
The reference arms and runbook need none. The model-swap condition always uses
the configured swap model and accepts AI arms only.

Use the same run name and arguments to resume. A changed scenario selection,
model, source hash, timing or port configuration is refused under that name.
Use a new name for a changed experiment. Completed original results remain
on disk; an eligible retry is kept in `retry/`, and the oracle's validity
recheck in `oracle-validation/`. Only one retry of each kind is made.
An infrastructure failure during that validity recheck gets one retry under
`oracle-validation/retry/`. Both remain separate from the arm's scored result.
Errored control runs cannot establish a validity exclusion; missing control
evidence leaves the case pending.

The harness prints one line per completed pair. Every run updates
`results/runs.csv`, including partial runs. That file is a raw run ledger;
the report applies validity exclusions. Reports write `report.md`,
`metrics.json`, `summary.json`, `case_success.png`, `user_impact.png` and
`tokens_cost.png` inside the named run. Per-case evidence includes `result.json`
(the arm response), `record.json` (checker, injection manifest and audit),
and copied logs. The harness copies customer logs without reading them.

## Contract 1.2 scoring and interruption

The generic checker supplies harmful-quarantine counts and time to mitigation.
The report puts the censored count and Wilson interval beside the mitigation
mean. A missing harm count makes success unknown only after a successful
quarantine; an allowlist refusal remains harmful regardless of that count.

Must-escalate validity uses only the noop verdict. The oracle is never re-run
for these cases. Fixable cases still need their oracle check. Development
runs that omit both controls retain injection and manifest checks and say
"not validated: no controls in this run". Held-out and transfer runs require
controls. Missing required evidence stays pending.

`--report RUN --against MAIN` pairs robustness cases by source id, system and
arm, and notes differing seeds. Log-format and model-swap conditions inherit
main-run validity; four-fault and extra-service variants need their own controls.
The full held-out report compares label-derived strata with the sealed counts.

An unreachable read is a harness error even when the arm catches it: the
harness retains the guard's `read_error` audit entry and retries once. The
oracle continues the remaining fixes after a failed action, retaining the
failure. Both oracle and runbook send action reasons to the guard.

Ctrl+C stops new work and kills the case processes in flight. Interrupted
pairs get no completed record, and the manifest stays incomplete. Repeating
the same command resumes those pairs as first attempts while preserving
completed pairs.

Every rate retains its numerator, denominator and Wilson interval. Missing
telemetry is unavailable, not zero. Practice, pilot and synthetic fixtures carry
explicit labels. The report states where the scripted runbook ties or wins.
