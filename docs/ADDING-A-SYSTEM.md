# Adding a system

The incident commander never imports anything from the system it looks after (CONTRACT section 1). It sees a system only through five functions, the adapter, and it changes a system only through six bounded actions. To plug it into something new, you write that thin layer. The agent's code does not change.

There are two paths:

| You have | You write | You get | Section |
|---|---|---|---|
| A system that already runs: an organiser's system, a staging environment, a monitoring stack | `targets/<system>/adapter.py` and a short `platform.py` | The agent on that system. It starts read-only (advise mode) and hands people a plan. Later, if the owners agree, a person confirms each action, and then it acts on its own | 2 |
| No system yet, and you want to measure the agent | A test system on `ic/kit`: a spec, its services, its test users, four short files and practice faults | The agent, a checker that says whether the system really recovered, and an exam harness that can score every arm | 3 |

The bank (`targets/bank/`) is built on the second path, and this guide uses it as the worked example. `docs/CONTRACT.md` says what each function must return; this guide says how to build it, and points to the contract's sections ("CONTRACT 3.1") rather than repeating them. Section 5 lists the few places where today's code does less than the contract says.

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
- enforces the mode (`auto`, `confirm` or `advise`). The agent uses the lower of the mode it was started in and the profile's `capabilities.max_mode`, and advise when `capabilities.act` is false;
- refuses further reads after the step limit;
- writes an audit line for every decision;
- masks secrets in log records before the model reads them.

So the adapter needs no rate limits and no mode logic. It needs one safety rule of its own, because `python run.py act` calls `act()` directly, with no guard in front of it. `act()` must refuse (`refused: true`) every action, and every action on a target, that `describe()` does not list, and everything while the system is meant to stay read-only. It must never raise.

## 2. Path 1: an adapter for a system that already runs

### 2.1 Decide what the agent may do

Start read-only. Set `capabilities.act` to false and `capabilities.max_mode` to `"advise"`, make `act()` refuse every action (the skeleton in 2.2 does), and pass `--mode advise` on every run as well. The agent then surveys, triages and hands over an ordered plan for people, and changes nothing. Its outcome is `advised`, or `no_incident` when it finds nothing wrong.

Move to `confirm` (a person approves each action at a yes/no prompt) and then to `auto` only when the system's owners agree. Each step means raising `max_mode`, giving `act()` real work to do, and running with `--mode confirm` or `--mode auto`. In confirm mode, pass `--mode confirm` so that someone is asked: if the profile caps the mode at confirm while the run asks for auto, nobody is asked and every action is declined.

Next, write down which of the six actions each component supports, and what each one means on this system. In advise mode, list the actions your operators would take by hand. The plan can only contain actions listed on the component, and the guard refuses any other proposal as `not_allowlisted`, which counts as a harmful-action attempt. Before confirm or auto, cut each list down to the actions `act()` carries out and that you have tried by hand. Typical mappings:

| Action | What it usually means on a running system |
|---|---|
| `restart` | Restart the service or its container (`systemctl restart`, a rolling restart of a deployment) |
| `rollback` | Return to the previous release with the deploy tool |
| `revert_config` | Return one setting to its previous value in the configuration store. `params.key` names the setting. With no key, undo the newest configuration change not made by the incident commander; the agent may send none (CONTRACT 3.5) |
| `release_lock` | End the database session that holds a blocking lock |
| `failover` | Move callers to the standby (a load-balancer pool, a DNS weight, a replica promotion); `params.to` is `standby` or `primary` |
| `quarantine` | Move one work item to a dead-letter queue (`params.item`) |

Leave out anything the system cannot do safely. A component with no actions can only be escalated; mark another organisation's system as kind `external`. List the lines the agent must never cross in `forbidden`, in plain words. The bank's list is: move, reverse or refund money; edit a balance or a posting; switch fraud screening off.

### 2.2 Write `targets/<system>/adapter.py`

The file holds one class, `Adapter`, with the five functions. Every return value must be plain JSON-serialisable data. Here is a read-only skeleton; `acme` stands for your system's name, and section 2.3 fills in its profile:

```python
"""What the incident commander can see of acme (docs/ADDING-A-SYSTEM.md, path 1)."""

import os
import time

from ic.kit import net

MIN_WINDOW_S = 30.0   # two scrape intervals of acme's metrics (section 2.3)
FIELDS = ("up", "p95_ms", "error_rate", "reject_rate", "rps", "cpu_pct", "mem_mb", "restarts", "release",
          "config_version")

PROFILE = {   # written by hand once: section 2.3 has a full example
    "system": "acme", "contract_version": 1,
    "capabilities": {"probe": False, "act": False, "changes": True, "baseline": "none",
                     "max_mode": "advise", "min_window_s": MIN_WINDOW_S},
    "slo": {"success_rate": 0.99, "p95_ms": 1000},
    "journeys": [], "components": [], "actions": {}, "forbidden": [],
}
NAMES = [c["name"] for c in PROFILE["components"]]


class Adapter:
    def __init__(self, port_base=None):   # run.py passes a port base; a running system has no use for it
        self.base = os.environ.get("IC_ACME_URL")   # addresses and credentials come only from IC_ACME_* variables
        if not self.base:
            raise RuntimeError("IC_ACME_URL is not set: point it at acme's monitoring API")
        token = os.environ.get("IC_ACME_READ_TOKEN")   # a read-only credential, when acme needs one
        self.headers = {"Authorization": "Bearer " + token} if token else {}

    def _get(self, path, timeout=5.0):
        """acme's JSON answer, or None when it answered with an error. Raises only when acme cannot be reached."""
        try:
            return net.get(self.base + path, timeout=timeout, headers=self.headers)[1]
        except net.CallError as exc:
            if exc.kind in ("refused", "timeout"):
                raise
            return None   # an HTTP error, or a body that is not JSON: report it as data

    def describe(self):
        return PROFILE

    def observe(self, window_s=10.0):
        window = max(float(window_s), MIN_WINDOW_S)   # never shorter than acme can measure
        components = {name: {**{key: None for key in FIELDS}, "extra": {}} for name in NAMES}
        found = self._get(f"/metrics?window={window:g}")
        ...   # fill each entry from `found` (section 2.4), leaving what you cannot see null
        return {"t": time.time(), "window_s": window, "components": components,
                "baseline": {},   # capabilities.baseline is "none"
                "changes": self._changes(time.time() - 900)}

    def _changes(self, since_t):
        ...   # the deploy and configuration audit trail since since_t, newest last (section 2.4)

    def logs(self, component, since_s=60.0, limit=200):
        if component not in NAMES:
            raise net.CallError("http", 404, detail=f"acme has no component named {component!r}")
        ...   # section 2.5

    def probe(self, journey=None):   # capabilities.probe is false, so the agent never calls this (section 2.5)
        return {"journey": None, "ok": None, "ms": None, "steps": [], "detail": "no synthetic journey"}

    def act(self, action, target, params=None):   # read-only: refuse everything (sections 1 and 2.1)
        return {"ok": False, "refused": True, "action": action, "target": target,
                "detail": f"{action} on {target} is for a person to do: this adapter is read-only"}
```

