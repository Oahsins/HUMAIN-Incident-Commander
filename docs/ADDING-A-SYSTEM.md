# Adding a system

The incident commander never imports anything from the system it looks after (CONTRACT section 1). It sees a system only through five functions, the adapter, and it changes a system only through six bounded actions. To plug it into something new, you write that thin layer. The agent's code does not change.

There are two paths:

| You have | You write | You get | Section |
|---|---|---|---|
| A system that already runs: an organiser's system, a staging environment, a monitoring stack | `targets/<system>/adapter.py` and a short `platform.py` | The agent on that system. It starts read-only (advise mode), then a person confirms each action, then it acts on its own | 2 |
| No system yet, and you want to measure the agent | A test system on `ic/kit`: a spec, its services, four short files and practice faults | The agent, a checker that says whether the system really recovered, and an exam harness that can score every arm | 3 |

The bank (`targets/bank/`) is built on the second path, and this guide uses it as the worked example. `docs/CONTRACT.md` is the source of truth. This guide points to its sections ("CONTRACT 3.1") rather than repeating them, and where the two differ, the contract wins.

## 1. What the agent needs from any system

| Function | Returns | The agent uses it for |
|---|---|---|
| `describe()` | The profile: components, who depends on whom, the user journeys and their service levels, the actions each component allows, and the lines never to cross (CONTRACT 3.1) | Its map: the order of the survey, "upstream first" in triage, what it may do |
| `observe(window_s)` | Metrics per component, the healthy baseline and the recent changes (CONTRACT 3.2) | The ABCDE survey (CONTRACT 3.7), and the sustained check after a fix |
| `logs(component, since_s, limit)` | Log records, oldest first, each with at least `t` (CONTRACT 3.3) | Evidence for the model, after secrets are masked |
| `probe(journey)` | One synthetic user journey, step by step (CONTRACT 3.4) | Checking whether users get through, before and after a fix |
| `act(action, target, params)` | `ok`, `refused` and a `detail`. It never raises (CONTRACT 3.5) | The six actions, and nothing else |

The six actions are `restart`, `rollback`, `revert_config`, `release_lock`, `failover` and `quarantine`. Each is bounded and safe: four can be undone, and the other two lose no committed data. A system maps each action onto its own tools, and offers each component only the actions that make sense for it. If no action can fix a fault (an outage at another organisation, say), the agent escalates it to a person. Escalating and declaring recovery are things the agent reports; they are not actions.

The agent never holds the adapter itself. It gets the safety wrapper (`ic/guard.py`, CONTRACT 3.6), which:

- refuses any action outside the six or outside the target's list;
- allows at most 8 actions per incident, and the same action on the same target at most twice;
- enforces the mode (`auto`, `confirm` or `advise`);
- refuses further reads after the step limit;
- writes an audit line for every decision;
- masks secrets in log records before the model reads them.

So an adapter needs no safety logic of its own. It only has to refuse an action it does not support, never raise on one.

## 2. Path 1: an adapter for a system that already runs

### 2.1 Decide what the agent may do

Start read-only. Set `capabilities.act` to false and `capabilities.max_mode` to `"advise"`. The agent then surveys, triages and hands over an ordered plan, and changes nothing; its outcome is `advised`. Move to `confirm` (a person approves each action at a yes/no prompt) and then to `auto` only when the system's owners agree.

Next, write down which of the six actions each component supports, and what each one means on this system. Typical mappings:

| Action | What it usually means on a running system |
|---|---|
| `restart` | Restart the service or its container (`systemctl restart`, a rolling restart of a deployment) |
| `rollback` | Return to the previous release with the deploy tool |
| `revert_config` | Return one setting to its previous value in the configuration store (`params.key`) |
| `release_lock` | End the database session that holds a blocking lock |
| `failover` | Move callers to the standby (a load-balancer pool, a DNS weight, a replica promotion); `params.to` is `standby` or `primary` |
| `quarantine` | Move one work item to a dead-letter queue (`params.item`) |

