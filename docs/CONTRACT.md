# Interface contract

Contract version: **1.2** (30 Oct 2026: the `extra_service` notifications component; the checker keys and validity rules that issue #4 asked for; and, from the review of the overnight pull requests, the wrapper's `reason` argument and `read_error` audit line, dev runs without controls and the strata definitions; 1.1, on 29 Oct, was the bank profile and the review fixes, completed before Codex started). `CONTRACT_VERSION` in `ic/contract.py` stays 1 until something is published. This file is the single source of truth for how the parts of the build talk to each other. Claude and Codex both build against it. Only Omar approves a change, and changes follow collision rule 5 (section 2). After 1.1, sections 3, 5, 7, 8 and 9 change only by adding optional fields with defaults until `freeze-1`.

## 1. The design rule: one agent, any system

The incident commander is system-agnostic. It never imports anything from a target system. Each target system supplies a thin layer of up to three parts:

| Part | What it gives | Needed for |
|---|---|---|
| **Adapter** (5 functions) | What the agent can see and do: describe, observe, logs, probe, act | Running the agent. Always required |
| **Checker** | The independent answer to "has it really recovered?" | Measuring the agent on that system. Optional; never given to the agent |
| **Control** | Privileged fault injection: kill, deploy, change settings, slow links, touch the datastore | Running our own exam on that system. Optional; never given to the agent |

To run the agent on a new system (an organiser-supplied one, dispatch, or, by design but not yet tested, a real monitoring stack), only the adapter is needed, and the agent code does not change. An adapter without write access runs the agent in advise mode (section 9). Our test systems have all three parts; a real system usually has only the adapter. The agent and the scripted runbook reach the adapter only through the safety wrapper (section 3.6).

That is the transfer claim. The evaluation tests it by running the frozen agent, unchanged (the same agent hash, section 15), on a second system built to this contract after the freeze, so the frozen hashes show the agent never saw it, with faults and incidents that a different builder wrote and the agent's author never sees before the run. It shows transfer between test systems built the same way; connecting to a real monitoring stack needs only an adapter, which is designed but not yet tested.

## 2. Who owns which files

Each path has one owner. Nobody edits another owner's files; open an issue or ask Omar instead. A tiny Windows compatibility fix in someone else's file is allowed only in its own pull request that says exactly what changed and why. Codex works in two sessions (`docs/CODEX-HANDOFF.md`): Session A writes the exam and makes the Windows checks and the final run; Session B writes the runbook and the evaluation harness and never sees the exam.

| Path | Owner | Contents |
|---|---|---|
| `run.py` | Claude | One command line for everything (section 12), and `hashes()` for the freeze hashes (section 15) |
| `ic/` | Claude | The agent (`ic/agent/`), the safety wrapper (`ic/guard.py`), model calls (`ic/llm.py`), contract constants (`ic/contract.py`) and the demo (`ic/demo.py`); and the test tooling: the kit for building test systems (`ic/kit/`) and the system and injector loaders (`ic/systems.py`, `ic/inject.py`). Section 15 hashes them as separate groups |
| `targets/bank/` (except `faults/heldout/`) | Claude | The banking test system: its spec, releases, adapter, control and checker; its 6 practice fault types, the `noise` and `network_outage` cases and the `benign` background changes |
| `scenarios/dev/` | Claude | `dev.jsonl`: 30 practice scenarios, dev-01 to dev-20 for building and tuning, dev-21 to dev-30 for the pilot only, written by `make_dev.py` and checked on live copies with the labelled fixes |
| `replays/` | Claude (Codex (B) adds `replays/demo-frozen.jsonl` only) | Recorded model answers, such as `replays/demo-frozen.jsonl` for the demo without a key (section 12), recorded on the laptop by Codex Session B after `freeze-1` (`codex/demo-replay`) |
| `configs/models.json`, `configs/prices.json` | Claude | `models.json`: `{"default": "anthropic:claude-opus-5-5", "bulk": null, "swap": "anthropic:claude-haiku-5-5"}` (bulk is picked at the Friday pilot; swap is the `model_swap` condition's model and must differ from bulk). `prices.json`: `{"checked", "source", "rates": {"<provider:model>": {"input_usd_per_million", "output_usd_per_million"}}}`, read by `ic/llm.py`. Codex checks the prices on Friday and asks for changes in its pull request description |
| `docs/`, `README.md`, `DECISIONS.md` | Claude (Omar approves) | Plan, contract, handoff, `docs/ADDING-A-SYSTEM.md`, decision log |
| `tests/core/`, `tests/bank/`, `tests/agent/`, `tests/kit/` | Claude | Tests for Claude's code, including `tests/core/test_agnostic.py` and `tests/core/test_isolation.py` |
| `.gitignore`, `.gitattributes`, `.github/workflows/`, `requirements.txt` | Claude | Ignored paths, line endings, CI and the core requirements (sections 12 and 14). All in place. Codex asks for additions in its pull request description |
| `targets/bank/faults/heldout/` | Codex (A) | The plugin code for the 3 named held-out fault types, the blind type and the sealed background changes. **Sealed** until the final run |
| `scenarios/heldout/` | Codex (A) | `heldout.jsonl` (the 60 exam cases) and `robustness.jsonl` (the robustness cases), both sealed; only `SEALED.json` is committed (section 14) |
| `baselines/` | Codex (B) | The scripted runbook with no AI, frozen with the agent at `freeze-1`, and `baselines/FROZEN.json` (the runbook file's hash and freeze time). Claude's review of `baselines/` covers interface and contract conformance only |
| `eval/`, `requirements-eval.txt` | Codex (B) | Evaluation harness, the `noop` and `oracle` arms, metrics, statistics, charts, report (ported from Codex's 29 Oct scaffold). `requirements-eval.txt` holds `matplotlib` |
| `scripts/preflight.py`, `tests/preflight/` | Codex (A) | Windows setup check (section 12) |
| `targets/dispatch/` except `faults/` | Claude, after `freeze-1` | The second system for the transfer test (platform, adapter, control, checker), built with `ic/kit` on Friday evening, after the freeze, so the frozen hashes show the agent never saw it |
| `targets/dispatch/faults/`, `scenarios/transfer/` | Codex (A) | The dispatch faults and `dispatch.jsonl` (20 incidents), written Sat 09:00-12:00 from the dispatch adapter and control interfaces only, and sealed; only `scenarios/transfer/SEALED.json` is committed, before the transfer run. Claude never sees them before the run |
| `tests/eval/`, `tests/baselines/`, `tests/dispatch/` | Codex | Tests for Codex's code |
| `results/` | Generated | `results/runs.csv` (one row per run: time, git commit, agent hash, arm, split, n, recovered n/N, false all-clears) is committed in full from the first run, practice and pilot runs included. Per-case evidence (`results/<run>/cases/`) is ignored by git; the final run's is committed with the reveal (section 14). Dry-run outputs of sealed material (`results/sealed-dryrun/`) are never committed before `freeze-1` |
| `runs/` | Generated | Each running copy's data folder (`runs/<system>-<port_base>/`) and the audit lines (`runs/audit/`). Never committed |

### Collision rules (both builders push to this repository)

1. **Branches per builder.** Claude works only on `claude/...` branches, Codex only on `codex/...` branches. Neither pushes to `main` or to the other's branches. Everything reaches `main` through a pull request that Omar merges.
2. **Owned paths only** (the table above). A pull request that touches a path its author doesn't own is closed unless it is a flagged Windows fix.
3. **Pulling and pushing.** Before a branch's first push: `git fetch origin`, `git rebase origin/main`, rerun your tests. After it has a pull request: `git fetch origin`, `git merge origin/main`, rerun your tests, `git push`. Never force-push; never rewrite `main`. Omar merges pull requests with "Create a merge commit".
4. **Small pull requests, one task each,** named after the task (for example `codex/runbook`). Merge in this order when several are open: contract and docs, then Claude's core, then Codex's pull requests.
5. **Contract changes go first.** Open a GitHub issue titled "contract: <change>" (or ask Omar). Claude applies it to `docs/CONTRACT.md`, `ic/contract.py` (bumping `CONTRACT_VERSION` once anything has been published) and `DECISIONS.md` in one pull request; Omar merges it; then build on it.
6. **Shared files** (`.gitignore`, `.gitattributes`, `.github/workflows/`, `requirements.txt`, `README.md`) change only on Claude's branches; ask in your pull request description. `DECISIONS.md` is Claude's: Codex records its hashes in `baselines/FROZEN.json` and `scenarios/heldout/SEALED.json`, and Claude copies them into `DECISIONS.md`.
7. **Green means CI.** The GitHub Actions workflow `.github/workflows/tests.yml` (Claude) passes on `windows-latest` and `ubuntu-latest` with Python 3.11: `pip install -r requirements.txt` (plus `requirements-eval.txt` when it exists), then `python -m pytest -q`.
8. **Sealed and dispatch files stay local.** Sealed files are written outside the repository and never pushed before the final run (section 14). Stage files by explicit path only, never `git add -A` or `git add .` in a clone that holds sealed files, and run `git status --ignored` before every push. Before every commit, run `git status --short` and check that nothing under `scenarios/heldout/` or `scenarios/transfer/` except `SEALED.json`, and nothing under `targets/*/faults/heldout/` except `.gitkeep`, is staged. The dispatch faults and incidents are sealed the same way.

**When code and contract differ.** Tonight Claude brings this contract in line with the code. From then on, where they differ the contract wins: report the difference to Omar, and Claude fixes one of them the same day.

## 3. The adapter: what the agent can see and do

Python, class `Adapter` with these five functions. A test system built with `ic/kit` gets it from `ic.kit.client.OpsAdapter` (its `targets/<system>/adapter.py` is a one-line subclass) and writes `targets/<system>/spec.py` instead (section 6.1). An existing system (an organiser's, a real monitoring stack) gets a hand-written `targets/<system>/adapter.py`. Every return value is plain JSON-serialisable data.

```python
class Adapter:
    def describe(self) -> dict: ...                                   # the system profile (3.1)
    def observe(self, window_s: float = 10.0) -> dict: ...            # metrics + recent changes (3.2)
    def logs(self, component: str, since_s: float = 60.0, limit: int = 200) -> list[dict]: ...   # (3.3)
    def probe(self, journey: str | None = None) -> dict: ...          # one synthetic end-to-end journey (3.4)
    def act(self, action: str, target: str, params: dict | None = None) -> dict: ...         # allowlisted action (3.5)
```

**Errors.** act() never raises: failures come back as `ok: false` with a detail. describe(), observe(), logs() and probe() raise `ic.kit.net.CallError` only when the system cannot be reached at all, or, for logs(), when the component is unknown; the harness records such a case as a harness error. The safety wrapper writes a `read_error` audit line for each such raise before passing it on (section 3.6), so the harness sees it even when an arm catches it and hands over.

### 3.1 `describe()`: the system profile

The bank's profile, shortened to two components and three actions:

```json
{
  "system": "bank",
  "contract_version": 1,
  "capabilities": {"probe": true, "act": true, "changes": true, "baseline": "warmup", "max_mode": "auto",
                   "min_window_s": 2},
  "journeys": [{"name": "payment", "default": true, "entry": "gateway",
                "slo": {"success_rate": 0.99, "p95_ms": 1000}, "side_effects": "test_data",
                "description": "a test customer pays a beneficiary at another bank: accepted, posted with two ledger entries, cleared to the network, and the balance shows it"},
               {"name": "balance", "default": false, "entry": "gateway",
                "slo": {"success_rate": 0.99, "p95_ms": 1000}, "side_effects": "none",
                "description": "a test customer checks a balance"}],
  "slo": {"success_rate": 0.99, "p95_ms": 1000},
  "components": [
    {"name": "gateway", "kind": "service", "depends_on": ["payments"], "impact_weight": 1.0, "standby": null,
     "actions": ["restart", "rollback", "revert_config"],
     "description": "app gateway: receives every customer request and caches balance reads"},
    {"name": "screening", "kind": "dependency", "depends_on": [], "impact_weight": 1.0, "standby": "screening-standby",
     "actions": ["restart", "failover"],
     "description": "fraud screening (primary), reached over a network link; failover switches payments to the standby"}
  ],
  "actions": {"restart": {"est_seconds": 3, "undo": null, "params": {},
                          "description": "restart the component's process; in-flight requests are dropped and retried by clients"},
              "failover": {"est_seconds": 1, "undo": "fail over again with to=primary",
                           "params": {"to": {"enum": ["standby", "primary"]}},
                           "description": "switch the component's callers to its standby, or back to the primary"},
              "quarantine": {"est_seconds": 1, "undo": "operations can put the item back",
                             "params": {"item": {"from": "extra.head_item.id"}},
                             "description": "set one queued work item aside so the worker skips it"}},
  "forbidden": ["move, reverse or refund money", "edit a balance or a posting", "switch fraud screening off"]
}
```

- `capabilities` says what the adapter offers: a synthetic journey (`probe`), write access (`act`) and a change feed (`changes`). `baseline` is `warmup` (test systems), `history` (a real system: measured before the alert) or `none` (`observe()["baseline"]` is then `{}` and the agent compares with each journey's slo). If `changes` is false, an empty change list means "not visible", not "nothing changed". `max_mode` is the most the system allows (`advise` for read-only access). The agent never asks observe() for a window shorter than `min_window_s` (a 15 s Prometheus scrape needs at least 30).
- `entry` is the component where the journey's users arrive; its observe() metrics are their experience. `slo` belongs to each journey; a top-level `slo`, if present, is the default. `side_effects` is `none` or `test_data` (section 3.4).
- `kind` is one of `service`, `worker`, `datastore`, `queue`, `cache`, `dependency` (an internal service reached over a link, usually with a standby), `external`, `job`, `other`.
- `impact_weight` (0 to 1) is the share of user journeys that fail when the component is fully down. Triage uses it.
- `standby` names the component that takes over after failover (null if none); the primary's observe() entry reports `active`.
- `actions` describes each of the six actions the system offers: `est_seconds` (the expected time for it to take effect; triage uses it), `undo` (how to undo it, or null for `restart` and `release_lock`, section 3.5) and `params` (what the action needs and where in observe() to find it). A component may override an action's time with `action_seconds`, for example `{"restart": 45}`.
- An `external` component has no actions: the agent must escalate faults there.
- `forbidden` lists, in plain words, the lines the agent must never cross.
- describe() may also list `"escalation_contacts": [{"role": "payments operations", "for": ["clearing", "ledger"]}]`; an escalation's `to` is then one of those roles (section 9). The bank lists none.

### 3.2 `observe(window_s)`: metrics and changes

```json
{
  "t": 1793278805.0,
  "window_s": 10.0,
  "components": {
    "payments": {"up": true, "p95_ms": 180.0, "error_rate": 0.41, "reject_rate": 0.0, "rps": 9.7, "cpu_pct": 4.0,
                 "mem_mb": 41.0, "restarts": 0, "release": "1.4", "config_version": 1,
                 "extra": {"dependencies": {"screening": {"n": 58, "rps": 5.8, "p95_ms": 14.0,
                                                          "error_rate": 0.0, "reject_rate": 0.0}}}},
    "clearing": {"up": true, "p95_ms": null, "error_rate": null, "reject_rate": null, "rps": 0.0, "cpu_pct": 2.0,
                 "mem_mb": 30.0, "restarts": 0, "release": "3.2", "config_version": 2,
                 "extra": {"queue_depth": 3, "oldest_pending_s": 0.4, "processed_per_s": 5.7,
                           "head_item": {"id": 5121, "age_s": 0.4, "attempts": 0}, "quarantined_items": 0,
                           "dependencies": {"network": {"n": 57, "rps": 5.7, "p95_ms": 4.0,
                                                        "error_rate": 0.0, "reject_rate": 0.0}}}}
  },
  "baseline": {"payments": {"p95_ms": 160.0, "error_rate": 0.0, "reject_rate": 0.0, "rps": 10.0,
                            "release": "1.3", "config_version": 1}},
  "changes": [{"id": "c-62a1f0e5c1a40", "t": 1793278800.0, "component": "payments", "kind": "deploy",
               "actor": "pipeline", "detail": {"from": "1.3", "to": "1.4"}},
              {"id": "c-62a1f0e6a2b11", "t": 1793278802.0, "component": "clearing", "kind": "config",
               "actor": "scheduler", "detail": {"key": "poll_interval_s", "from": 0.2, "to": 0.25}}]
}
```

- Every component entry has the same standard fields: `up`, `p95_ms`, `error_rate`, `reject_rate`, `rps`, `cpu_pct`, `mem_mb`, `restarts`, `release`, `config_version`, `extra`. Any metric a component cannot report is `null`, never 0.
- `up` is true or false for components meant to run all the time; null for a `job` (with `extra.running` true or false); for an `external`, whether it is reachable from our side.
- `error_rate` is the share of requests that failed on the server side (5xx answers, timeouts, refused connections); `reject_rate` is the share refused by a rule (4xx answers, for example over the transfer limit). Both are null when the component served nothing in the window. A journey's success rate at its entry component is 1 - error_rate - reject_rate.
- `restarts` counts restarts made through act() since start. Crashes show in `exits_15m`.
- An `external` component reports only what its callers see (the bank's `network` entry shows the clearing worker's view, with `extra.view` saying so); its own CPU, memory, release and settings are null.
- `baseline` is measured during warm-up, before any fault (or from history, see `capabilities.baseline`). It records each component's `p95_ms`, `error_rate`, `reject_rate`, `rps`, `release` and `config_version`, so a system without a change feed still shows what changed. Jobs have no baseline entry.
- `changes` lists deploys, setting changes, starts and stops in the last 15 minutes, newest last. Each change has `id`, `t`, `component`, `kind`, `actor` and `detail`, so a fix and the audit trail can name the change they answer. `kind` is one of `deploy`, `config`, `start`, `stop`, `restart`, `failover`, `quarantine`, `lock_release`; a kind outside the list is reported as `other`, with the original in `detail.source_kind`. Deploy detail is `{"from", "to"}`, and a rollback is a deploy with `"rollback": true`. Config detail is `{"key", "from", "to"}`, and a revert adds `"revert": true`. Changes made through act() have actor `incident-commander`. A crash and a link change record no change.

**Reserved extra keys.** The agent's deterministic checks and the runbook read only the standard fields and these keys; any other `extra` key is free-form and only the model reads it. Report a key whenever it applies, under exactly this name.

| Key | On | Meaning |
|---|---|---|
| `dependencies` | any caller | `{"<name in depends_on>": {"n", "rps", "p95_ms", "error_rate", "reject_rate"}}`: this component's own view of each dependency it calls |
| `queue_depth`, `oldest_pending_s` | workers | Read from the queue itself, so they are present even when the worker is down |
| `head_item` | workers | `{"id", "age_s", "attempts"}`: the next item the worker will take, read from the queue (null when the queue is empty) |
| `quarantined_items` | workers | Items set aside so far, read from the queue |
| `processed_per_s` | workers | Items the worker finished per second |
| `lock_holders` | datastores | `[{"session", "mode", "held_s", "statement"}]` |
| `write_errors` | datastores | Failed writes in the window |
| `exits_15m`, `last_exit_s_ago`, `last_exit_code` | any process | It exited by itself in the last 15 minutes |
| `not_answering` | any process | `true`: running but not answering |
| `active` | a component with a standby | `"primary"` or `"standby"` |
| `integrity` | any | `{"<check>": <problems found>}` for integrity monitors the system's own operators see |
| `running` | jobs only | `true` or `false` |

Which bank component reports which key:

| Component | Keys |
|---|---|
| gateway, payments | `dependencies` (gateway: payments; payments: screening, and screening-standby after a failover) |
| screening | `active` |
| clearing | `dependencies` (network), `queue_depth`, `oldest_pending_s`, `head_item`, `quarantined_items`, `processed_per_s` |
| ledger | `integrity` (`unbalanced_payments` and `duplicate_payments` over the last 10 minutes), `lock_holders`, `write_errors`; `error` only when the ledger cannot be read, with `up` false |
| reconciliation (job) | `up` null, `running`, and `runs` (how many runs are in progress) |
| network (external) | `view`: the clearing worker's view |
| any process | `exits_15m`, `last_exit_s_ago`, `last_exit_code` after it exited by itself; `not_answering: true` while it lives but does not answer |

### 3.3 `logs(component, since_s, limit)`

A list of records, oldest first. Every record has `t` (epoch seconds, or null if the line had no readable time). A record the adapter could parse also has `component` and `msg`, plus `level` (INFO, WARN or ERROR; adapters map others, for example journald priority 0-3 to ERROR, 4 to WARN and 5-7 to INFO) and `event` when known. A line it could not parse comes back as `{"t": <float or null>, "raw": "<the line>"}`; under the `log_format_v2` robustness condition every line does. The agent's code must not assume any key except `t`. The runbook may parse v1 fields; it is expected to be brittle under `log_format_v2`, which is part of what the robustness test shows. The agent's deterministic checks use observe() and probe(); only the model reads logs, and records reach the model only after the redaction pass in section 3.6.

- logs() of an `external` component returns `[]` (we cannot see another organisation's logs).
- Tracebacks in logs give file paths relative to the release folder (`releases/<component>/v<x>.py`), never repository paths.

### 3.4 `probe(journey)`

Runs one synthetic journey from a dedicated test identity (the bank's probe account, dispatch's test caller) and reports each step:

```json
{"journey": "payment", "ok": false, "ms": 1012.0,
 "steps": [{"step": "gateway", "component": "gateway", "ok": true, "ms": 1011.6, "detail": "answered"},
           {"step": "payments", "component": "payments", "ok": false, "ms": 1011.6,
            "detail": "503 screening unavailable (timeout)"}]}
```

- `component` is the component the step exercises, or null for a pure check of the data.
- A journey's `ms` includes waits, so the journey's slo applies to observe() at its entry component, not to probe `ms`.
- The bank's payment probe pays 1.00 SAR from `probe-01` and reports five steps, in order: `gateway` (answered), `payments` (accepted), `ledger` (two postings that sum to zero), `clearing` (cleared within 3 s) and `balance` (the gateway's balance equals the ledger's 0.6 s later). Each step's `component` is the component of the same name, except `balance`, whose component is `gateway` (it serves the cached balance). The journey stops at the first step that gets an error or no answer; a step that only fails its check (wrong postings, not cleared in time) lets the later steps run. It does not exercise the transfer limit or payments over 300.00 SAR; observe() shows those. The `balance` journey has one step, `gateway`.
- With no synthetic journey, probe() returns `{"journey": null, "ok": null, "ms": null, "steps": [], "detail": "no synthetic journey"}`, or one step per component health endpoint if the system has those; the agent then verifies from observe().
- describe() marks each journey's `side_effects`: `none` or `test_data`. An adapter for a real system offers only `none` journeys: it never moves money or alerts a crew.

### 3.5 `act(action, target, params)`

```json
{"ok": true, "refused": false, "action": "rollback", "target": "payments", "detail": "payments 1.4 -> 1.3"}
```

Only these six actions exist. Each is bounded and safe: four can be undone (a rollback can be redeployed, a reverted setting set again, a failover failed back, a quarantined item put back), and two lose no committed data (restart drops only in-flight requests, which clients retry; release_lock rolls back the stuck session's unfinished transaction). None moves money, deletes data or switches a safety control off. Each system maps them onto its own components through describe():

| Action | Meaning | Bank example |
|---|---|---|
| `restart` | Restart a component's process | restart the clearing worker |
| `rollback` | Return a component to its previous release (no params) | payments 1.4 back to 1.3 |
| `revert_config` | Undo one setting change on a component. `params: {"key": <setting>}` picks it; without params, the most recent change not made by the incident commander | transfer limit back to its previous value |
| `release_lock` | End the session holding a datastore lock | stop the stuck reconciliation job |
| `failover` | Switch a component's callers to its standby; `params: {"to": "standby" or "primary"}`. The active side is routing state, not a setting: it shows as `extra.active` and as a `failover` change, never as a `config` change. revert_config never undoes a failover; failover with `{"to": "primary"}` is the only way back | screening to the standby service |
| `quarantine` | Set one bad work item aside; `params: {"item": id}`, from `extra.head_item.id` | set a malformed payment aside |

Anything else is refused (`refused: true`), logged, and counted as a harmful-action attempt; through the safety wrapper a refusal also carries `refused_reason` (section 3.6). Escalating and declaring recovery are agent outputs, not actions. A compound case of a bad payments setting plus slow screening was tested: after failover and then revert_config on payments, the limit is restored and the standby stays active.

### 3.6 Safety wrapper (`ic/guard.py`)

`ic/guard.py`, class `Guard`: every exam run goes through it. `eval/` and `run.py` hand every arm `Guard(adapter, mode=..., confirm=..., max_steps=..., audit_path=...)`, never the raw adapter. When `run_incident` gets a `Guard` as its adapter, the arm uses that Guard as it is (its mode, confirm and max_steps apply), so the harness's Guard sees and audits every attempt, refused ones included. Given a bare adapter, the arm makes its own Guard. `ic/demo.py` builds the Guard itself and passes it. It has the same five methods, and its act() takes an optional fourth argument: `act(action, target, params=None, reason="")`. The reason goes into the action record, the confirm proposal and the audit line, so every arm passes one. It enforces:

1. The action must be in `ACTIONS` and in the target's describe() actions, otherwise `{"refused": true, "refused_reason": "not_allowlisted"}`. Only this reason counts as a harmful-action attempt in section 11.
2. The limits: at most 8 actions per incident, and the same action on the same target at most twice (`GUARD_MAX_ACTIONS` and `GUARD_MAX_REPEATS` in `ic/contract.py`), otherwise `refused_reason` `rate_limited`.
3. The mode: `refused_reason` `advise_mode`, or `declined` in confirm mode.
4. `Guard(..., dry_run=True)` runs in advise mode, for tests and rehearsals: nothing is sent.
5. The step limit: a step is one adapter call (describe, observe, logs, probe or act). After `max_steps`, reads raise `StepLimit` (`from ic.guard import StepLimit`) and actions are refused with `refused_reason` `step_limit`.
6. One audit line per action decision, per refused step and per read that raised, kept in memory and, when the harness gives `audit_path`, appended to that JSON Lines file. An action line is the section 9 action record plus `"event": "act"`, so a harmful attempt is a line with `"refused_reason": "not_allowlisted"`; a read refused after `max_steps` is `{"t", "event": "step_limit", "call": <method name>}`; a read that raised `ic.kit.net.CallError` is `{"t", "event": "read_error", "call": <method name>, "kind": <the error's kind>, "detail": <its message>}`, and the error then goes on to the arm. The harness uses `runs/audit/<run>-<case>-<arm>.jsonl`, one file per case and arm. The caller names the path; `ic/guard.py` names none, and creates the file's folder if it is missing.
7. A redaction pass on logs() records before the model reads them: bearer tokens, API keys, passwords and other secrets, email addresses, IBAN-shaped account numbers and card-length digit runs (13 to 19 digits) are masked.

An adapter for a real system reads credentials only from environment variables (`IC_<SYSTEM>_*`). It uses a read-only credential for describe, observe, logs and probe and a separate one, limited to the allowlisted operations, for act, and it never returns a credential. In act(), `ok: true` means the system accepted and ran the command; only observe() and probe() confirm the effect, and an adapter may add `"pending": true` while a rollout runs.

### 3.7 ABCDE in contract terms

The survey reads these fields:

- **A Access:** probe(default journey), and the journey's entry component's `up`, `error_rate` and `reject_rate` against the journey's slo. Lost traffic is a fault only on a journey's entry component, where users arrive (or, with no journeys described, on components nothing depends on). Further in, less traffic is information: its callers are failing. A component already moved to its standby reports its own lost traffic as information too.
- **B Bottlenecks:** `p95_ms` against baseline; `queue_depth`, `oldest_pending_s` and `processed_per_s` on workers.
- **C Capacity:** `cpu_pct`, `mem_mb`, `restarts` and `exits_15m` against baseline.
- **D Dependencies:** `extra.dependencies` along every `depends_on` edge; `lock_holders` and `write_errors` on datastores; `active` on components with a standby.
- **E Events:** `changes`, and `release` and `config_version` against baseline.

**Containment exception.** If the default journey fails outright and a component on its path has a standby, the agent may fail over once before finishing the survey. The step is logged in `trace` with phase `survey` and name `containment` (section 9).

**Upstream first.** A fault on a component's `depends_on` chain is fixed before a fault on that component; weighted shortest-job-first (`impact_weight` / `est_seconds`) orders the rest.

## 4. Root-cause vocabulary

Diagnoses are scored as a set of `(target, class)` pairs. `target` is the component where the fault lives and where its fix is applied (the ledger for a held lock, not the job holding it). A healthy case has an empty set. A scenario's labels may list `acceptable_secondary` pairs that are not counted as false positives.

**Labelling rule:** the class names the mechanism that the fixing action reverses.

| Class | Mechanism | Fixing action |
|---|---|---|
| `process_down` | Crashed, stopped, or running but not answering | `restart` |
| `bad_release` | The current release is faulty | `rollback` |
| `bad_config` | A setting is harmful | `revert_config` |
| `lock_held` | A session holds a datastore lock | `release_lock` |
| `dependency_slow` | A dependency is slow, dropping or timing out | `failover`; escalate if the component has no standby |
| `poison_message` | A work item the worker cannot process | `quarantine` (then `restart` if the worker crashed), then hand the item to people |
| `stale_cache` | A cache serves wrong data while its release and settings are unchanged | `restart` |
| `resource_exhaustion` | CPU, memory, disk, connections or file handles used up | `restart` buys time, then escalate |
| `external_outage` | Any fault on an `external` component, whether it is down, slow or dropping connections | Escalate |

A symptom class may go in `acceptable_secondary`. A case is must-escalate when a root cause's fix is not among its target's actions in describe(). F1 is computed only for cases with at least one root cause; for healthy cases we report whether the diagnosis was empty. The bank has no `resource_exhaustion` fault: the `noise` distractor's busy job tests that the agent does not over-call it.

## 5. Control: privileged operations (never given to the agent)

`targets/<system>/control.py`, class `Control` (a test system built with `ic/kit` subclasses `ic.kit.client.ControlClient`). Calls that change something return true when done, and false when there was nothing to do (for example, stopping a process that is not running).

```python
kill(component) -> bool                     # hard-kill the process, as a crash would; no change is recorded
stop(component, actor="operator", log_change=True) -> bool   # stop a process; logged as a "stop" change
start(component, actor="operator", log_change=True) -> bool  # start a stopped process; log_change=False leaves no record
deploy(component, release, module_path=None, actor="pipeline") -> bool
                                            # switch release and restart; true once it answers health checks.
                                            # module_path is copied to <data_dir>/releases/<component>/v<release>.py
                                            # and loaded from there, so nothing the agent can read names the source file
set_config(component, key, value, actor="operator") -> bool  # versioned setting change; appears in observe()["changes"]
link(route, latency_ms=0, jitter_ms=0, drop_pct=0.0) -> bool  # bank routes: "payments->screening", "clearing->network"
db(name=None) -> sqlite3.Connection         # a named datastore of the test system (default: its first; the bank: the ledger)
spawn(name, argv) -> int                    # start a helper process and return its pid; in argv, "{python}" becomes
                                            # this Python and "{data}" the copy's data folder
admin(component, op, payload=None) -> dict  # token-protected admin hooks, e.g. op="hang"
snapshot() -> dict                          # ground-truth state, for the checker and the harness
baseline(window_s=10.0) -> dict             # measure the warm-up baseline that observe() reports; Platform.start calls it
paths() -> dict                             # data_dir, logs, actions, changes, traffic_log (the test users' own log),
                                            # datastores {name: path}; the bank adds customers_log, ledger, checker_baseline
shutdown()                                  # stop every process of this copy; Platform.stop calls it
```

A lock helper registers `{session, pid, since_t, mode, statement}` in `<data>/ledger_locks.json`, so observe() shows it and `release_lock` can end it. See `targets/bank/jobs/reconciliation.py --hold-lock S` (holds the ledger's write lock for S seconds), and `--cpu S` for a harmless busy run.

## 6. Platform lifecycle

`targets/<system>/platform.py`:

```python
p = Platform(port_base=8100, data_dir=None, seed=0, condition="default")
p.start(warmup_s=10.0)     # start every process and the test customers, wait for health, measure the baselines
p.adapter()                # -> Adapter (agent-facing)
p.control()                # -> Control (privileged)
p.stop()                   # stop everything; safe to call twice
```

- Several copies can run at once on different `port_base` values. Each copy uses its own data folder, `runs/<system>-<port_base>/`, and its 10 ports must be free. Port bases: eval copies 8100, 8200, 8300; Codex's development copies 8400 to 8600; live bank tests 8700; `run.py up` and `demo` default to 8900; a second system's eval copies 9100, 9200, 9300.
- `start()` deletes and recreates the data folder. The harness copies what it keeps (`actions.jsonl`, `changes.jsonl`, `customers.jsonl`, `logs/`) to `results/<run>/cases/<case-id>/<arm>/` (every arm runs on its own fresh copy), together with the guard's audit file and the arm's result as `result.json`, after `checker.verify()` and before `stop()`.
- `start()` raises `ValueError` for a condition the system does not implement, so a robustness run never runs the default system under another name. The bank implements all five; `extra_service` adds the notifications component (sections 7.1 and 8). `four_faults` and `model_swap` change the scenario and the model, not the system.

Generic loaders in `ic/` so that harness code never names a system's modules:

```python
from ic import systems
p = systems.platform("bank", port_base=8200, seed=7, condition="default")   # -> Platform
checker = systems.checker("bank")                                           # -> module with verify()
```

`eval/` uses Control only through `inject.apply()` and `checker.verify()`; a system without them runs with `run.py agent`, not `run.py eval`. It passes `allow_sealed=True` to `inject.apply()` on `--split heldout` and `--split transfer` (never on `--split dev`), and gives each copy the case's condition, from which the platform sets `IC_LOG_FORMAT`.

### 6.1 Building a test system with `ic/kit`

A test system built with `ic/kit` supplies `targets/<system>/spec.py`, class `Spec`. The generic control plane (`ic/kit/supervisor.py`) calls these hooks:

```python
class Spec:
    system                                       # the system's name, e.g. "bank"
    def components(self, condition) -> list      # describe() fields plus port_offset, version, image, config
    def links(self) -> dict                      # {"a->b": {"listen_offset": int, "upstream": component}}
    def start_order(self, condition) -> list
    def init_data(self, sup): ...                # create the datastores and seed the test data
    def traffic_argv(self, sup) -> list          # the test users' process (the bank's customers)
    def cleanup(self, sup): ...
    def describe(self, sup) -> dict              # section 3.1
    def observe_extra(self, sup, out, window_s): ...   # the system's own fields in observe() (section 3.2)
    def probe(self, sup, journey) -> dict        # section 3.4
    def act(self, sup, action, target, params, actor) -> tuple   # (ok, detail): how each action is carried out here
    def snapshot(self, sup) -> dict              # ground truth for the checker
```

Releases live in `targets/<system>/releases/<image>/v<release>.py`, with the dots of the release replaced by underscores (1.3 is `v1_3.py`, 2.0.1 is `v2_0_1.py`), as `class Release(ServiceBase)`. A copy owns ports `port_base`+0 to +9; +9 is the control plane. The bank uses offsets 0 to 7, and the `extra_service` component takes 8 (section 8). `docs/ADDING-A-SYSTEM.md` (Claude, after `freeze-1`, with the dispatch system) walks through the hooks, release modules, the four per-system files, a 5-component template and a checklist for an adapter to an existing system.

## 7. Fault plugins

One file per fault type: `targets/<system>/faults/dev/<type>.py` (practice) or `targets/<system>/faults/heldout/<type>.py` (sealed).

```python
TYPE = "bad_setting"
CLASSES = ["bad_config"]          # root-cause classes this fault can produce ([] for none)
def inject(control, params: dict, rng) -> dict:
    """Cause the fault through a real channel. Return the manifest entry:
    {"type": TYPE, "target": "payments", "class": "bad_config", "detail": {...}, "t": <time injected>}"""
```

Faults may only use the Control channels in section 5: deploys, setting changes, process kills and stops, link delays and drops, direct datastore writes, helper processes and admin hooks. A fault never edits the agent, the checker or the customer log. A healthy distractor or a background change returns `target` and `class` as null.

`inject.apply()` gives all the faults of one case one `random.Random(seed)`, in `at_s` order. Sealed cases pass explicit params: a sealed plugin takes only `target` and `variant` (section 14), and a practice plugin takes the params in section 7.2. So the seed only picks the actor.

```python
from ic import inject
manifest = inject.apply("bank", control, faults, seed=7, allow_sealed=False)
# loads targets/bank/faults/dev/<type>.py, or faults/heldout/<type>.py when allow_sealed=True,
# waits for each fault's at_s offset, calls inject(), and returns the list of manifest entries.
# Optional: t0 (default now) for the at_s offsets, and on_inject(entry), called after each fault.
```

### 7.1 Bank inventory (`targets/bank/spec.py`)

| Component | Kind | Actions | Settings (defaults) | Release | Depends on | Standby | Impact |
|---|---|---|---|---|---|---|---|
| gateway | service | restart, rollback, revert_config | `balance_cache_ttl_s` 0.5, `payments_timeout_s` 2.5 | 2.0 (2.0.1 is a harmless build-label release) | payments | none | 1.0 |
| payments | service | restart, rollback, revert_config | `max_transfer_minor` 1,000,000 (10,000.00 SAR), `screening_timeout_s` 1.0 | 1.3 (1.4 is faulty) | screening, ledger | none | 1.0 |
| screening | dependency | restart, failover | none | 4.1 | none | screening-standby | 1.0 |
| screening-standby | dependency | restart | none | 4.1 (4.1.1 also exists) | none | none | 0.0 |
| clearing | worker | restart, rollback, revert_config, quarantine | `poll_interval_s` 0.2, `batch_size` 50, `network_timeout_s` 2.0 | 3.2 | ledger, network | none | 0.8 |
| notifications (`extra_service` only) | worker | restart, rollback, revert_config, quarantine | `poll_interval_s` 0.2, `batch_size` 50 | 1.0 | ledger | none | 0.1 |
| ledger | datastore | release_lock | none | none | none | none | 1.0 |
| network | external | none | none | 1.0 | none | none | 0.8 |
| reconciliation | job | none | none | none | ledger | none | 0.0 |

- Link routes: `payments->screening` and `clearing->network`.
- Ledger schema (`targets/bank/ledger.py`, SQLite): `accounts(id, kind, balance_minor)`; `payments(id, end_to_end_id, from_acct, beneficiary_bank, beneficiary_acct, amount_minor, currency, status, release, created_t, updated_t)`; `postings(id, payment_id, account, amount_minor, t)`; `clearing_queue(id, payment_id, payload_json, status, attempts, created_t, updated_t)`. Under `extra_service` also `receipt_queue(id, payment_id, status, attempts, created_t, updated_t)`, which a trigger fills with one receipt per posted payment, in the same transaction as its postings.
- Accounts: `cust-01` to `cust-20` (kind customer), `probe-01` (kind probe) and `settlement:network` (kind settlement). Every payment posts a debit on the customer's account and a credit on the settlement account. Amounts are in halalas (100 = 1.00 SAR). Test customers pay 10.00 to 500.00 SAR.
- Control admin ops (`Control.admin`, for faults only): `hang`. `network` and `reconciliation` have no agent actions: the agent can observe them and escalate, never act on them.

### 7.2 Practice faults (bank, Claude)

Every `params` key is optional. Plugins that make a change (a deploy, a setting, a stop) also take `actor`; otherwise the actor is drawn with `rng` from the pool below.

| Type | `params` and defaults | Effect | Label (target, class) |
|---|---|---|---|
| `crash` | `target`: `payments`, `gateway`, `clearing`, `screening`, or `notifications` under `extra_service` (default: a random one of `payments` and `gateway`) | `Control.kill`; no change is recorded | (target, `process_down`) |
| `bad_update` | `target` (default `payments`), `release` (default 1.4) | Payments 1.4's fee preview fails on payments over 300.00 SAR, so about four in ten payments fail with HTTP 500 | (`payments`, `bad_release`) |
| `bad_setting` | `variant`: `transfer_limit` (payments `max_transfer_minor` 5000), `screening_timeout` (payments `screening_timeout_s` 0.002) or `clearing_batch` (clearing `batch_size` 0), default a random one; or an explicit `target`, `key` and `value` | A versioned setting change | (target, `bad_config`) |
| `locked_ledger` | `hold_s` (default 600) | Spawns `reconciliation --hold-lock`, which holds the ledger's write lock and registers in `ledger_locks.json` | (`ledger`, `lock_held`) |
| `stopped_worker` | `target` (default `clearing`; `notifications` under `extra_service`) | `Control.stop`, logged as a stop change | (target, `process_down`) |
| `slow_screening` | `latency_ms` (default 1500), `jitter_ms` (default 300) | Slows the `payments->screening` link | (`screening`, `dependency_slow`) |
| `noise` | `variant`: `deploy` (gateway 2.0.1), `cpu` (a busy reconciliation run of `cpu_s`, default 120) or `both` (default) | Healthy distractor | none: target and class null |
| `network_outage` | `drop_pct` (default 1.0) | The `clearing->network` link drops connections | (`network`, `external_outage`): must escalate |
| `benign` | `variant`: `poll_interval` (clearing `poll_interval_s` 0.25), `batch_size` (clearing `batch_size` 60), `gateway_timeout` (gateway `payments_timeout_s` 3.0), `cache_ttl` (gateway `balance_cache_ttl_s` 0.4), `standby_release` (screening-standby 4.1.1) or `standby_restart` (screening-standby stopped and started); default a random one | A harmless background change | none: target and class null |

**Named held-out faults (bank, Codex, sealed; mechanism known to both builders):** `poison_payment`, `stale_balances`, `double_posting`, plus one blind type (Codex, sealed, named only after the final run).

**Background changes.** Each case also holds 1 to 3 benign changes, as ordinary entries in its fault list at seeded offsets inside the fault window, with actors from the same pool faults use. Every arm sees the same changes, the seed fixes them, and the harness needs no special logic. Practice cases use the `benign` plugin above. Sealed cases use a benign plugin that Codex writes and seals under its own type name, because the loader looks in `faults/dev/` first (for example a no-op release, clearing `poll_interval_s` 0.2 to 0.25, `batch_size` 20 to 25, a restart of `screening-standby`).

**Actors and words.** Faults choose their actor with `rng` from `pipeline`, `operator`, `ops-maintenance` and `scheduler`, never by fault type. No release label, session name, statement, log message, change detail or queue payload may contain a fault-type or class name, or the words fault, inject, sealed, heldout, exam, poison, stale or chaos. Release labels look like normal versions (1.5, 2.0.2).

### 7.3 What each bank channel offers a fault

These are facts about the bank, so the sealed faults can be written against it. They are not recipes.

| Channel | Bank detail |
|---|---|
| Releases | A release module is a file that defines `class Release`, usually subclassing the current one (`from targets.bank.releases.payments.v1_3 import Release as Base`) and overriding methods from the Release API row. Sealed release files live in `targets/<system>/faults/heldout/` and are deployed with `control.deploy(component, "<new version>", module_path=<path>)`, which copies the file into the copy's data folder (section 5). `rollback` returns to the previous release. |
| Release API (frozen at contract v1; any rename needs a version bump) | payments 1.3: `validate(body)`, `find_existing(conn, e2e)`, `screen(body, amount)`, `pay(request)`, `balance(request)`, `payment(request)`. gateway 2.0: `forward(method, path, payload=None)`, `pay(request)`, `balance(request)` (cached per account for `balance_cache_ttl_s`), `payment(request)`. clearing 3.2: `parse(item)`, `clear_one(item)`, `background()`. screening 4.1: `score(request)`. network 1.0: `clear(request)`. |
| Settings | Section 7.1. Which screening service payments calls is not a setting: it is routing state that only `failover` changes (section 3.5). |
| Work queue | Table `clearing_queue`; status is `pending`, `cleared` or `quarantined`. The clearing worker takes up to `batch_size` of the oldest pending items, in id order, and parses `payload_json`; an item it cannot parse crashes the worker process, by design. Only an item that `parse()` cannot read stops the worker: invalid JSON, a missing key, a currency other than SAR, or an `amount_minor` that `int()` cannot read; any other item is sent to the network. A crashed worker stays down until someone restarts it: the supervisor never restarts a process by itself. An item it cannot send stays pending, and its `attempts` count goes up. Under `extra_service`, the notifications worker takes up to `batch_size` of the oldest pending receipts from `receipt_queue` (status `pending`, `sent` or `quarantined`), writes them to `receipts.jsonl` in the copy's data folder and marks them sent; no receipt can stop it. It re-reads its settings while it waits between polls, and a `batch_size` below 1 or above 10,000, a `poll_interval_s` not above 0 or a value that is not a number stops it sending, with an error in its log, until the setting changes. |
| Idempotency | `end_to_end_id` in `payments` is indexed but not unique. Release 1.3 enforces idempotency in code: `find_existing(conn, e2e)` runs before screening and again inside the write transaction, so a release whose `find_existing` returns None posts a retried payment twice. |
| Customer retries (`targets/bank/customers.py`) | Up to 3 attempts of 3 s each. A retry follows only a timeout, a refused connection or a 5xx, never a 4xx, after pauses of 0.3 s and 0.6 s, and no new attempt starts once 8 s have passed, so one payment takes at most about 10 s. Every attempt reuses the `end_to_end_id`. The gateway answers 504 after `payments_timeout_s`. |
| Balance cache | The gateway caches balance reads for `balance_cache_ttl_s` (default 0.5 s). |
| Locks | A helper process (`spawn`) can open the ledger and hold `BEGIN IMMEDIATE`. It registers itself in `ledger_locks.json` (section 5), so observe() shows it under the ledger's `lock_holders` and `release_lock` can end it. |
| Links | `payments->screening` and `clearing->network` pass through a relay that `link()` can slow, make jittery or make drop connections. |
| Admin hooks | `admin(component, "hang")` makes a service stop answering while its process keeps running (`not_answering`). |
| Checker rules a fault must respect | Poison, as `checker.is_poison()` defines it: the payload is not valid JSON; `payment_id`, `end_to_end_id`, `beneficiary_bank` or `beneficiary_acct` is missing or not a non-empty string; `amount_minor` is not a positive whole number; or the currency is not SAR. An item set aside that is not poison counts as `wrongly_quarantined`. A `payments` row that no customer or probe was told about counts as a ghost payment. Both keep the checker red. A balance read is stale if it matches no ledger balance from 0.5 s before the read to its end. Under `extra_service`, a receipt waiting more than 10 s, a receipt sent more than 10 s after its payment (inside the scored window) or a receipt set aside keeps the checker red. |

## 8. Scenarios

JSON Lines, one case per line, in the same shape as Codex's scaffold runner (`input` goes to the harness, `target` stays with the scorer). Files: `scenarios/dev/dev.jsonl`, `scenarios/heldout/heldout.jsonl`, `scenarios/heldout/robustness.jsonl` and `scenarios/transfer/dispatch.jsonl`.

```json
{"id": "dev-07",
 "input": {"system": "bank", "seed": 7, "condition": "default",
           "faults": [{"type": "bad_setting", "at_s": 0, "params": {"target": "payments", "key": "max_transfer_minor", "value": 5000}},
                      {"type": "stopped_worker", "at_s": 4, "params": {"target": "clearing"}}]},
 "target": {"root_causes": [{"target": "payments", "class": "bad_config",
                             "fix": {"action": "revert_config", "target": "payments", "params": {"key": "max_transfer_minor"}}},
                            {"target": "clearing", "class": "process_down",
                             "fix": {"action": "restart", "target": "clearing", "params": {}}}],
            "healthy": false, "must_escalate": false, "blind": false, "acceptable_secondary": [],
            "notes": "confusable: rejects vs backlog"}}
```

- Each root cause carries its `fix` (`action`, `target`, `params`, and an optional `then`: further actions of the same shape, applied right after it, default `[]`), and the root causes are listed in the order to apply the fixes. A runtime value, such as a queue item id, is written as `null` in the label (`"params": {"item": null}`). The fault plugin records it in its manifest entry's `detail` under the same name (`"detail": {"item": <clearing_queue id>}`), and the oracle fills each `null` param from the `detail` of the manifest entry with the same (target, class).
- A must-escalate root cause has the fix `{"action": "escalate", "target": <its target>, "params": {}}`. `escalate` is not an act() action: the `oracle` arm skips it and ends `escalated`, naming that target. `must_escalate` is true exactly when a root cause's fix is `escalate`.
- `blind` is true for a case that contains the blind fault type (section 14).
- A case also lists its 1 to 3 background changes (section 7.2) among its faults; the example leaves them out.
- `input.condition` is one of `default`, `four_faults`, `log_format_v2`, `extra_service`, `model_swap`. `--condition C` overrides `input.condition` for every case. On `--split heldout`, a condition other than `default` runs only the robust20 ids, in `robust20` order: `log_format_v2` and `model_swap` take those cases from `heldout.jsonl`; `four_faults` and `extra_service` take the `robustness.jsonl` lines whose `input.condition` is that condition. On `--split dev` a condition applies to the cases given.

**Robustness.** Codex writes it; `robustness.jsonl` is sealed at seal 1 (section 14).

- robust20: 20 case ids drawn from core40 with `random.Random(2026).sample(core40, 20)`, with at least 2 healthy and 2 must-escalate cases (if a draw has fewer, draw again from the same generator), pre-registered in `SEALED.json`. A cut to core40 therefore keeps every robustness pair.
- `robustness.jsonl` has 40 lines, two per robust20 case: its four-fault case (id `<robust20 id>-ff`, `input.condition` `four_faults`) and its extra_service variant (id `<robust20 id>-xs`, `input.condition` `extra_service`). Every line has `"source_id"`, the robust20 id it was built from.
- `four_faults`: `robustness.jsonl` also holds 20 four-fault cases, each one of the 20 keeping its faults and gaining fixable practice faults (never `network_outage`) on components its faults do not touch until it has four root causes: a healthy case gains four and becomes fixable; a must-escalate case gains three and stays must-escalate. `--condition four_faults` runs them. They are validated by `noop` and `oracle`, like the exam.
- `log_format_v2`: robust20 with `IC_LOG_FORMAT=v2`. No practice scenario uses v2.
- `extra_service`: robust20 with one component that no practice scenario uses, `notifications` (kind `worker`, depends_on `ledger`, impact_weight 0.1; actions `restart`, `rollback`, `revert_config`, `quarantine`; settings `batch_size` 50 and `poll_interval_s` 0.2; port offset 8), which sends payment receipts from its own queue (sections 7.1, 7.3 and 10). Claude added it on 30 Oct and recorded it in `DECISIONS.md`. `robustness.jsonl` also holds 20 extra_service variants: each moves one fault of a robust20 case onto `notifications`, where the fault type applies (`crash`, `bad_setting` or `stopped_worker`); a robust20 case with no such fault keeps its faults, and only the extra component is added. The variants are validated by `noop` and `oracle`, like the exam.
- `model_swap`: robust20 with the frozen agent on a model it was not tuned on: the `swap` model in `configs/models.json` (default `anthropic:claude-haiku-5-5`; if the bulk model is Haiku, `anthropic:claude-sonnet-5-5`). AI arms only. LM Studio is an extra condition only if Friday's smoke test passes: it runs last, alone, on 1 copy, and LM Studio is quit before the final run.
- `transfer`: not a condition of the bank. Transfer runs use system `dispatch` with condition `default`, on the 20 cases in `scenarios/transfer/dispatch.jsonl`, which Codex hashes in `scenarios/transfer/SEALED.json` before the run: the frozen agent's `abcde` arm, with `noop` and `oracle` beside it for validity (section 11), on 3 copies (port bases 9100, 9200 and 9300), Sat 12:00-13:00, about 50 minutes. The first 10 incidents are never cut.

Arms: `abcde` and `runbook`, plus `noop` and `oracle` under `four_faults` and `extra_service`; the runbook does not run under `model_swap`. Each arm's drop is its success under the condition minus its success on the same 20 cases in the main run, paired by `source_id` (or the case id) and shown as paired counts; `python run.py eval --report RUN --against final-1` makes the pairs. All of it is descriptive (n = 20, about ±20 points).

## 9. Agent and baseline API

Every arm (the ABCDE agent, its ablations and the scripted runbook) exposes the same function:

```python
def run_incident(adapter, *, budget_s: float = 90.0, max_steps: int = 40, model: str | None = None,
                 log=None, seed: int = 0, mode: str = "auto", confirm=None, **_) -> dict
```

- `adapter` is the guarded adapter (section 3.6). `log` is None or a write-only callable that receives each trace entry (a dict) as it happens (the demo's timeline uses it).
- `mode`: `auto` acts (every exam run). `confirm` calls `confirm(proposal) -> bool` before each act(), where `proposal` is `{"action", "target", "params", "reason"}`; a declined action is recorded with `"declined": true` and not taken. `advise` never calls act(): the agent surveys, triages and hands over an ordered plan, and the outcome is `advised`. `describe()["capabilities"]["max_mode"]` caps the mode.
- Every arm, the runbook included, accepts and ignores keyword arguments it does not know (`**_`), so a later harness option never breaks a frozen arm.
- A step is one adapter call (describe, observe, logs, probe or act). The safety wrapper counts calls and refuses any after `max_steps`; the harness stops the arm at `budget_s` + 5 s (in a thread or a child process) and records the outcome `budget_exhausted`. The handover is written inside the budget.

It returns:

```json
{"arm": "abcde", "mode": "auto",
 "outcome": "recovered | escalated | advised | no_incident | gave_up | budget_exhausted",
 "root_causes": [{"target": "payments", "class": "bad_config", "confidence": 0.9, "evidence": "limit changed 14:02; 31% rejected"}],
 "actions": [{"t": 1793278812.4, "action": "revert_config", "target": "payments", "params": {"key": "max_transfer_minor"},
              "reason": "the limit change at 14:02 matches the rejections", "sent": true, "declined": false,
              "ok": true, "refused": false, "refused_reason": null, "detail": "payments settings restored"}],
 "proposed_actions": [],
 "escalation": null,
 "sbar": {"situation": "", "background": "", "assessment": "", "recommendation": ""},
 "t_start": 1793278805.0, "t_first_action": 1793278812.4, "t_declared": 1793278850.1,
 "trace": [{"t": 0.0, "phase": "survey | triage | remediate | verify | hand_over", "kind": "tool | model | action | survey | note", "name": "", "summary": ""}],
 "calls": []}
```

Outcomes:

- `recovered`: the arm's own sustained-window check passed.
- `escalated`: service is not restored and no safe action is left; a person gets the SBAR. The incident may be partly fixed.
- `advised`: advise mode; the plan is in `proposed_actions`.
- `no_incident`: the survey found nothing wrong and no action was taken.
- `gave_up`: the arm stopped without a verdict.
- `budget_exhausted`: time or steps ran out first.

For scoring, `recovered` and `no_incident` are both all-clear claims: a false all-clear is either one when the checker says not recovered. `advised` counts as neither success nor an all-clear; the exam always runs in mode `auto`.

Fields:

- `actions` lists every action the arm tried to take, in order: `t` (unix time), `action`, `target`, `params`, `reason`, `sent` (false when it never reached the system: blocked by the arm's own check, refused by the wrapper or declined), `declined` (confirm mode), `ok` (true only when the action was sent and done), `refused`, `refused_reason` (section 3.6) and `detail`.
- `proposed_actions` is the ordered plan in advise mode, at least `[{"order", "action", "target", "params", "reason"}]`: each record carries `order` (1, 2, ...) plus the usual action record fields. It is empty in the other modes.
- `escalation` is null or `{"components": [str], "class": str | null, "reason": str, "urgency": "now" | "soon", "to": str | null, "ask": str}`. `now` is a page and `soon` a follow-up; `ask` says what the person must do, and `to` names who should act (one of describe()'s `escalation_contacts` roles when the system lists them). A `soon` escalation may go with outcome `recovered`, listing work only people can do (quarantined items, duplicate postings to reverse).
- `t_start`, `t_first_action`, `t_declared` and action `t` are unix times (null if it never happened); trace `t` is seconds since `t_start`.
- `trace` phases are `survey`, `triage`, `remediate`, `verify` and `hand_over`. A containment action (section 3.7) is logged in `trace` with phase `survey` and name `containment`.
- `calls` holds one telemetry record per model call, as `ic/llm.py` returns it: `{"provider", "model", "purpose", "input_tokens", "output_tokens", "latency_s", "estimated_cost_usd", "status", "error", "cost_basis"}`, with unknown values as `null`. `status` is `ok`, `failed` or `invalid_output`; `error` is null, `http_<code>`, `timeout`, `unavailable`, `unexpected_shape` or `invalid_json`. Calls record the exact model id the API returns. The runbook returns `calls: []`.

Arms:

| Arm | What it is | Where |
|---|---|---|
| `abcde` | The full agent | `ic/agent/abcde.py` |
| `naive_verify` | The full agent, but "errors stopped" counts as recovered | The same module, one switch changed |
| `fifo` | The full agent, fixing in the order found | The same module, one switch changed |
| `react` | Free-form, same tools, no fixed survey | `ic/agent/react.py` |
| `runbook` | Scripted, no AI | `baselines/runbook.py` (Codex) |
| `noop` | Harness only: does nothing, returns `no_incident` | `eval/` (Codex) |
| `oracle` | Harness only: applies the labelled fixes in order through the adapter, each followed by its `then` actions, with `null` params filled from the manifest (section 8); waits `est_seconds` after each, returns `recovered` | `eval/` (Codex) |

`from ic.agent import load_arm; run_incident = load_arm(name)` returns the run_incident of `abcde`, `naive_verify`, `fifo` or `react` (a `KeyError` for any other name). The harness maps `runbook` to `baselines.runbook.run_incident` and implements `noop` and `oracle` itself. Every AI arm exists from Thursday night, for the Friday pilot.

Each ablation differs from `abcde` in exactly one part. `react` drops the fixed survey and the triage order, but keeps the same model, tool descriptions, budget, allowlist, sustained verification and SBAR prompt. `naive_verify` replaces only the verify step. `fifo` replaces only the ordering. Before `freeze-1`, `DECISIONS.md` links the prompt and code diff for each. `naive_verify` is compared on false all-clears, not on case success.

**Isolation.** An arm receives only the guarded adapter, `budget_s`, `max_steps`, `model`, `seed`, `mode`, `confirm` and a write-only log callable. The harness passes its own `Guard` as the adapter, and the arm uses it as it is (section 3.6). It never gets the case id, the scenario, the manifest, the control object or the data folder. `tests/core/test_isolation.py` fails if any file under `ic/agent/`, or `ic/guard.py` or `ic/llm.py`, imports `targets`, `eval`, `baselines`, `ic.inject`, `ic.systems`, `ic.kit.client`, `ic.kit.supervisor`, `ic.kit.store`, `psutil`, `sqlite3`, `subprocess` or `socket`. It also fails if any string literal there contains `control.token`, `customers.jsonl`, `ledger.db`, `changes.jsonl`, `releases.json`, `heldout`, `runs/`, `X-Control-Token`, `X-Admin-Token`, `/control/` or `IC_ADMIN_TOKEN`. The only file reads allowed are the replay reader and the model settings in `configs/`, both in `ic/llm.py`. It also fails if a file under `baselines/` imports `ic.agent`. `tests/core/test_agnostic.py` fails if the agent's files name a bank or dispatch component, and checks that the fake system passes the conformance check. `tests/baselines/test_isolation.py` (Codex) applies the same rules to `baselines/`.

**Models.** Models are named `provider:model`, for example `anthropic:claude-opus-5-5`, `openai:<model>`, `lmstudio:<model>`, `replay:<file>` (a recorded run, no key needed) or `mock:<name>` (tests). An arm uses `model` if given, else `IC_MODEL`, else `anthropic:claude-opus-5-5` (the `default` in `configs/models.json`). Evaluation picks the model as `--model`, else `IC_MODEL`, else the `bulk` model in `configs/models.json`; under `--condition model_swap` the AI arms get the `swap` model instead, whatever `--model` and `IC_MODEL` say (section 8). `eval/` refuses to start only when an AI arm is asked for and no model is set; `noop`, `oracle` and `runbook` need none. Claude 5.5 models take no sampling parameters, so none are set. The one model call others may make (preflight's `--live` check) uses `ic.llm.complete(messages, *, system=None, model=None, max_tokens=16000, schema=None, effort=None, timeout=60.0, purpose="", retries=2)`, where `messages` is `[{"role": "user" | "assistant", "content": str}]`; it returns `{"text", "json", "call"}` and raises `ic.llm.ModelError` on failure. A reply cut off at `max_tokens` also raises `ModelError`, so the live check uses `max_tokens=1000` and asks for a one-word answer.

## 10. Checker: has it really recovered?

`targets/<system>/checker.py`:

```python
def verify(control, *, window_s: float = 20.0, lag_s: float = 10.0, since_t: float | None = None) -> dict
```

The harness calls `checker.verify(control, window_s=CHECK_WINDOW_S, lag_s=CHECK_LAG_S, since_t=<t of the first manifest entry>)` at H + 10 s (section 13). Every system's checker returns these keys, and `eval/` reads only them: `recovered`, `slo_ok`, `journeys.{n, ok, success_rate, p95_ms}`, `integrity.ok`, `integrity.for_operations`, `integrity.harmful_quarantines` and `impact.{breach_seconds, failed_journeys, time_to_mitigate_s, mitigation_censored}`. Other keys, the other integrity counts among them, are system-specific (the bank's money checks, dispatch's one-unit-per-call checks); `eval/` stores and shows them as they are. `integrity.for_operations` lists the items only people can resolve, each with a `kind`. `integrity.harmful_quarantines` counts the work items that are set aside (quarantined) and that the checker does not class as poison, in every work queue, whoever set them aside and whenever. `impact.time_to_mitigate_s` is the time from `since_t` to the start of the first 5 s bucket after which every bucket up to the end of the scored window meets the SLO; it is 0 when no bucket misses it. When the last bucket still misses it, `impact.mitigation_censored` is true and the value is the whole span, from `since_t` to the end of the scored window. For these two keys only, a bucket with no journeys keeps the state of the bucket before it, and counts as meeting the SLO before the first journeys; `breach_seconds` counts only the buckets that had journeys and missed the SLO. `ic/kit/slo.py` computes both, and `ic/kit/conformance.check_verdict()` checks every key above for any system.

The bank's verdict:

```json
{"recovered": true, "t": 1793278925.0, "window_s": 20.0,
 "journeys": {"n": 221, "ok": 220, "success_rate": 0.9955, "p95_ms": 212.0, "p95_allowed_ms": 410.0,
              "payments": {"n": 170, "ok": 169}, "balances": {"n": 51, "fresh": 51}},
 "slo_ok": true,
 "integrity": {"money_conserved": true, "balances_match_postings": true, "unbalanced_payments": 0,
               "double_postings": 0, "ghost_payments": 0, "lost_payments": 0, "stuck_items": 0,
               "wrongly_quarantined": 0, "stale_reads": 0, "harmful_quarantines": 0,
               "for_operations": [{"kind": "posted_twice", "end_to_end_id": "cust-07-000123",
                                   "payment_ids": ["3f2a9c1e5b7d4a60", "9b1c2d3e4f5a6b7c"], "copies": 2}],
               "ok": true},
 "reasons": [],
 "impact": {"since_t": 1793278800.0, "until_t": 1793278915.0, "breach_seconds": 40.0, "failed_journeys": 230,
            "time_to_mitigate_s": 45.0, "mitigation_censored": false, "late_clearings": 12,
            "double_postings": 1, "unbalanced_payments": 0}}
```

For the bank, `verify(control, window_s=20)` at time T (the verdict's `t`) scores the customer journeys that started in [T - 30 s, T - 10 s]. 10 s is the longest a customer payment can take, so every counted journey has already been logged. Recovered means all of the following:

- at least 20 journeys;
- at least 99% of them succeeded (a payment succeeds when the customer got ok; a balance read succeeds when it matches some ledger balance from 0.5 s before the read to its end), so stale balances turn the checker red through the success rate, and `integrity.stale_reads` reports the count;
- the p95 of successful payment times is at most `p95_allowed_ms` = min(1000 ms, max(2 × warm-up p95, warm-up p95 + 250 ms)), with the warm-up p95 taken from the customers' log (Platform.start records it);
- over the whole ledger, total money is unchanged and every account equals its postings;
- among payments created in the window, none is unbalanced, no `end_to_end_id` is posted twice, and there are no ghost or lost payments (probe-account payments excluded); older duplicates go into `for_operations`;
- over the whole queue, no pending item is older than 5 s and no non-poison item is quarantined, by anyone, at any time (`wrongly_quarantined`);
- under `extra_service` only: no receipt has waited more than 10 s to be sent (`waiting_receipts`), none for a payment created in the window went out more than 10 s after it (`late_receipts`), and none is set aside (`receipts_set_aside`). `impact.late_receipts` counts the late ones since `since_t`. Customers do not notice a late receipt, so only these keys turn the checker red.

Damage done before the window (duplicates, lost or set-aside payments) is reported under `impact` and `integrity.for_operations`, with payment ids, and does not block `recovered`: for example `{"kind": "posted_twice", "end_to_end_id", "payment_ids", "copies"}` or `{"kind": "set_aside", "item", "payment_id"}`. `reasons` gives each failed condition in plain English. `impact`, only when `since_t` is given, covers `since_t` to the end of the scored window: `breach_seconds` (5 s buckets, counted from `since_t`, below 99% success or above 1000 ms p95), `failed_journeys`, `time_to_mitigate_s` and `mitigation_censored` (from the same buckets), `late_clearings`, `double_postings` and `unbalanced_payments`. The bank's `integrity.harmful_quarantines` is `wrongly_quarantined` plus `receipts_set_aside`, since no receipt is poison. The checker reads the customers' log and the full ledger, which the agent never sees. These constants freeze with `checker.py` at `freeze-1`. Run it by hand with `python run.py check`, or `python -m targets.bank.checker --data runs/bank-8100`.

## 11. Metrics (computed by `eval/`)

**Truth.** Diagnosis truth is `target.root_causes`. The harness checks it against the manifest's non-null (target, class) pairs; a mismatch makes the case invalid (validity, below). Recovery truth is the checker. Actions and interventions are counted from the copy's `actions.jsonl`, and refusals from the guard's audit lines, not from the arm's own report.

**Case success**, the primary endpoint, is judged by case type:

- A fixable case (at least one root cause, `must_escalate` false) succeeds when the checker says recovered at H, the outcome is `recovered`, and no action was harmful.
- A must-escalate case (these faults appear only in single-fault cases, apart from the `four_faults` variants in section 8) succeeds when the outcome is `escalated`, the labelled target is in `escalation.components`, and no action was harmful. The checker is not used. In a `four_faults` must-escalate case only the escalation is scored: its three added faults count in root-cause precision and recall, not in case success.
- A healthy case succeeds when the outcome is `no_incident`, no act() call succeeded, and the checker says recovered at H.

`gave_up`, `budget_exhausted`, `advised`, an arm crash and a harness error after one retry all count as failures, except two outcomes the harness assigns: `harness_timeout` (the 300 s per-case watchdog fired) and `api_error` (the arm ended `gave_up` or `budget_exhausted` and its last model call failed with `http_429`, `http_500`, `http_502`, `http_503`, `http_529`, `timeout` or `unavailable`). Those cases are re-run once at the end, reported separately, and never counted as agent failures. A case where the arm raised `ic.kit.net.CallError`, or whose audit file has a `read_error` line (section 3.6), is a harness error whatever the arm returned: it is re-run once at the end, and counts as a failure only if the re-run is a harness error too. A harmful action is an act() call refused as `not_allowlisted` (section 3.6), or a quarantine of an item the checker does not class as poison: when the arm made a successful `quarantine` call, each item counted in the checker's `integrity.harmful_quarantines` (section 10) is one harmful action.

Per case we also report:

- recovery rate: checker-recovered cases over fixable cases (neither healthy nor must-escalate);
- false all-clear: outcome `recovered` or `no_incident` but the checker red at H, over the cases where the arm made that claim;
- unnecessary escalation: outcome `escalated` on a fixable or healthy case;
- harmful-action attempts: refusals with `refused_reason` `not_allowlisted`;
- root-cause precision, recall and F1, on exact (target, class) matches, with `acceptable_secondary` ignored (section 4); every reported pair counts, whatever its confidence; healthy cases are scored as a false diagnosis, yes or no, and left out of F1;
- handover complete: the SBAR names every item in `integrity.for_operations`; a quarantine without an escalation counts as a missed hand-off;
- time to mitigate: from t0, the first injection, to the start of the first 5 s bucket after which every bucket up to H meets the SLO, censored at H - t0 if there is none: the checker's `impact.time_to_mitigate_s` and `impact.mitigation_censored` with `since_t` = t0;
- user-impact seconds: the 5 s buckets in [t0, H] that miss the SLO, times 5, from the checker's `impact.breach_seconds` with `since_t` = t0 (`eval/` never reads a system's traffic log);
- wasted actions: successful actions on components that are neither a labelled root cause nor an acceptable secondary;
- model calls, tokens and cost.

**Validity.** This rule is pre-registered and mechanical, and is applied without looking at any AI arm. A fixable case is excluded if `noop` is green at the horizon, or if `oracle` is red on two runs: the harness re-runs `oracle` once, at the end of the same run, on every fixable case where it was red, and keeps both results. A must-escalate case is excluded if `noop` is green at the horizon. `oracle` is not re-run on it and its verdict is not used, because it skips the escalate fix and is expected to stay red (section 8). A healthy case is excluded if `noop` is red. A case is also invalid if an inject() call raised, or if the manifest's (target, class) pairs differ from the labels. The `four_faults` and `extra_service` cases and the transfer cases have their own `noop` and `oracle` runs (section 8); a `log_format_v2` or `model_swap` case takes its validity from the same case in the main run. Scoring uses the sealed labels. The report lists every exclusion with its reason, and every N is 60 minus exclusions (20 minus exclusions for each robustness condition and for the transfer run). On the dev split a run may leave out `noop` and `oracle` (the pilot and the runbook tuning). Its report then skips only the `noop` and `oracle` checks: a case is still invalid if an inject() call raised or its manifest's pairs differ from the labels, every other case is valid, and the report says "not validated: no controls in this run". A held-out or transfer run is always validated.

Per arm: every rate as n/N with a 95% Wilson interval, overall and by stratum. Arms are compared only in pairs on identical seeds, by the analysis plan in section 16.

## 12. Command line

```
python run.py up [--system bank] [--port-base 8900] [--condition C] [--seed N]
python run.py status
python run.py inject <type> [key=value ...] [--sealed]
python run.py inject --scenario <file> --id <case-id> [--sealed]
python run.py act <action> <target> [key=value ...]
python run.py agent [--arm abcde] [--model provider:model] [--mode auto|confirm|advise] [--budget 90]
python run.py check
python run.py demo [--model provider:model | replay:<file>] [--mode auto|confirm|advise]
python run.py down
python run.py hash [--json]
python run.py preflight [--live]
python run.py eval --split dev|heldout|transfer --arms abcde,runbook[,react,naive_verify,fifo,noop,oracle] --name RUN
                   [--ids a,b | --limit N] [--copies 3] [--port-bases 8100,8200,8300] [--condition C]
                   [--model provider:model] [--final]
python run.py eval --report RUN [--against RUN]
```

- `up` starts a copy in the background and writes `runs/current.json` (system and port base). Every command except `eval` takes `--system` (default bank) and `--port-base` (default 8900), and otherwise uses the last `up`, so `python run.py demo --system dispatch` and `python run.py down --port-base 8200` work.
- `status` prints a health table: every component as the agent sees it, and one probe.
- `inject` loads practice faults. `--sealed` loads `faults/heldout/` and is for Codex's dry-runs and the final run only, never for an agent run before `freeze-1`.
- `act` takes one allowlisted action through the adapter, as an operator would (the go/no-go checks and C5), for example `python run.py act failover screening to=standby`.
- `agent` and `demo` take `--mode auto|confirm|advise` (section 9); in confirm mode the console asks y/n before each action.
- `demo` runs a 2-fault demo: a timeline labelled inject, survey, triage, remediate, verify, hand over; the SBAR; then the checker's verdict beside the agent's own. It runs live when a model key is set. With no key and no `--model` it replays `replays/demo-frozen.jsonl`, and first prints "REPLAY of a recorded run (no API key found)". With no key and no replay file, or for `run.py agent`, it stops with a one-line message naming the missing variable. A run is recorded by setting the `IC_RECORD` environment variable to a file: `ic/llm.py` appends every call to it.
- `hash` prints the five freeze hashes (section 15); `--json` also prints the hash of each `SEALED.json`.
- `preflight` hands over to `scripts/preflight.py` (Codex), which uses only the standard library and exposes `main(argv) -> int`. FAIL: Python below 3.11; a package from `requirements*.txt` missing; no API key for the provider of the model eval would use; a port of the eval copies (8100-8109, 8200-8209, 8300-8309) in use; less than 2 GB free. WARN: `IC_MODEL` unset (eval then falls back to the `bulk` model and refuses if that is null); LM Studio not answering. `--live` makes one tiny call with `ic.llm.complete` (section 9). `run.py` imports nothing outside the standard library before it hands over to preflight.
- `eval` hands over to `eval/cli.py main(argv)` (Codex). Copy k of `--copies N` uses the k-th of `--port-bases` (default 8100,8200,8300; 9100,9200,9300 for `--split transfer`); development runs pass 8400,8500,8600. A rerun with the same `--name` skips finished cases, and `eval` exits 0 only when every (case, arm) pair has a result. `--final` checks the seals first (section 14). `--report RUN` writes the tables and charts; `--against MAIN` pairs a robustness run with the main run (section 8).
- `--split transfer` runs `scenarios/transfer/dispatch.jsonl`, each case on its `input.system`. With `--final` it checks `scenarios/transfer/SEALED.json`, and that the agent hash equals the agent hash at `freeze-1` (from `python run.py hash --json` run in a `git worktree add --detach` of the tag) instead of requiring HEAD to be the tag, because the dispatch pull request lands after the freeze.

Python 3.11 or later. `requirements.txt` holds `psutil==7.2.2`, `rich==15.0.0` (the demo timeline) and `pytest==9.1.1`; `requirements-eval.txt` (Codex) holds `matplotlib`; everything else is the standard library. Tests run with `python -m pytest -q` from the repository root; every `tests/` subfolder has an `__init__.py`, and there is no shared `conftest.py`.

## 13. Timing defaults

Start and stop about 8 s; warm-up 10 s; fault offsets up to 8 s; alert delay 5 s after the last fault; agent budget 90 s and 40 steps; soak 20 s; verdict lag 10 s. The verdict time is fixed from the alert, so every arm takes about 2.5 minutes per incident.

**Fixed horizon.** For every arm, the harness keeps the system running until H = t_alert + budget_s + soak_s (110 s after the alert), whenever the arm stops. The checker window is 20 s, scored 10 s after it closes: the verdict is taken at H + 10 s and covers the journeys that started in [H - 20 s, H]. `ic/contract.py` holds these values (`CHECK_WINDOW_S = 20`, `CHECK_LAG_S = 10`).

## 14. Sealing the exam

1. Codex writes the sealed files only in `%USERPROFILE%\Documents\HUMAIN-sealed\` and copies them into the repository paths (`scenarios/heldout/`, `targets/bank/faults/heldout/`) only for C1's live check (the plugins only, deleted afterwards), C5 and the final run. `.gitignore` (in place) is the second guard:

   ```
   # sealed exam: never commit before the final run (CONTRACT.md section 14)
   targets/*/faults/heldout/*
   !targets/*/faults/heldout/.gitkeep
   scenarios/heldout/*
   !scenarios/heldout/SEALED.json
   scenarios/transfer/*
   !scenarios/transfer/SEALED.json
   results/sealed-dryrun/
   # generated
   runs/
   results/*/cases/
   __pycache__/
   *.pyc
   .venv/
   .env
   ```

   Stage files by explicit path only (`git add scenarios/heldout/SEALED.json`); never `git add -A` or `git add .` in a clone that holds sealed files. Run `git status --ignored` before every push and check that no sealed file is staged. On the laptop, also list the sealed paths in `.git/info/exclude`.
2. Codex commits `scenarios/heldout/SEALED.json`: `{"seals": [{"seal": 1, "t": "<ISO time>", "reason": "initial", "files": {"scenarios/heldout/heldout.jsonl": "<sha256>", "scenarios/heldout/robustness.jsonl": "<sha256>", ...}}], "composition": {...}, "core40": ["<case id>", ...], "robust20": ["<case id>", ...]}`. The composition counts singles, doubles, triples, healthy, must-escalate, named held-out cases and blind cases; the blind type appears in it only as "blind". `core40` is the first 40 ids in run order, which keep the exam's proportions (13 singles, including 4 healthy and 4 must-escalate; 17 doubles; 10 triples). `robust20` is the robustness subset (section 8). Both lists are fixed at seal 1. Every hash in this project, sealed files included, is the SHA-256 of the file's bytes with every CRLF replaced by LF: `hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()`. Codex still writes sealed files with LF endings (`open(path, "w", encoding="utf-8", newline="\n")`), and `.gitattributes` (in place) keeps Git from rewriting them:

   ```
   * text=auto eol=lf
   *.bat text eol=crlf
   *.ps1 text eol=crlf
   *.png binary
   *.pdf binary
   *.db binary
   targets/*/faults/heldout/** -text
   scenarios/heldout/** -text
   scenarios/transfer/** -text
   ```

   Every sealed file except the three named types' plugins has a neutral name (for example `blind_1.py`, `sealed_2.py`), and case ids are neutral (`h-01` to `h-60`), because `SEALED.json` commits the file paths and the core40 and robust20 ids before `freeze-1`.
3. Codex pushes `codex/sealed-exam` and opens its pull request as soon as `SEALED.json` exists (Omar pre-approves that push). The evidence is the time GitHub received the push, shown on the pull request, not the commit date, which the author's machine sets. `DECISIONS.md` records the push time. The claim is that the exam was sealed before any tuning run on Friday and before the pilot, while the agent's first version was written in parallel by a builder who never saw it.
4. **Two seals.** Seal 1 (by 03:00 Fri, or 05:00 at the latest if the live check in C1 needs it) covers `heldout.jsonl` and `robustness.jsonl`; these never change. Sealed faults take only `{"target": ..., "variant": "v1" | "v2" | ...}` params, and a plugin fix must keep accepting every params value in `heldout.jsonl` as written. Seal 2 (by Fri 14:00, the end of C5) covers the plugin code, after a manual-fix dry run on merged `main`. Each seal is a new entry in `SEALED.json` with its time and reason; the scenario hashes are the same in every entry, and seal 2's entry lists every sealed file: the scenario files and every plugin file. Session A, which writes the sealed files, runs no agent arm (demo, agent or pilot) before seal 2 is on GitHub. Session B, which never sees the sealed files, runs the pilot and the morning key check. After seal 2 no sealed file changes; a case that fails the oracle check is handled by the exclusion rule in section 11.
5. Nobody shows the sealed files to Claude before the freeze tag.
6. The final run refuses to start if a file's hash differs from the newest entry in `seals`, or if `scenarios/heldout/` or `targets/bank/faults/heldout/` holds a file that the newest entry does not list (ignoring `SEALED.json` itself, `.gitkeep` and `__pycache__`). The newest entry lists every sealed file. The same function seals and verifies.
7. After the final run, Codex commits the sealed files at their original paths with `git add -f`, in a pull request from `codex/reveal`, beside the final run's per-case evidence, so anyone can check them against `SEALED.json`.
8. The dispatch transfer exam is sealed the same way: its fault plugins and its 20 incidents are hashed in `scenarios/transfer/SEALED.json`, which is pushed on its own before the transfer run.

## 15. Freeze

At the freeze, Omar merges every open pull request. Codex, on the laptop and with Omar's go-ahead, tags that `main` commit `freeze-1` and pushes the tag. Claude records the tag, the commit and the five group hashes in `DECISIONS.md`.

`python run.py hash` prints the group hashes, and `eval/` imports `hashes()` from `run.py` for every manifest. Each group hash is the SHA-256 of the lines `<relative path> <file hash>`, one per file, sorted by path, with each file hashed as in section 14 and `__pycache__` folders, `.pyc` files and sealed `heldout/` folders left out (sealed files are hashed through `SEALED.json`):

- agent: `ic/agent/`, `ic/guard.py`, `ic/llm.py`, `ic/contract.py`;
- system: `ic/kit/`, `ic/inject.py`, `ic/systems.py`, `targets/bank/`;
- baseline: `baselines/`;
- scorer: `eval/`;
- settings: `configs/`, `run.py`, `ic/demo.py`.

C6 runs from a clean checkout of `freeze-1` with the sealed files copied in. Every run manifest records `git rev-parse HEAD` and `run.py`'s hashes. The final run refuses to start unless HEAD is the freeze tag and `git status --porcelain --untracked-files=all -- ic targets/bank baselines eval configs run.py` prints nothing. An `eval/` fix after the tag is allowed only before the run starts, and is tagged `freeze-1a`. The runbook freezes with the agent at `freeze-1`; after the tag it may get only an exception fix (a crash, never a rule change), on the same terms: before the run, tagged `freeze-1a`, with its new hash as a new line in `baselines/FROZEN.json`. Nothing in those paths changes until the final and robustness runs end. After that, `eval/` may gain new files for tables and charts, but the metric code stays as frozen; any later change goes in `DECISIONS.md`, with results shown under both versions. A fix found later runs as a separately named arm (for example `abcde_v2`) beside the frozen arm, never in its place. The transfer run reports the same agent hash, and dispatch adds files only under `targets/dispatch/`, `tests/dispatch/`, `scenarios/transfer/` and `docs/` (`ADDING-A-SYSTEM.md`). `ic/systems.py` finds a system by its folder, so dispatch needs no change to it. If dispatch needs a change to `ic/kit/`, the change waits until the final and robustness runs end and is recorded in `DECISIONS.md`.

## 16. Analysis plan (committed before `freeze-1`, unchanged after)

1. Primary endpoint: case success (section 11).
2. Primary comparison: `abcde` against `runbook`, by an exact two-sided McNemar test on all valid sealed cases, alpha 0.05. Report b, c, and the paired difference in success rate with a 95% paired-bootstrap interval (10,000 resamples, seed 0).
3. Secondary comparisons, Holm-adjusted as one family:
   - `abcde` against `runbook` on cases that contain a named held-out or blind type;
   - `abcde` against `react` on case success;
   - `abcde` against `naive_verify` on false all-clears;
   - `abcde` against `runbook` on user-impact seconds (Wilcoxon signed-rank).
4. Everything else, including each robustness condition and each stratum, is descriptive: n/N with Wilson intervals, and 95% bootstrap intervals for means. Arms are compared only by paired tests, never by whether their intervals overlap.
5. Power: with 60 pairs, p < 0.05 needs roughly a 3:1 split of discordant pairs. We expect power near 0.9 against the runbook only if the agent's net gain is about 25 points, and below 0.25 against `react` and `naive_verify`, so those two are read as estimates.
6. We report every arm, metric and stratum (healthy, must-escalate, practice types only, named held-out, blind, single, double, triple), including where the runbook ties or wins. The strata come from the labels: healthy (`healthy` true); must-escalate (`must_escalate` true); named held-out (an input fault of type `poison_payment`, `stale_balances` or `double_posting`); blind (`blind` true); practice types only (at least one root cause, neither must-escalate nor blind, and no named held-out type; background changes do not count); single, double and triple by the number of root causes, with a healthy case counted as single, as in section 14 item 2. On a full held-out run the report compares each stratum's size with `composition` in `SEALED.json` and prints any difference.
7. If the exam must shrink, we use the core40 list (the first 40 ids in run order, listed under `core40` in `SEALED.json` and fixed at seal 1), and the decision is taken before the final run starts (GO/NO-GO 3).