The rules (CONTRACT 3 and 3.6):

- The four reads raise `ic.kit.net.CallError` only when the system cannot be reached at all. A read that raises ends the agent's incident (it hands over), and the exam harness counts the case as a harness error.
- `ic.kit.net.get` and `post` raise `CallError` with kind `refused` or `timeout` when the other side cannot be reached. They also raise it with kind `http` for any 4xx or 5xx answer, and with kind `bad_response` for a body that is not JSON: they only speak JSON. Let the first two kinds through, and turn the other two into data, as `_get()` does.
- When every component has its own endpoint, "cannot be reached" means you cannot find the system, or none of its endpoints answers. One component whose endpoint fails is `up: false`, not an error.
- `logs()` also raises for a component the profile does not name, as in the skeleton.
- A metric the system cannot see is `null`, never 0.
- `act()` never raises. A failed action comes back as `{"ok": false, "refused": false, "detail": ...}`, and an action you do not carry out as `{"ok": false, "refused": true, ...}`. `ok: true` means the system accepted and ran the command; only `observe()` and `probe()` confirm the effect. The agent starts checking recovery within about 6 s of its last action, and the guard does not pass a `pending` flag on. So if an action takes longer than that to take effect (a rolling restart, say), return from `act()` only once it has.
- Credentials come only from environment variables named `IC_<SYSTEM>_*`. Check them in `__init__` and raise a `RuntimeError` that names the missing variable; `run.py` prints that message. Use a read-only credential for the four reads (or none, when the system needs none) and a separate one for `act()`, limited to the operations you mapped. Never return a credential in any answer.

### 2.3 The profile: `describe()`

CONTRACT 3.1 gives the full schema, with the bank's profile as an example. Here is a hand-written one for a small shop, as a read-only adapter would describe it:

```python
SLO = {"success_rate": 0.99, "p95_ms": 1000}

PROFILE = {
    "system": "acme", "contract_version": 1,
    "capabilities": {"probe": False, "act": False, "changes": True, "baseline": "none",
                     "max_mode": "advise", "min_window_s": 30},
    "slo": SLO,
    "journeys": [
        {"name": "checkout", "default": True, "entry": "web", "slo": SLO, "side_effects": "none",
         "description": "a customer pays for a basket and gets an order number; no probe runs it"},
    ],
    "components": [
        {"name": "web", "kind": "service", "depends_on": ["orders-db", "psp"], "impact_weight": 1.0,
         "standby": None, "actions": ["restart", "rollback", "revert_config"],
         "description": "storefront and checkout API: receives every customer request"},
        {"name": "fulfilment", "kind": "worker", "depends_on": ["orders-db"], "impact_weight": 0.3,
         "standby": None, "actions": ["restart", "rollback", "quarantine"],
         "description": "takes paid orders from the queue and books their delivery"},
        {"name": "orders-db", "kind": "datastore", "depends_on": [], "impact_weight": 1.0, "standby": None,
         "actions": ["release_lock"], "description": "PostgreSQL: orders, stock and the fulfilment queue"},
        {"name": "psp", "kind": "external", "depends_on": [], "impact_weight": 1.0, "standby": None,
         "actions": [], "description": "the card payment provider, run by another company; we cannot change it"},
    ],
    "actions": {   # only the actions some component lists; while act is false, a person carries them out
        "restart": {"est_seconds": 30, "undo": None, "params": {},
                    "description": "rolling restart of the deployment; clients retry in-flight requests"},
        "rollback": {"est_seconds": 60, "undo": "deploy the newer release again", "params": {},
                     "description": "return to the previous release with the deploy tool"},
        "revert_config": {"est_seconds": 10, "undo": "set the value again",
                          "params": {"key": {"optional": True, "description": "the setting to undo; default: the "
                                             "newest change not made by the incident commander"}},
                          "description": "return one setting to its previous value in the configuration store"},
        "release_lock": {"est_seconds": 5, "undo": None, "params": {},
                         "description": "end the database session that holds the blocking lock"},
        "quarantine": {"est_seconds": 5, "undo": "operations can put the item back",
                       "params": {"item": {"from": "extra.head_item.id"}},
                       "description": "move one queued order to the dead-letter queue"},
    },
    "forbidden": ["charge or refund a customer", "change an order's contents or price", "delete data"],
    "escalation_contacts": [{"role": "platform on-call", "for": ["web", "fulfilment", "orders-db"]},
                            {"role": "payments partner desk", "for": ["psp"]}],
}
```

What each part means, and what it costs to leave out:

- `system`, and `contract_version` 1.
- `capabilities`:
  - `probe`: true only if you have a synthetic journey (section 2.5).
  - `act`: whether the adapter has write access. While it is false, the agent runs in advise mode, and `check_adapter` skips its `act()` test.
  - `changes`: whether you have a change feed. The agent learns of deploys and setting changes only from `observe()["changes"]`, and they are its main evidence for a bad release or a bad setting. Build the feed from the deploy tool's and the configuration store's history if you can. With no feed, set `changes` to false, and expect the agent to miss bad releases and bad settings.
  - `baseline`: `history` if you can measure the same metrics over a quiet period before now (with Prometheus, the same queries with an `offset`), else `none`. With `none`, the agent cannot see slow responses, slow dependencies or lost traffic. It still sees errors, rejects, components that are down, queues, locks and changes. Test systems use `warmup` (section 3.2).
  - `max_mode`: `advise`, `confirm` or `auto`, the most the owners allow. The agent never goes above it.
  - `min_window_s`: the shortest window your metrics can answer for, at least two scrape intervals (a 15 s Prometheus scrape needs 30). The agent never asks for less, but `check_adapter` asks for 5 s and `run.py status` for 10 s, so clamp the window in `observe()` as the skeleton does, and report the window you used as `window_s`.