Leave out anything the system cannot do safely. A component with no actions can only be escalated; mark another organisation's system as kind `external`. List the lines the agent must never cross in `forbidden`, in plain words. The bank's list is: move, reverse or refund money; edit a balance or a posting; switch fraud screening off.

### 2.2 Write `targets/<system>/adapter.py`

The file holds one class, `Adapter`, with the five functions. Every return value must be plain JSON-serialisable data. Here is a read-only skeleton; `acme` stands for your system's name:

```python
"""What the incident commander can see of acme (docs/ADDING-A-SYSTEM.md, path 1)."""

import os

from ic.kit import net

PROFILE = {   # the profile, written by hand once (section 2.3)
    "system": "acme", "contract_version": 1,
    "capabilities": {"probe": False, "act": False, "changes": True, "baseline": "history",
                     "max_mode": "advise", "min_window_s": 30},
    "journeys": [], "components": [], "actions": {}, "forbidden": [],
}


class Adapter:
    def __init__(self, port_base=None):   # the platform passes a port base; a running system has no use for it
        self.base = os.environ["IC_ACME_URL"]   # addresses and credentials come only from IC_ACME_* variables
        self.headers = {"Authorization": "Bearer " + os.environ["IC_ACME_READ_TOKEN"]}

    def describe(self):
        return PROFILE

    def observe(self, window_s=10.0):
        _, metrics = net.get(f"{self.base}/metrics?window={window_s}", timeout=5.0, headers=self.headers)
        ...   # map them onto the standard fields (section 2.4)

    def logs(self, component, since_s=60.0, limit=200):
        ...   # section 2.5

    def probe(self, journey=None):
        return {"journey": None, "ok": None, "ms": None, "steps": [], "detail": "no synthetic journey"}

    def act(self, action, target, params=None):
        return {"ok": False, "refused": True, "action": action, "target": target,
                "detail": "this adapter is read-only"}
```

The rules (CONTRACT 3 and 3.6):

- The four reads raise `ic.kit.net.CallError` only when the system cannot be reached at all, or, for `logs()`, when the component is unknown. `ic.kit.net.get` and `post` raise it for you. Anything else comes back as data, and a metric the system cannot see is `null`, never 0.
- `act()` never raises. A failed action comes back as `{"ok": false, "refused": false, "detail": ...}`, and an action you do not support as `{"ok": false, "refused": true, ...}`. `ok: true` means the system accepted and ran the command; add `"pending": true` while a rollout runs. Only `observe()` and `probe()` confirm the effect.
- Credentials come only from environment variables named `IC_<SYSTEM>_*`. Use a read-only credential for the four reads and a separate one for `act()`, limited to the operations you mapped. Never return a credential in any answer.

### 2.3 The profile: `describe()`

CONTRACT 3.1 gives the full schema, with the bank's profile as an example. These are the parts that matter most when you write a profile by hand:

- `system`, and `contract_version` 1.
- `capabilities`:
  - `probe`: whether you have a synthetic journey.
  - `act`: whether the agent may act at all.
  - `changes`: whether you have a change feed. If it is false, an empty change list means "not visible", not "nothing changed".
  - `baseline`: `history` for a running system (the same metrics, measured before the alert), or `none`.
  - `max_mode`: `advise`, `confirm` or `auto`.
  - `min_window_s`: at least two scrape intervals. A 15 s Prometheus scrape needs 30.
- `journeys`: what users do. Each journey has a `name`, the component where users arrive (`entry`), its service level (`slo`: `success_rate` and `p95_ms`), `side_effects` and a `description`. Exactly one journey is the `default`. A real system offers only journeys with `side_effects` `none`: a probe never moves money or alerts a crew.
- `components`: one entry per component.
  - `name`: the name the operators use. The handover quotes it.
  - `kind`: `service`, `worker`, `datastore`, `queue`, `cache`, `dependency`, `external`, `job` or `other`.
  - `depends_on`: the components this one calls. Triage fixes faults upstream first.
  - `impact_weight`: from 0 to 1, the share of user journeys that fail when the component is fully down.
  - `standby`: the component that takes over after a failover, or null.
  - `actions`: the actions this component allows.
  - `description`: one line an on-call engineer would understand. The model reads it.
  - Optionally, `action_seconds`, which overrides an action's time for this component, for example `{"restart": 45}`.
