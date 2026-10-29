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

The harness prints one line per completed pair. Every run updates
`results/runs.csv`, including partial runs. That file is a raw run ledger;
the report applies validity exclusions. Reports write `report.md`,
`metrics.json`, `summary.json`, `case_success.png`, `user_impact.png` and
`tokens_cost.png` inside the named run. Per-case evidence includes `result.json`
(the arm response), `record.json` (checker, injection manifest and audit),
and copied logs. The harness copies customer logs without reading them.

## Measurement limits awaiting contract clarification

[Contract issue #4](https://github.com/Oahsins/HUMAIN-Incident-Commander/issues/4)
records three gaps in version 1.1:

- The generic checker exposes aggregate impact, but no ordered SLO buckets
  from which to calculate time to mitigation. This metric stays unavailable.
- The generic checker has no permitted field for deciding whether a quarantine
  was harmful. Such harm and the affected case-success verdict stay unknown;
  allowlist refusals remain measurable from the guard audit.
- Oracle recovery is intentionally impossible for a must-escalate case, yet
  the validity wording also excludes fault cases after two red oracle runs.
  These cases stay explicitly pending until that rule is clarified.

Missing validity controls are also shown as pending. `--report RUN --against MAIN`
inherits matching source-case validity for log-format and model-swap conditions.
Four-fault and extra-service variants need their own noop/oracle results.
An ABCDE-only transfer run is descriptive and has pending validity under the
current contract. No pending case is silently presented as a valid exam result.

Every rate retains its numerator, denominator and Wilson interval. Missing
telemetry is unavailable, not zero. Practice, pilot and synthetic fixtures carry
explicit labels. The report states where the scripted runbook ties or wins.