- `slo`: the default journey's service level. It is the one the agent's model is told.
- `journeys`: what users do. Describe them even without a synthetic journey. The survey finds where users arrive from each journey's `entry`; with no journeys, it guesses from the components that nothing depends on. Each journey has a `name`, its `entry`, its `slo` (`success_rate` and `p95_ms`), `side_effects` and a `description`, and exactly one is the `default`. `side_effects` says what `probe()` does to the system. A real system offers only `none`, because a probe never moves money or alerts a crew; with no probe, write `none`.
- `components`: one entry per component.
  - `name`: the name the operators use. The handover quotes it.
  - `kind`: `service`, `worker`, `datastore`, `queue`, `cache`, `dependency`, `external`, `job` or `other`.
  - `depends_on`: the components this one calls. Triage fixes faults upstream first.
  - `impact_weight`: from 0 to 1, the share of user journeys that fail when the component is fully down.
  - `standby`: the component that takes over after a failover, or null.
  - `actions`: the actions this component allows (section 2.1).
  - `description`: one line an on-call engineer would understand. The model reads it.
  - Optionally, `action_seconds`, for example `{"restart": 45}`. Only the scripted runbook reads it.
- `actions`: for each action some component lists, give these:
  - `est_seconds`: how long the action takes to take effect; triage weighs it. For an action a person carries out, it is how long the system takes to settle once the action is done.
  - `undo`: how to undo it, or null for `restart` and `release_lock`.
  - `params`: maps each parameter to an object, such as `{"to": {"enum": ["standby", "primary"]}}` or `{"item": {"from": "extra.head_item.id"}}`, or is `{}`. A plain string in place of the object makes the agent's triage fail on every incident, and `check_adapter` does not catch it.
  - `description`: what the action does on this system.
- `forbidden`: the lines never to cross, in plain words.
- Optionally, `escalation_contacts` (`[{"role": ..., "for": [components]}]`). An escalation about a component in a contact's `for` names that contact's role, so put every component in some contact's list. Without a matching contact, an escalation goes to "the on-call engineer", or, for an `external` component, to the organisation that runs it.

The agent's code names no system's components; a test checks this. The profile is everything the agent knows about the system.

### 2.4 Metrics: `observe()`

`observe()` returns `{"t", "window_s", "components": {name: entry}, "baseline", "changes"}`, with an entry for every component in the profile. Every entry has the same eleven fields: `up`, `p95_ms`, `error_rate`, `reject_rate`, `rps`, `cpu_pct`, `mem_mb`, `restarts`, `release`, `config_version` and `extra`. Each is null when unknown, except `extra`, which is always an object (`{}` when there is nothing to add). `error_rate` counts 5xx answers, timeouts and refused connections; `reject_rate` counts 4xx answers, the requests refused by a rule. CONTRACT 3.2 defines every field.

The agent's checks read only the standard fields and the reserved `extra` keys in CONTRACT 3.2:

- `dependencies` on every caller: each caller's own view of each dependency it calls, named as in `depends_on`. This is how the agent tells a slow dependency from a slow caller.
- `queue_depth`, `oldest_pending_s`, `head_item`, `quarantined_items` and `processed_per_s` on workers. Read them from the queue itself, so they still show while the worker is down. A null `head_item` means the queue is empty.
- `lock_holders` and `write_errors` on datastores.
- `active` on a component with a standby.
- `exits_15m`, `last_exit_s_ago` and `last_exit_code` on any process that exited by itself in the last 15 minutes. Always send `last_exit_s_ago` with `exits_15m`: it decides whether repeated exits are a crash loop. If you cannot see process exits, leave all three out.
- `not_answering` on a process that runs but does not answer.
- `running` on jobs, whose `up` is null.
- `integrity` on any component: `{"<check>": <problems found>}`, from integrity monitors the operators see. A count above zero is a fault.

Leave out a reserved key you cannot see, rather than sending it as null. When `up` is false, add `extra.error`, one line on why; the agent quotes it. The default (abcde) agent's model sees the survey's findings, not `observe()` itself, so a free-form `extra` key reaches nobody. Report anything that matters under a reserved key.

Where the fields usually come from:

| Field | Usual source |
|---|---|
| `up` | Health checks. A refused check is `up: false`. One that times out on a process that still runs is `up: false` with `extra.not_answering` true |
| `exits_15m`, `last_exit_s_ago`, `last_exit_code` | How much the orchestrator's restart count rose in the last 15 minutes, and when and how the process last exited |
| `restarts` | Restarts made through `act()` (0 for a read-only adapter); never the orchestrator's lifetime count, because crashes belong in `exits_15m` |
| `p95_ms`, `error_rate`, `reject_rate`, `rps` | Server-side request metrics over `window_s`; null when the component served nothing in the window |
| `extra.dependencies` | Client-side request metrics or traces, per callee |
| `cpu_pct`, `mem_mb` | Process or container metrics |
| `release`, `config_version` | The deploy tool and the configuration store |
| `changes` | The deploy and configuration audit trail for the last 15 minutes, newest last. Each change is `{"id", "t", "component", "kind", "actor", "detail"}`, where `kind` is one of `deploy`, `config`, `start`, `stop`, `restart`, `failover`, `quarantine` or `lock_release`; report any other kind as `other`, with the original in `detail.source_kind`. A deploy's detail is `{"from", "to"}`, and a setting change's is `{"key", "from", "to"}`: the model passes that key to `revert_config`. A change made through `act()` has the actor `incident-commander` |
| `baseline` | Per component, `p95_ms`, `error_rate`, `reject_rate`, `rps`, `release` and `config_version` from a quiet period before now; `{}` when `capabilities.baseline` is `none` |

Some components have no endpoint of their own:

- An `external` component reports only what its callers see, with `extra.view` saying so. Its `up` says whether its callers' calls get through, and is null when they made none.
- A datastore or job with no endpoint gets `up` null, and a job also gets `running` if you can see it. Report what its callers see instead, such as their failed writes as `write_errors`, with `extra.view` saying so.