- `actions`: for each action you offer, `est_seconds` (how long it takes to take effect; triage weighs it), `undo` (null for `restart` and `release_lock`), `params` and a `description`.
- `forbidden`, and optionally `escalation_contacts` (`[{"role": ..., "for": [components]}]`). When contacts are listed, an escalation names one of their roles.

The agent's code names no system's components; a test checks this. The profile is everything the agent knows about the system.

### 2.4 Metrics: `observe()`

`observe()` returns `{"t", "window_s", "components": {name: entry}, "baseline", "changes"}`. Every entry has the same eleven fields, each null when unknown: `up`, `p95_ms`, `error_rate`, `reject_rate`, `rps`, `cpu_pct`, `mem_mb`, `restarts`, `release`, `config_version` and `extra`. `error_rate` counts 5xx answers, timeouts and refused connections; `reject_rate` counts 4xx answers, the requests refused by a rule. CONTRACT 3.2 defines every field.

Its table of reserved `extra` keys lists the keys the agent's checks read:

- `dependencies` on every caller: each caller's own view of each dependency it calls. This is how the agent tells a slow dependency from a slow caller.
- `queue_depth`, `oldest_pending_s`, `head_item` and `processed_per_s` on workers.
- `lock_holders` and `write_errors` on datastores.
- `active` on a component with a standby.
- `exits_15m` and `not_answering` on processes.

Any other `extra` key is free-form, and only the model reads it.

Where the fields usually come from:

| Field | Usual source |
|---|---|
| `up`, `exits_15m` | Health checks, and the orchestrator's restart count |
| `p95_ms`, `error_rate`, `reject_rate`, `rps` | Server-side request metrics over `window_s` |
| `extra.dependencies` | Client-side request metrics or traces, per callee |
| `cpu_pct`, `mem_mb` | Process or container metrics |
| `release`, `config_version` | The deploy tool and the configuration store |
| `changes` | The deploy and configuration audit trail for the last 15 minutes. Each change is `{"id", "t", "component", "kind", "actor", "detail"}`, where `kind` is one of `deploy`, `config`, `start`, `stop`, `restart`, `failover`, `quarantine` or `lock_release`. Report any other kind as `other`, with the original in `detail.source_kind` |
| `baseline` | The same metrics, per component, from a quiet period before the alert (`{}` when `capabilities.baseline` is `none`) |

An `external` component reports only what its callers see, with `extra.view` saying so.

### 2.5 Logs and the probe

`logs()` returns records oldest first, and every record has `t` (epoch seconds, or null). A line you can parse also has `component`, `msg`, `level` and, when known, `event`. `level` is `INFO`, `WARN` or `ERROR`; map other levels onto these (journald priorities 0-3 become ERROR, 4 becomes WARN and 5-7 become INFO). A line you cannot parse comes back as `{"t": ..., "raw": "<the line>"}`. For an `external` component, `logs()` returns `[]`.

`probe()` runs one synthetic journey from a dedicated test identity and reports each step as `{"step", "component", "ok", "ms", "detail"}`. If there is no synthetic journey, return the "no synthetic journey" answer in the skeleton above, or one step per component health endpoint; the agent then verifies from `observe()` (CONTRACT 3.4).

### 2.6 Let the command line find it

`run.py` finds a system by its folder (`ic/systems.py`), through `targets/<system>/platform.py`. A system that already runs has nothing to start or stop:

```python
"""acme already runs, so this platform has nothing to start or stop (docs/ADDING-A-SYSTEM.md, path 1)."""

import os

from ic.kit.client import PlatformBase
from targets.acme.adapter import Adapter


class Platform(PlatformBase):
    system = "acme"
    adapter_cls = Adapter

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        os.makedirs(self.data_dir, exist_ok=True)   # run.py agent keeps the guard's audit and its result here

    def start(self, *args, **kwargs):
        raise RuntimeError("acme already runs: there is nothing to start")

    def running(self):
        return True

    def stop(self):
        pass
```

Add an empty `targets/acme/__init__.py` as well.

### 2.7 Check it, then run the agent

```
python -c "from targets.acme.adapter import Adapter; from ic.kit.conformance import check_adapter; print(check_adapter(Adapter()) or 'conforms')"
python run.py status --system acme
python run.py agent --system acme --mode advise
```

`check_adapter` calls each read once and checks the shapes. When `capabilities.act` is true, it also checks that an unknown action comes back refused. `status` prints the table the agent would see. `agent` needs a model key in the environment (CONTRACT 12). In advise mode it changes nothing. It writes its result and the guard's audit to `runs/acme-8900/`.

Checklist for path 1:

- [ ] Every component that a user journey passes through is in `describe()`, and its `depends_on` matches who calls whom.
- [ ] Each component lists only actions you have mapped and tried by hand.
- [ ] `forbidden` names the lines that matter on this system.
- [ ] `observe()` fills every standard field, using null for anything unknown, and gives `extra.dependencies` for every caller you can measure.
- [ ] `changes` comes from the real audit trail, or `capabilities.changes` is false.
- [ ] The reads raise only when the system cannot be reached, and `act()` never raises.
- [ ] Credentials come only from `IC_<SYSTEM>_*` variables, and the credential for `act()` can do only the mapped operations.
- [ ] `check_adapter` prints `conforms`, and `run.py status` looks right to an on-call engineer.
- [ ] The first runs use advise mode, and the owners read the plans before you switch to confirm or auto.

## 3. Path 2: a test system on `ic/kit`

A test system is a set of small Python web services that `ic/kit` runs as real processes. The generic control plane, `ic/kit/supervisor.py`:

- starts the services in order;
- keeps the change log and the versioned settings;
- relays the links you choose, so faults can slow them;
- serves both the agent's API (`/ops/...`, the five functions) and the privileged one (`/control/...`) on the copy's tenth port. The privileged API needs a token the agent never sees.

The system supplies only what makes it itself.

### 3.1 The files

| File | What it holds |
|---|---|
| `targets/<system>/spec.py` | Class `Spec`: the components, links and start order, the set-up, the test users, `describe()`, extra observations, the probe, how each action is carried out here, and the ground truth (section 3.2) |
| `targets/<system>/releases/<image>/v<release>.py` | One `class Release(ServiceBase)` per release of each service (section 3.3) |
| `targets/<system>/<users>.py` | The test users: a process that runs journeys all the time and logs each one (section 3.4). The bank's is `customers.py` |
| `targets/<system>/platform.py`, `adapter.py`, `control.py` | Short subclasses of `ic.kit.client` (section 3.7) |
| `targets/<system>/checker.py` | `verify(control, *, window_s, lag_s, since_t)`, which answers "has it really recovered?" (section 3.5) |
| `targets/<system>/faults/dev/<type>.py` | Practice faults (section 3.6) |
| `scenarios/<split>/<name>.jsonl` | The cases: the faults to inject, and the labels for scoring (CONTRACT 8) |
| `tests/<system>/` | The system's tests |

Every folder that holds Python files needs an `__init__.py`. That includes `targets/<system>/`, `releases/`, each release folder, `faults/`, `faults/dev/` and `tests/<system>/`.

### 3.2 The spec

The supervisor calls these hooks (CONTRACT 6.1).

**`components(condition)`** returns one dict per component. Each dict has the describe() fields (`name`, `kind`, `depends_on`, `impact_weight`, `actions`, `description` and `standby`), plus:

- `port_offset`: 0 to 8, or None for a component with no process of its own, such as a datastore file or a job. The tenth port of a copy (offset 9) is the control plane.
- `version`: the release the component starts on, or None if it has no process.
- `image`: the release folder, when it is not the component's own name. The bank's `screening-standby` runs `screening` releases.
- `config`: the component's default settings, or None. The supervisor keeps them versioned. `Control.set_config` changes one setting and logs a change, `revert_config` undoes one, and a service reads them with `self.setting(key, default)`.

**`links()`** returns the relayed routes, for example `{"payments->screening": {"listen_offset": 6, "upstream": "screening"}}`. A relay listens on `port_base + listen_offset` and forwards to the upstream component, and `Control.link(route, latency_ms, jitter_ms, drop_pct)` slows or breaks it. Components and relays share offsets 0 to 8, so a system can have at most nine of them in total.

**`start_order(condition)`** lists the components that have a process, dependencies first. The supervisor starts each one on its release, waits until every `/health` answers, then starts the test users.

**`init_data(sup)`** creates the datastores in `sup.data_dir` and seeds the test data. **`cleanup(sup)`** stops anything the system started outside the supervisor (the bank ends its lock-holding helpers). **`traffic_argv(sup)`** returns the test users' command line, for example `proc.python_argv("targets.<system>.users", "--data", sup.data_dir, "--port", sup.ports["<entry component>"], "--seed", sup.seed)`.

**`describe(sup)`** returns the profile (section 2.3). Build it from the component list, so the two never disagree.

**`observe_extra(sup, out, window_s)`** adds what only the system knows. By the time it runs, the supervisor has already filled every component's standard fields from its `/metrics`, its process and the release store, and has added:

- `extra.dependencies`;
- `exits_15m` and `not_answering`;
- `active`, for a component with a standby;
- `running`, for a job;
- an external component's view, taken from its callers.

The hook changes `out` in place. Typical additions are a datastore's `up`, `lock_holders` and `write_errors`, and a worker's queue keys. Read the queue keys from the queue itself, so they still show while the worker is down.

**`probe(sup, journey)`** runs one journey from the test identity and reports each step (CONTRACT 3.4). The bank's payment probe has five steps.

**`act(sup, action, target, params, actor) -> (ok, detail)`** carries out an action. The supervisor calls it only for one of the six actions that is also in the target's list; it refuses everything else itself, and it logs every call to `actions.jsonl`.

- For `restart`, `rollback` and `revert_config`, use `sup.restart(target, actor)`, `sup.rollback(target, actor)` and `sup.revert_config(target, actor, key=...)`.
- For `failover`, call `Routing(sup.data_dir).set(target, to)` and log a `failover` change with `sup.changes.add(target, "failover", actor, ...)`.
- `release_lock` and `quarantine` are the system's own. Log a `lock_release` or a `quarantine` change for them.
- `detail` is one plain sentence, because the agent reads it.

**`snapshot(sup)`** returns the ground truth for the checker and the harness. The agent never sees it.

### 3.3 Services and releases

A service is one process, and `ic.kit.service.ServiceBase` gives it most of what it needs: a small JSON web server with `/health` and `/metrics`, a JSON log in `logs/<component>.jsonl`, its versioned settings and rolling request statistics. A release adds the service's own behaviour:

```python
# targets/example/releases/web/v1_0.py: the front end of the template in section 3.8
from ic.kit import net
from ic.kit.service import ServiceBase


class Release(ServiceBase):
    def routes(self):
        # a path ending in "/*" matches any suffix, which the function reads from request["tail"]
        return {("POST", "/order"): self.order, ("GET", "/order/*"): self.get_order}

    def order(self, request):
        if not request["body"].get("item"):
            raise net.Reply(400, {"error": "no item"})   # a 4xx answer counts as a reject, a 5xx as an error
        return self.forward("POST", "/order", request["body"])

    def get_order(self, request):
        return self.forward("GET", "/order/" + request["tail"])

    def forward(self, method, path, payload=None):
        try:
            return self.call("api", method, self.url("api", path), payload,
                             timeout=self.setting("api_timeout_s", 2.0))[1]
        except net.CallError as exc:
            raise net.Reply(502, {"error": f"api unavailable ({exc.kind})"})
```