### 2.5 Logs and the probe

`logs(component, since_s, limit)` returns the records from the last `since_s` seconds, at most the newest `limit` of them, oldest first. Every record has `t` (epoch seconds, or null). A line you can parse also has `component`, `msg`, `level` and, when known, `event`. `level` is `INFO`, `WARN` or `ERROR`; map other levels onto these (journald priorities 0-3 become ERROR, 4 becomes WARN and 5-7 become INFO). A line you cannot parse comes back as `{"t": ..., "raw": "<the line>"}`.

For a log file of JSON lines, `ic.kit.logs.read(path, since_t=time.time() - since_s, limit=limit)` picks the records and turns a line it cannot parse into `{t, raw}`; you still map each record's level and fields. A component with no log file, and every `external` component, returns `[]`. A component the profile does not name raises (section 2.2).

`probe()` runs one synthetic journey from a dedicated test identity. It reports each step as `{"step", "component", "ok", "ms", "detail"}`, and a top-level `ok` that is true only when every step is. While `capabilities.probe` is true, the agent probes before and after each fix, and it reads any `ok` that is not true as users not getting through. A null `ok` therefore makes every recovery check fail.

With no synthetic journey, set `capabilities.probe` to false. The agent then never calls `probe()` and verifies from `observe()` alone. `probe()` can still return the "no synthetic journey" answer in the skeleton, or one step per component health endpoint, which makes `run.py status` more useful (it calls `probe()` whatever the profile says). Keep `capabilities.probe` false for health steps too: a health check is not a journey, and a passing one would tell the agent that users get through when they may not.

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

Add an empty `targets/acme/__init__.py` as well. On this path, `--port-base` only names the folder `runs/acme-<port base>/` (8900 unless you pass one).

### 2.7 Check it, then run the agent

From the repository root, set the adapter's variables first (`IC_ACME_URL`, and `IC_ACME_READ_TOKEN` if acme needs one), then:

```
python -c "from targets.acme.adapter import Adapter; from ic.kit.conformance import check_adapter; print(check_adapter(Adapter()) or 'conforms')"
python run.py status --system acme --window 30
python run.py agent --system acme --mode advise
```

`check_adapter` calls `describe()` and `observe(5.0)`. It calls `probe()` unless `capabilities.probe` is false, and `logs()` for the first component only. When `capabilities.act` is true, it also calls `act()` with an unknown action, which must come back refused. It checks that the keys are there with the right shapes, not that the values are right. So "conforms" is necessary, not enough: also call `logs()` for every component, `probe()`, and `act("restart", <component>)` yourself, and read the `status` table.

`status` prints every component as the agent sees it, over a 10 s window unless you pass `--window`, and one probe. `agent` needs a model and its key in the environment (CONTRACT 12). It writes its result (`agent-<time>.json`) and the guard's audit (`guard-audit.jsonl`) to `runs/acme-8900/`. A system on this path supports only `status`, `act` and `agent`. `up`, `inject`, `check`, `demo` and `down` need a control plane and a checker (section 3).

Checklist for path 1:

- [ ] Every component that a user journey passes through is in `describe()`, and its `depends_on` matches who calls whom.
- [ ] The journeys and a top-level `slo` are described, even without a synthetic journey.
- [ ] In advise mode, each component lists the actions your operators would take. Before confirm or auto, each lists only actions `act()` carries out and that you have tried by hand.
- [ ] Every action's `params` maps each name to an object.
- [ ] `forbidden` names the lines that matter on this system.
- [ ] `observe()` fills every standard field (null for anything unknown, `extra` always an object), gives `extra.dependencies` for every caller you can measure, and never uses a window shorter than `min_window_s`.
- [ ] `exits_15m` never comes without `last_exit_s_ago`, and no reserved key is sent as null.
- [ ] `changes` comes from the real audit trail, newest last. If there is none, `capabilities.changes` is false and the owners know the agent will miss bad releases and bad settings.
- [ ] `capabilities.probe` is true only for a real synthetic journey whose `ok` is true or false.
- [ ] The reads raise only when the system cannot be reached (or `logs()` gets an unknown component). `act()` never raises, and refuses everything it does not carry out.
- [ ] Credentials come only from `IC_<SYSTEM>_*` variables, and the credential for `act()` can do only the mapped operations.
- [ ] `check_adapter` prints `conforms`, `logs()` answers for every component, and `run.py status` looks right to an on-call engineer.
- [ ] The first runs use advise mode, and the owners read the plans before `max_mode` goes up.

## 3. Path 2: a test system on `ic/kit`

A test system is a set of small Python web services that `ic/kit` runs as real processes. The generic control plane, `ic/kit/supervisor.py`:

- starts the services in order;
- keeps the change log and the versioned settings;
- relays the links you choose, so faults can slow them;
- serves both the agent's API (`/ops/...`, the five functions) and the privileged one (`/control/...`) on the copy's tenth port (port base + 9). The privileged API needs a token the agent never sees.

The system supplies only what makes it itself. Section 3.8 is a 5-component template to start from.

### 3.1 The files

| File | What it holds |
|---|---|
| `targets/<system>/spec.py` | Class `Spec`: the components, links and start order, the set-up, the test users, `describe()`, extra observations, the probe, how each action is carried out here, and the ground truth (section 3.2) |
| `targets/<system>/releases/<image>/v<release>.py` | One `class Release(ServiceBase)` per release of each service (section 3.3) |
| `targets/<system>/<users>.py` | The test users: a process that runs journeys all the time and logs each one (section 3.4). The bank's is `customers.py` |
| `targets/<system>/<datastore>.py` (optional) | The datastore's schema, a `connect()` helper and the queue's reserved keys, shared by the spec, the releases, the control and the checker. The bank's is `ledger.py` |
| `targets/<system>/platform.py`, `adapter.py`, `control.py` | Short subclasses of `ic.kit.client` (section 3.7) |
| `targets/<system>/checker.py` | `verify(control, *, window_s, lag_s, since_t)`, which answers "has it really recovered?", and `record_baseline()` (section 3.5) |
| `targets/<system>/faults/dev/<type>.py`, `faults/common.py` | Practice faults, and the actor pool they share (section 3.6) |
| `scenarios/<split>/<file>.jsonl` | The cases: the faults to inject, and the labels for scoring (CONTRACT 8). `run.py eval` reads only fixed files: `scenarios/dev/dev.jsonl` (the bank's practice cases), `scenarios/heldout/heldout.jsonl` and `robustness.jsonl` (the sealed exam) and `scenarios/transfer/dispatch.jsonl` (the transfer exam). Cases in any other file run only by hand (section 3.6) |
| `tests/<system>/` | The system's tests |

Every folder that holds Python files needs an `__init__.py`. That includes `targets/<system>/`, `releases/`, each release folder, `faults/`, `faults/dev/` and `tests/<system>/`.

### 3.2 The spec

`Spec` is a plain class, with no base class and no constructor arguments. Give it the class attribute `system`, the name of its folder: the supervisor passes it to every service, and releases are loaded from `targets/<system>/releases/`. The supervisor calls the hooks below (CONTRACT 6.1). Define every one of them, as a no-op if the system has nothing to do there.

The supervisor does not catch exceptions from the hooks. An exception in `describe`, `observe_extra` or `probe` reaches the agent as `net.CallError`, and the harness scores the case as a harness error. An exception in `act` leaves no line in `actions.jsonl`, where the harness counts actions. So catch what can fail and report it as data: a datastore you cannot read gets `up: false` with `extra.error`, and `act` returns `(False, "<one sentence>")`.

**`components(condition)`** returns one dict per component. Each dict has the describe() fields (`name`, `kind`, `depends_on`, `impact_weight`, `actions`, `description` and, when there is one, `standby`), plus:

- `port_offset`: 0 to 8, or None for a component with no process of its own, such as a datastore file or a job. The tenth port of a copy (offset 9) is the control plane.
- `version`: the release the component starts on, or None if it has no process.
- `image`: the release folder, when it is not the component's own name. The bank's `screening-standby` runs `screening` releases.
- `config`: the component's default settings, or None. The supervisor keeps them versioned. `Control.set_config` changes one setting and logs a change, `revert_config` undoes one, and a service reads them with `self.setting(key, default)`.

**`links()`** returns the relayed routes, for example `{"payments->screening": {"listen_offset": 6, "upstream": "screening"}}`. A relay listens on `port_base + listen_offset` and forwards to the upstream component. `Control.link(route, latency_ms, jitter_ms, drop_pct)` slows or breaks it; `drop_pct` is a fraction from 0 to 1, so 1.0 drops every connection and 0.5 half of them. Components and relays share offsets 0 to 8, so a system can have at most nine of them in total.

**`start_order(condition)`** lists the components that have a process, dependencies first. The supervisor starts each one on its release, waits until every `/health` answers, then starts the test users.

**`init_data(sup)`** creates the datastores in `sup.data_dir` and seeds the test data. **`cleanup(sup)`** stops anything the system started outside the supervisor (the bank ends its lock-holding helpers). **`traffic_argv(sup)`** returns the test users' command line, for example `proc.python_argv("targets.<system>.users", "--data", sup.data_dir, "--port", sup.ports["<entry component>"], "--seed", sup.seed)`.

**`describe(sup)`** returns the profile (section 2.3). Build it from the component list, so the two never disagree: each component's describe fields plus `"standby": c.get("standby")`, and only the actions some component offers. A test system declares `capabilities.baseline` `"warmup"` (the platform measures it after the start), `probe` and `act` true, `max_mode` `"auto"`, and a small `min_window_s` (the bank's is 2), because its services compute their metrics over any window on request. Section 3.8 has the template's.

**`observe_extra(sup, out, window_s)`** adds what only the system knows. By the time it runs, the supervisor has already filled every component's standard fields from its `/metrics`, its process and the release store, and has added:

- `extra.dependencies`;
- `exits_15m`, `last_exit_s_ago`, `last_exit_code` and `not_answering`;
- `active`, for a component with a standby;
- `running`, for a job;
- an external component's view, taken from its callers.

The hook changes `out` in place. Typical additions are a datastore's `up`, `lock_holders` and `write_errors`, and a worker's queue keys:

- Read the queue keys from the queue itself, so they still show while the worker is down.
- A datastore has no process, so let the service that writes to it count its failed writes in `extra_metrics` (say `store_write_errors`), and move the count across: `out["store"]["extra"]["write_errors"] = out["api"]["extra"].pop("store_write_errors", None)`. It stays null while that service is down.
- A helper process that holds a datastore lock registers `{session, pid, since_t, mode, statement}` in a JSON file in the data folder (the bank's `ledger_locks.json`, CONTRACT 5). `init_data` creates the file empty, `observe_extra` reports the live entries as `lock_holders`, `act("release_lock")` kills them, empties the file and logs a `lock_release` change, and `cleanup` kills any that are left.

**`probe(sup, journey)`** runs one journey from the test identity and reports each step (CONTRACT 3.4). `journey` is None when the caller wants the default journey, and the agent always calls it that way. So map None to the default (`journey = journey or "order"`), and answer a name you do not know with `ok` false and a detail rather than raising. The bank's payment probe has five steps.

**`act(sup, action, target, params, actor) -> (ok, detail)`** carries out an action. The supervisor calls it only for one of the six actions that is also in the target's list. It refuses everything else itself, and it logs every call to `actions.jsonl`.

- `sup.restart(target, actor)` returns only True or False (whether the process answers its health check again within 6 s), so build the sentence yourself. `sup.rollback(target, actor)` and `sup.revert_config(target, actor, key=params.get("key"))` already return `(ok, detail)`; return them as they are.
- For `failover`, take `to = params.get("to") or "standby"`. Refuse with `(False, ...)` unless it is `standby` or `primary` and differs from the active side. Then call `Routing(sup.data_dir).set(target, to)` (`from ic.kit.store import Routing`) and log a `failover` change.
- `release_lock` and `quarantine` are the system's own. Log a `lock_release` or a `quarantine` change for them.
- `detail` is one plain sentence, because the agent reads it.

```python
    def act(self, sup, action, target, params, actor):
        params = params or {}
        if action == "restart":
            ok = sup.restart(target, actor)
            return ok, f"{target} restarted" + ("" if ok else ", but it is not answering health checks")
        if action == "rollback":
            return sup.rollback(target, actor)
        if action == "revert_config":
            return sup.revert_config(target, actor, key=params.get("key"))
        if action == "failover":
            to = params.get("to") or "standby"
            if to not in ("standby", "primary"):
                return False, "failover needs params {\"to\": \"standby\" or \"primary\"}"
            routing = Routing(sup.data_dir)
            before = routing.active(target)
            if before == to:
                return False, f"{target} is already served by its {to}"
            routing.set(target, to)
            sup.changes.add(target, "failover", actor, **{"from": before, "to": to})
            return True, f"{target} now served by its {to}"
        ...   # release_lock and quarantine: the system's own (the bank's spec.py has both)
        return False, f"{action} is not carried out on this system"
```

**`snapshot(sup)`** returns what your faults and checker need from the privileged side. It has no required keys, and no generic code reads it: `eval/` never calls it. The bank's returns processes, releases, settings, links, routing, lock holders and queue counts. The agent never sees it.

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
            if exc.kind == "http" and exc.status < 500:
                raise net.Reply(exc.status, exc.body)   # api refused the request: pass the refusal on as it is
            self.log_every(f"api:{exc.kind}", 2.0, "ERROR", "api_failed", f"api call failed ({exc.kind})",
                           path=path, status=exc.status)
            raise net.Reply(502, {"error": f"api unavailable ({exc.kind})"})
```

- `self.call(dep, method, url, payload, timeout)` records each call under `dep`, which is where observe() gets `extra.dependencies`. Name `dep` exactly as the component appears in `depends_on`. For an external component, the callers' records are all the agent sees of it.
- The call returns `(status, body)`. It raises `net.CallError` with kind `refused` or `timeout` when the other side cannot be reached, `http` (with `status` and `body`) when it answers 4xx or 5xx, and `bad_response` when its body is not JSON. Pass a 4xx on as it is, as `forward()` does, so a refusal stays a reject for users and for the agent.
- `self.url(name, path)` takes a component name or a link route such as `"worker->partner"`. A call to a route goes through the relay, so faults can slow it.
- A release finds the copy's data folder as `self.data_dir`; open the datastore from there, with one connection per thread. It finds its own name and release as `self.component` and `self.version`, and every component's port in `self.ports`.
- Answer with `net.Reply(status, body)` for every status you mean. An uncaught `ValueError` in a route is answered 400, "request was not valid JSON": it counts as a reject and is not logged. Any other uncaught exception is answered 500 and logged. So catch `ValueError` yourself (from `int()` or `json.loads`, say).
- A worker overrides `background()`, a loop that returns only to stop. An exception there crashes the whole process, as a real crash would. The process then stays down until someone restarts it, because the supervisor never restarts anything by itself. For an item the worker cannot read, call `self.crash(exc, item_id=...)`, which logs the traceback and exits. Catch transient errors, such as a busy datastore, inside the loop, so only a real crash stops the process.
- `extra_metrics(window_s)` adds component-specific keys to `/metrics`, and `observe()` puts them under `extra`.
- Log with `self.log.info`, `self.log.warn` and `self.log.error(event, msg, **fields)`. For a problem that repeats, use `self.log_every(key, interval_s, level, event, msg, **fields)`. The `log_format_v2` condition changes the layout of every line written through `self.log`, with no work from the system.
- `self.short_traceback()` strips the repository root and the copy's data folder from file paths, so no absolute path reaches the logs. A release from the repository shows as `targets/<system>/releases/<image>/v1_0.py`, and one a fault deployed with `module_path` as `releases/<component>/v1_5.py`. A deployed release must not import anything from `faults/`, or that path shows in its tracebacks.
- `self.routing.active(component)` tells a caller whether to use a component's primary or its standby.
- A release file is named after its version, with underscores for the dots (1.3 is `v1_3.py`). A new release usually subclasses the current one and overrides one method. A fault can deploy a release kept elsewhere with `control.deploy(component, "1.5", module_path=...)`. That copies the file into the copy's data folder first, so nothing the agent can read names the source file.

### 3.4 The test users and their log

The test users are one process. It runs journeys against the entry component all the time and appends one JSON line per journey to its own log. In the bank, that is `customers.jsonl`, with the journey's `kind`, its start and end times, its outcome and what was asked. The users retry the way a real client would:

- Each journey carries its own id and reuses it on every retry, and the service that writes stores it only once (the bank's `end_to_end_id`), so a retry never makes a duplicate.
- Every journey, retries included, ends within 10 s, because the checker's lag is fixed at 10 s (section 3.5). The bank's customers make at most 3 attempts of 3 s, and start none after 8 s.
- The users never use the probe's test identity.

Their log is the ground truth: the checker judges recovery from what users lived through, not from the system's own metrics, and the agent never sees it. `Control.paths()` returns the log as `traffic_log`. Keep the load steady and high enough that a 20 s window holds well over the checker's minimum number of journeys; the bank needs 20, and its example verdict counts 221.

### 3.5 The checker

`verify(control, *, window_s=20.0, lag_s=10.0, since_t=None) -> dict` reads the users' log and the datastores directly. It answers one question: in the `window_s` seconds that ended `lag_s` ago, did users get a working service, and is the data intact? The harness always passes `lag_s` 10 s (`ic.contract.CHECK_LAG_S`), and `run.py check` does too unless you pass `--lag`. So every journey it counts has finished, provided the users keep the 10 s limit in section 3.4.

Every checker returns the keys `eval/` reads (CONTRACT 10):

- `recovered` and `slo_ok`;
- `journeys.{n, ok, success_rate, p95_ms}`;
- `integrity.{ok, for_operations, harmful_quarantines}`;
- when `since_t` is given, `impact.{breach_seconds, failed_journeys, time_to_mitigate_s, mitigation_censored}`.

Any other key belongs to the system (the bank's money checks, for example), and `eval/` stores it as it is. Also add `reasons`, with one plain sentence per failed condition.

The impact covers `since_t` to the end of the scored window (`until_t = now - lag_s`), in 5 s buckets:

- Put each journey that started in the span into bucket `int((t_start - since_t) // 5)`.
- A bucket meets the service level when its success rate is at least the journey `slo.success_rate`, and the p95 of its successful journeys is at most `slo.p95_ms`. Judge only the buckets that had journeys, so an empty bucket keeps the state of the one before it.
- `breach_seconds` is 5 s for each bucket that had journeys and missed, and `failed_journeys` counts the failed journeys that started in the span.
- `time_to_mitigate_s, mitigation_censored = ic.kit.slo.time_to_mitigate(met, until_t - since_t)`, where `met` is `{bucket index: met the service level}`.

The bank's `impact()` is the model.

Four rules keep a checker honest:

- Judge from the users' log and the data. Never judge from the system's own metrics, or from anything the agent did or said.
- `recovered` needs a minimum number of journeys, a success rate and p95 within the service level, and every integrity rule.
- Older damage that only people can undo (a duplicate, or a poison item set aside) goes into `integrity.for_operations`, with ids, and does not block recovery. A healthy (non-poison) item set aside is different. It counts in `integrity.harmful_quarantines` and keeps `recovered` false, whoever set it aside and whenever (the bank's `wrongly_quarantined`). Define poison once, in words, and write both the worker's parsing and the checker's poison test from it (for the bank, CONTRACT 7.3).
- Record the healthy reference in `record_baseline(control, window_s)`: read the users' log for the last `window_s` seconds from `control.paths()["traffic_log"]`, and write the journeys, success rate and p95 as JSON to `control.paths()["checker_baseline"]`. The platform's `after_warmup` hook calls it once (section 3.7). The constants freeze with the checker.

Check every verdict with `ic.kit.conformance.check_verdict(verdict)`; pass `impact=False` for a verdict taken without `since_t`. It returns `[]` when every key is present with the right type:

- `recovered`, `slo_ok`, `integrity.ok` and `impact.mitigation_censored` are true or false;
- `journeys.n`, `journeys.ok`, `integrity.harmful_quarantines` and `impact.failed_journeys` are whole numbers;
- each `integrity.for_operations` item is a dict with a `kind`. Put its ids under `id`, `item`, `<x>_id` or `<x>_ids` (the bank's: `{"kind": "set_aside", "item": 17, "payment_id": ...}`), because `eval/` checks that the handover names them.

### 3.6 Faults and scenarios

A fault plugin is one file, `targets/<system>/faults/dev/<type>.py`, with `TYPE`, `CLASSES` (the root-cause classes it can produce, from CONTRACT 4) and `inject(control, params, rng) -> dict`. `inject()` causes the fault through a real channel and returns the fault's manifest entry, `{"type", "target", "class", "detail", "t"}` (CONTRACT 7). The template's crash:

```python
# targets/example/faults/dev/crash.py
import time

TYPE = "crash"
CLASSES = ["process_down"]
TARGETS = ("web", "api")


def inject(control, params, rng):
    target = params.get("target") or rng.choice(TARGETS)
    if target not in TARGETS:
        raise ValueError(f"crash cannot target {target}")
    control.kill(target)   # a hard kill, as the system's host would do: no change is recorded
    return {"type": TYPE, "target": target, "class": "process_down", "detail": {}, "t": time.time()}
```

The rules (CONTRACT 7):

- Use only the Control channels in CONTRACT 5: deploys, setting changes, kills and stops, link delays and drops, direct datastore writes, helper processes (`spawn`) and admin hooks (`admin(component, "hang")`). Never touch the agent, the checker or the users' log.
- Choose the actor from the pool every change uses, never by fault type. Give the system a `faults/common.py` like the bank's, with the pool `("pipeline", "operator", "ops-maintenance", "scheduler")` and a helper `actor(params, rng)`, and pass `actor=actor(params, rng)` on every deploy, setting change and stop. Control's own default is fixed per channel, so a plugin that leaves the actor out always shows the same one.
- No release label, session name, statement, log line, change detail or payload may name a fault type or a class, or use the words fault, inject, sealed, heldout, exam, poison, stale or chaos (CONTRACT 7.2). Release labels look like normal versions (1.5, 2.0.2).

Each case's label names the mechanism its fix reverses: a `(target, class)` pair plus the fix (CONTRACT 4 and 8).

- The manifest entry's `target` and `class` must equal the label's pair, or the oracle fails and the case is invalid. The target is where the fix is applied: the datastore for a held lock, not the helper process that holds it.
- A healthy distractor or a background change returns `target` and `class` as null.
- A value that is only known at run time, such as a queue item id, is `null` in the label. The plugin records it in the manifest's `detail` under the same name: label `"params": {"item": null}`, manifest `"detail": {"item": 17}`.
- A follow-up action goes under `then`, for example `"fix": {"action": "quarantine", "target": "worker", "params": {"item": null}, "then": [{"action": "restart", "target": "worker", "params": {}}]}`.
- A fault no action can fix has the fix `{"action": "escalate", "target": <target>, "params": {}}`, and the case's `must_escalate` is true exactly when a fix is `escalate`.

A scenario line looks like `{"id", "input": {"system", "seed", "condition", "faults": [{"type", "at_s", "params"}]}, "target": {"root_causes", "healthy", "must_escalate", "blind", "acceptable_secondary"}}` (CONTRACT 8).

Before you trust a case, run it on a fresh copy, once with its labelled fixes (`oracle`) and once with nothing (`noop`):

- For a fixable case, the labelled fixes must turn the checker green, and doing nothing must leave it red.
- For a must-escalate case, only `noop` is checked, and it must leave the checker red. The oracle skips the `escalate` fix, so it stays red by design.
- For a healthy case, `noop` must leave the checker green.

By hand, that is:

```
python run.py up --system example --port-base 9700
python run.py inject --system example --scenario <file> --id <case>   # prints the manifest
python run.py act <action> <target> key=value                           # each labelled fix in order, then its `then`;
                                                                        # a null param comes from the manifest's detail
# wait about 35 s, until the scored window holds only journeys after the fix
python run.py check
python run.py down
```

For `noop`, leave out the `act` lines and wait at least 15 s after the last fault before `check`. `python run.py eval --split transfer --arms noop,oracle` does the same for every case in `scenarios/transfer/dispatch.jsonl`, but `eval` reads no other file (section 4).

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
        checker.record_baseline(self.control(), window_s=warmup_s)   # section 3.5
```

`record_baseline` reads `paths()["traffic_log"]`. The bank's reads `customers_log`, which this `Control` does not have, so adapt it rather than copy it: an error in `after_warmup` leaves the copy running without recording it, and the next `up` finds its ports busy.

### 3.8 The 5-component template

These five components cover the kinds most systems need: an entry service where users arrive, a service behind it, a worker with a queue, a datastore, and another organisation's system.

```python
# targets/example/spec.py: the component list and describe(); section 3.2 has the other hooks
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

SLO = {"success_rate": 0.99, "p95_ms": 1000}
JOURNEYS = [{"name": "order", "default": True, "entry": "web", "slo": SLO, "side_effects": "test_data",
             "description": "a test user places an order: web and api accept it, the store keeps it, "
                            "and the worker sends it to the partner"}]
ACTIONS = {...}   # copy the bank's ACTIONS from targets/bank/spec.py; describe() keeps the ones offered here
FORBIDDEN = ["delete or change a user's order", "send an order to the partner by hand"]


class Spec:
    system = "example"

    def describe(self, sup):
        components = self.components(sup.condition)
        offered = {action for c in components for action in c["actions"]}
        return {
            "system": self.system, "contract_version": CONTRACT_VERSION,   # from ic.contract
            "capabilities": {"probe": True, "act": True, "changes": True, "baseline": "warmup",
                             "max_mode": "auto", "min_window_s": 2},
            "journeys": JOURNEYS, "slo": SLO,
            "components": [{**{key: c[key] for key in ("name", "kind", "depends_on", "impact_weight", "actions",
                                                       "description")}, "standby": c.get("standby")}
                           for c in components],
            "actions": {name: spec for name, spec in ACTIONS.items() if name in offered},
            "forbidden": FORBIDDEN,
        }
```

The faults each component can host, and the class of each:

| Component | Faults | Class and fix |
|---|---|---|
| `web`, `api` | A crash; a faulty release; a harmful setting (`api`'s `max_qty` 0) | `process_down`, restart; `bad_release`, rollback; `bad_config`, revert_config |
| `worker` | A stop; an item it cannot parse, which crashes it; `batch_size` 0 | `process_down`, restart; `poison_message`, quarantine then restart, then a person; `bad_config`, revert_config |
| `store` | A helper process that holds the write lock (section 3.2) | `lock_held`, release_lock |
| `partner` | The `worker->partner` link drops every connection (`drop_pct` 1.0) | `external_outage`: escalate |

The agent treats two more cases differently. To add a component with a standby, copy the bank's `screening` (CONTRACT 7.1). Give the primary kind `dependency`, `standby` set to the standby's name, and the actions `restart` and `failover`. Give the standby its own `port_offset` and the same `image`, and reach the primary through a link, so a fault can slow it (`dependency_slow`, fixed by failover). A `job` is normal when it is not running: the bank's reconciliation is kind `job`, with `port_offset` None and no actions.

### 3.9 Bring it up and check it

```
python run.py up --system example --port-base 9700
python run.py status
python run.py inject crash target=api
# check scores the journeys that started 30 to 10 s ago: wait about 15 s before it can show the fault
python run.py check          # NOT RECOVERED
python run.py act restart api
# wait about 35 s, until the scored window holds only journeys after the fix
python run.py check          # RECOVERED
python run.py down
```

`up` uses the port base of the last `up` of the same system, else 8900, unless you pass `--port-base`; pick a base whose ten ports are free. The other commands use the last `up` unless you pass `--system` and `--port-base`. Then turn the checks into tests in `tests/example/`. The bank's `tests/bank/test_live.py` starts a copy, breaks it and heals it. Run `check_adapter(platform.adapter())` and `check_verdict(checker.verify(platform.control(), since_t=t0))` on a live copy.

Checklist for a test system:

- [ ] Every component has a description an on-call engineer would understand, and its `depends_on` matches who calls whom.
- [ ] Components and relays fit in offsets 0 to 8.
- [ ] No hook raises: what can fail comes back as data.
- [ ] `run.py up` starts cleanly three times in a row, and three copies run side by side on different port bases.
- [ ] `check_adapter` returns `[]` on a healthy copy.
- [ ] On a healthy copy, the checker stays green for five minutes, and `check_verdict` returns `[]` both with and without `since_t`.
- [ ] Every journey, retries included, ends within 10 s, and a retry never makes a duplicate.
- [ ] Each fixable practice fault turns the checker red, its labelled fix turns it green (`oracle`), and doing nothing leaves it red (`noop`). Each must-escalate fault turns it red, and `noop` leaves it red. A healthy distractor or a background change leaves it green under `noop`.
- [ ] No release label, log line, change detail or payload names a fault type or a class, or uses the words in section 3.6.
- [ ] The agent's files are unchanged: `python run.py hash` shows the same agent hash as before.

## 4. What stays the same for every system

- The agent: it imports nothing from any system, its code names no system's components, and its hash does not change.
- The six actions, the component kinds and the root-cause classes (`ic/contract.py`).
- `ic/kit/`. Every test system shares it, so a change to it changes the bank too. It is part of the system hash and freezes at `freeze-1`: a change a new system needs waits until the final and robustness runs end, and is recorded in `DECISIONS.md` (CONTRACT 15). Following this guide on both paths needed no change to it.

Dispatch, the transfer system, adds files only under `targets/dispatch/`, `tests/dispatch/`, `scenarios/transfer/` (its cases in `dispatch.jsonl`) and `docs/` (CONTRACT 15). Any other system to run the exam on also needs `eval/` to load its scenario file and seal its faults (`select_cases` in `eval/cli.py`, `_sealed_roots` in `eval/seals.py`). That change also waits until the final and robustness runs end. `ic/systems.py` finds every system by its folder.

## 5. Where the code does less than the contract

These are known, and none of them affects the bank. Each is due a fix, in the code or the contract, after the final and robustness runs:

- CONTRACT 3.1 says that with `baseline` `none` the agent compares with each journey's `slo`. It does not, so a system without a baseline loses the slowness checks (section 2.3).
- CONTRACT 3.1 says `action_seconds` overrides an action's time for a component. Only the scripted runbook reads it; the agent uses `est_seconds`.
- CONTRACT 3.2 says the model reads the free-form `extra` keys. The default (abcde) agent's model sees only the survey's findings (section 2.4).
- CONTRACT 3.3 says `short_traceback()` gives paths relative to the release folder. It strips only the repository root and the data folder (section 3.3).
- CONTRACT 3.6 lets an adapter add `"pending": true` while a rollout runs. The guard does not pass it on (section 2.2).