- `self.call(dep, method, url, payload, timeout)` records each call under `dep`, which is where observe() gets `extra.dependencies`. Name `dep` exactly as the component appears in `depends_on`. For an external component, the callers' records are all the agent sees of it. The call returns `(status, body)` and raises `net.CallError` when the call fails.
- `self.url(name, path)` takes a component name or a link route such as `"worker->partner"`. A call to a route goes through the relay, so faults can slow it.
- A worker overrides `background()`, a loop that returns only to stop. An exception there crashes the whole process, as a real crash would. The process then stays down until someone restarts it, because the supervisor never restarts anything by itself.
- `extra_metrics(window_s)` adds component-specific keys to `/metrics`, and `observe()` puts them under `extra`.
- Log with `self.log.info`, `self.log.warn` and `self.log.error(event, msg, **fields)`. For a problem that repeats, use `self.log_every(key, interval_s, level, event, msg)`. `self.short_traceback()` gives paths relative to the release folder, never repository paths. The `log_format_v2` condition changes the layout of every line written through `self.log`, with no work from the system.
- `self.routing.active(component)` tells a caller whether to use a component's primary or its standby.
- A release file is named after its version, with underscores for the dots (1.3 is `v1_3.py`). A new release usually subclasses the current one and overrides one method. A fault can deploy a release kept elsewhere with `control.deploy(component, "1.5", module_path=...)`. That copies the file into the copy's data folder first, so nothing the agent can read names the source file.

### 3.4 The test users and their log

The test users are one process. It runs journeys against the entry component all the time and appends one JSON line per journey to its own log. In the bank, that is `customers.jsonl`, with the journey's `kind`, its start and end times, its outcome and what was asked. The users retry the way a real client would. Their log is the ground truth: the checker judges recovery from what users lived through, not from the system's own metrics, and the agent never sees it. `Control.paths()` returns the log as `traffic_log`. Keep the load steady and high enough that a 20 s window holds well over the checker's minimum number of journeys; the bank needs 20, and its example verdict counts 221.

### 3.5 The checker

`verify(control, *, window_s=20.0, lag_s=10.0, since_t=None) -> dict` reads the users' log and the datastores directly. It answers one question: in the `window_s` seconds that ended `lag_s` ago, did users get a working service, and is the data intact? `lag_s` is the longest a journey can take, so every journey it counts has finished.

Every checker returns the keys `eval/` reads (CONTRACT 10):

- `recovered` and `slo_ok`;
- `journeys.{n, ok, success_rate, p95_ms}`;
- `integrity.{ok, for_operations, harmful_quarantines}`;
- when `since_t` is given, `impact.{breach_seconds, failed_journeys, time_to_mitigate_s, mitigation_censored}`. Compute the last two with `ic.kit.slo.time_to_mitigate()`, over 5 s buckets counted from `since_t`.

Any other key belongs to the system (the bank's money checks, for example), and `eval/` stores it as it is. Also add `reasons`, with one plain sentence per failed condition.

Four rules keep a checker honest:

- Judge from the users' log and the data. Never judge from the system's own metrics, or from anything the agent did or said.
- `recovered` needs a minimum number of journeys, a success rate and p95 within the service level, and every integrity rule. Damage done before the window (a duplicate, an item set aside) goes into `integrity.for_operations` for people, with ids, and does not block recovery.
- `integrity.harmful_quarantines` counts every work item that was set aside and is not poison, whoever set it aside.
- Record the healthy reference, such as the warm-up p95, in the platform's `after_warmup` hook. The constants freeze with the checker.

Check every verdict with `ic.kit.conformance.check_verdict(verdict)`. It returns `[]` when every key is present; pass `impact=False` for a verdict taken without `since_t`.

### 3.6 Faults and scenarios

A fault plugin is one file, `targets/<system>/faults/dev/<type>.py`, with `TYPE`, `CLASSES` (the root-cause classes it can produce, from CONTRACT 4) and `inject(control, params, rng) -> dict`. `inject()` causes the fault through a real channel and returns the fault's manifest entry, `{"type", "target", "class", "detail", "t"}` (CONTRACT 7). The bank's `crash.py` is a good model.

- Use only the Control channels in CONTRACT 5: deploys, setting changes, kills and stops, link delays and drops, direct datastore writes, helper processes (`spawn`) and admin hooks (`admin(component, "hang")`). Never touch the agent, the checker or the users' log.
- Choose the actor from the same pool every change uses, never by fault type. No release label, session name, log line, change detail or payload may name the fault type or its class.
- Label each fault by the mechanism its fix reverses: a `(target, class)` pair plus the fix (CONTRACT 4 and 8). A value that is only known at run time, such as a queue item id, is `null` in the label, and the plugin records it in the manifest's `detail`.
- Before you trust a case, run it on a live copy with its labelled fixes. The `oracle` arm must turn the checker green, and `noop` must leave it red.

A scenario line looks like `{"id", "input": {"system", "seed", "condition", "faults": [{"type", "at_s", "params"}]}, "target": {"root_causes", "healthy", "must_escalate", "blind", "acceptable_secondary"}}` (CONTRACT 8). To load one case by hand, run `python run.py inject --system <system> --scenario <file> --id <case>`.

### 3.7 Platform, adapter and control

`example` stands for your system's name, and `store` for its datastore.

```python
# targets/example/adapter.py
from ic.kit.client import OpsAdapter


class Adapter(OpsAdapter):
    pass
```

```python
# targets/example/control.py
import os
import sqlite3

from ic.kit.client import ControlClient


class Control(ControlClient):
    def db(self, name=None):
        if name not in (None, "store"):
            raise KeyError(f"example has no datastore named {name!r}")
        return sqlite3.connect(os.path.join(self.data_dir, "store.db"), timeout=5)

    def paths(self):
        users = os.path.join(self.data_dir, "users.jsonl")
        return {**super().paths(), "traffic_log": users,
                "datastores": {"store": os.path.join(self.data_dir, "store.db")},
                "checker_baseline": os.path.join(self.data_dir, "checker_baseline.json")}
```

```python
# targets/example/platform.py
from ic.kit.client import PlatformBase
from targets.example import checker
from targets.example.adapter import Adapter
from targets.example.control import Control


class Platform(PlatformBase):
    system = "example"
    adapter_cls = Adapter
    control_cls = Control
    conditions = ("default", "log_format_v2")   # only the conditions start() really implements; others raise ValueError
    demo_faults = [{"type": "crash", "at_s": 0, "params": {"target": "api"}}]   # what `python run.py demo` injects

    def after_warmup(self, warmup_s):
        checker.record_baseline(self.control(), window_s=warmup_s)   # the checker's own function
```

### 3.8 The 5-component template

These five components cover every kind of component the agent treats differently: an entry service where users arrive, a service behind it, a worker with a queue, a datastore, and another organisation's system.

```python
# targets/example/spec.py: the component list (section 3.2 has the hooks)
COMPONENTS = [
    {"name": "web", "kind": "service", "port_offset": 0, "version": "1.0", "config": {"api_timeout_s": 2.0},
     "depends_on": ["api"], "impact_weight": 1.0, "actions": ["restart", "rollback", "revert_config"],
     "description": "front end: receives every user request"},
    {"name": "api", "kind": "service", "port_offset": 1, "version": "1.0", "config": {"max_qty": 10},
     "depends_on": ["store"], "impact_weight": 1.0, "actions": ["restart", "rollback", "revert_config"],
     "description": "core service: checks each request, writes it to the store and queues the follow-up work"},
    {"name": "worker", "kind": "worker", "port_offset": 2, "version": "1.0", "config": {"batch_size": 20},
     "depends_on": ["store", "partner"], "impact_weight": 0.5,
     "actions": ["restart", "rollback", "revert_config", "quarantine"],
     "description": "background worker: sends queued work to the partner"},
    {"name": "store", "kind": "datastore", "port_offset": None, "version": None, "config": None,
     "depends_on": [], "impact_weight": 1.0, "actions": ["release_lock"],
     "description": "the datastore (SQLite): the records and the work queue"},
    {"name": "partner", "kind": "external", "port_offset": 3, "version": "1.0", "config": {},
     "depends_on": [], "impact_weight": 0.5, "actions": [],
     "description": "a partner's service, run by another organisation; we cannot change it"},
]
LINKS = {"worker->partner": {"listen_offset": 4, "upstream": "partner"}}
START_ORDER = ["partner", "api", "worker", "web"]
```

The faults each component can host, and the class of each:

| Component | Faults | Class and fix |
|---|---|---|
| `web`, `api` | A crash; a faulty release; a harmful setting | `process_down`, restart; `bad_release`, rollback; `bad_config`, revert_config |
| `worker` | A stop; an item it cannot parse, which crashes it; `batch_size` 0 | `process_down`, restart; `poison_message`, quarantine then restart, then a person; `bad_config`, revert_config |
| `store` | A helper process that holds the write lock | `lock_held`, release_lock |
| `partner` | The `worker->partner` link drops every connection | `external_outage`: escalate |

To add a standby, copy the bank's `screening` (CONTRACT 7.1). Give the primary kind `dependency`, `standby` set to the standby's name, and the actions `restart` and `failover`. Give the standby its own `port_offset` and the same `image`, and reach the primary through a link, so a fault can slow it (`dependency_slow`, fixed by failover).

### 3.9 Bring it up and check it

```
python run.py up --system example
python run.py status
python run.py inject crash target=api
python run.py act restart api
python run.py check
python run.py down
```

`up` uses port base 8900 unless you pass `--port-base`; pick a base whose ten ports are free. Then turn the checks into tests in `tests/example/`. The bank's `tests/bank/test_live.py` starts a copy, breaks it and heals it. Run `check_adapter(platform.adapter())` and `check_verdict(checker.verify(platform.control(), since_t=t0))` on a live copy.

Checklist for a test system:

- [ ] Every component has a description an on-call engineer would understand, and its `depends_on` matches who calls whom.
- [ ] Components and relays fit in offsets 0 to 8.
- [ ] `run.py up` starts cleanly three times in a row, and three copies run side by side on different port bases.
- [ ] `check_adapter` returns `[]` on a healthy copy.
- [ ] On a healthy copy, the checker stays green for five minutes, and `check_verdict` returns `[]` both with and without `since_t`.
- [ ] Each practice fault turns the checker red. Its labelled fix turns it green again (`oracle`), and doing nothing leaves it red (`noop`).
- [ ] No release label, log line, change detail or payload names a fault type or a class.
- [ ] The agent's files are unchanged: `python run.py hash` shows the same agent hash as before.

## 4. What stays the same for every system

- The agent: it imports nothing from any system, its code names no system's components, and its hash does not change.
- The six actions, the component kinds and the root-cause classes (`ic/contract.py`).
- `ic/kit/`. Every test system shares it, so a change to it changes the bank too. It has not changed since the exam was sealed: a change a new system needs waits until the final and robustness runs end, and is recorded in `DECISIONS.md` (CONTRACT 15).

A new system to run the exam on adds files only under `targets/<system>/`, `tests/<system>/`, `scenarios/` and `docs/`. `ic/systems.py` finds it by its folder.
