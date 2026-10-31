# Dispatch: the test dispatch centre

Dispatch is the second test system. It is a simulated 9-1-1 dispatch centre that runs on `ic/kit`, like the
bank, behind the same adapter. This document gives the facts about it that an incident needs: what runs, what
the users do, what the checker counts, and what each channel offers a fault. You can write incidents from it
without reading the code in `targets/dispatch/`.

The facts follow the code. The measured numbers come from live runs on a 4-CPU Linux machine with seed 0 unless a
table says otherwise, and each table says how it was measured. Nothing was measured on Windows. Every measured
number here was taken before the dispatcher's 30 s re-offer rule (11.1, Pending incidents), except the alerting
outage given there and the drain after a unit-sync outage (section 6, also used in 11.6). The rule acts only on
an incident a unit failed to acknowledge, so it changes nothing on a healthy copy. Older results for breaks that
leave assignments unacknowledged (for example alerting or its link, unit-sync, a short `ack_timeout_s`) may
differ under it.

## 1. What dispatch is

**The centre.**

| Real centre | Dispatch |
|---|---|
| Call-taker positions and the call queue (ACD) | `call-handling` (service; the journey's entry) |
| The 9-1-1 call network provider: routing and the location database (ALI) | `call-network` (external, through a relay) |
| The CAD server: incident entry, repeat-call linking by number, the gateway for unit terminals (MDT) | `cad` (service) |
| Automated dispatch: recommend, commit, alert the station, the acknowledgement timer | `dispatcher` (worker) |
| The station alerting controller, and backup radio tone alerting | `alerting` (dependency), with standby `alerting-backup` |
| The unit status interface that applies terminal reports to CAD's unit records | `unit-sync` (worker over a queue) |
| The CAD database | `cad-db` (SQLite datastore) |
| Export of closed incidents to the records system (RMS) | `incident-archive` (job) |
| The public and the field crews | the test users (`people.py`) and the call surge helper (`surge.py`) |

**Two clocks.**

- **Centre clock, 1:20.** One simulated second stands for 20 real seconds, for everything the centre does.
  Section 7 gives the scaling table.
- **Field clock, about 1:300.** A whole field response fits inside one checker window:
  - turnout 0.2-0.4 s;
  - drive `min(1.8, 0.3 + 0.06 × km)` s from the unit's station to the incident;
  - on scene 0.6-1.2 s.

  No service target applies to field times, except that a crew must be en route at most 3.0 s after the
  caller is told.

**Not modelled.**

- Hang-ups and abandoned calls.
- Duplicate callers: one caller and one number per emergency.
- Silent or prank calls.
- More than one unit per incident.
- Vehicle location (AVL): distances are from the unit's station.
- Explicit crew declines: a busy crew simply does not respond.
- Radio traffic.

## 2. Inventory

`targets/dispatch/spec.py`, in the columns of CONTRACT 7.1.

| Component | Kind | Actions | Settings (defaults) | Release | Depends on | Standby | Impact |
|---|---|---|---|---|---|---|---|
| call-handling | service (entry) | restart, rollback, revert_config | `positions` 14, `rollover_s` 2.5, `ali_timeout_s` 0.5, `cad_timeout_s` 1.0 | 5.2 (5.2.1 is a harmless build label) | call-network, cad | none | 1.0 |
| cad | service | restart, rollback, revert_config | `repeat_match` "ani_open", `write_timeout_ms` 1000 | 3.4 (3.4.1 build label) | cad-db | none | 1.0 |
| dispatcher | worker | restart, rollback, revert_config | `poll_interval_s` 0.2, `batch_size` 20, `ack_timeout_s` 2.0, `alert_timeout_s` 1.0, `recommend_by` "closest" | 2.1 (2.1.1 build label) | cad-db, alerting | none | 1.0 |
| alerting | dependency | restart, failover | none | 1.6 (1.6.1 build label) | none | alerting-backup | 1.0 |
| alerting-backup | dependency | restart | none | 1.6, image `alerting` (1.6.1 build label) | none | none | 0.0 |
| unit-sync | worker | restart, rollback, revert_config, quarantine | `poll_interval_s` 0.2, `batch_size` 200, `max_message_age_s` 10.0 | 4.0 (4.0.1 build label) | cad-db | none | 0.6 |
| call-network | external | none | none | 1.0 | none | none | 0.5 |
| cad-db | datastore | release_lock | none | none | none | none | 1.0 |
| incident-archive | job (normal when not running) | none | none | none | cad-db | none | 0.0 |

**Ports.** A copy takes ten ports from its port base.

| Offset | What listens |
|---|---|
| 0 | call-handling |
| 1 | cad |
| 2 | dispatcher |
| 3 | alerting |
| 4 | alerting-backup |
| 5 | unit-sync |
| 6 | call-network |
| 7 | relay `dispatcher->alerting` (upstream alerting) |
| 8 | relay `call-handling->call-network` (upstream call-network) |
| 9 | the supervisor (Control) |

**Link routes.** `dispatcher->alerting` and `call-handling->call-network`. Each passes through its relay.

**Start order.** call-network, alerting, alerting-backup, cad, unit-sync, dispatcher, call-handling.

**The alerting path.** The dispatcher reads the routing state before every alert. On the primary it posts
through the `dispatcher->alerting` relay and records the call under `alerting`. On the standby it posts to
`alerting-backup` directly and records it there. Only `failover` changes the routing state.

**Descriptions**, as describe() gives them:

- call-handling: "9-1-1 call handling: queues each 9-1-1 call for the call-taker positions, gets the caller's
  location from the call network, and enters the incident in CAD"
- cad: "computer-aided dispatch server: creates incidents from calls, links a repeat call from the same number to
  its open incident, and takes in status reports from unit terminals"
- dispatcher: "automated dispatch: takes pending incidents in priority order, recommends the closest free unit,
  commits it and sends the station alert"
- alerting: "station alerting controller: alerts the unit's station over the county network"
- alerting-backup: "backup station alerting over the radio tone path; carries alerts only after a failover"
- unit-sync: "unit status interface: applies status reports from unit terminals to CAD's unit records"
- call-network: "the 9-1-1 call network provider's location service (ALI), run by another organisation; we
  cannot change it"
- cad-db: "the CAD database (SQLite): incidents, calls, units, assignments and the queue of reports from unit
  terminals"
- incident-archive: "export of closed incidents to the records system; normal when not running"

**describe() also gives:**

- the six actions with the bank's `est_seconds` (3 for restart, 4 for rollback, 1 for the others), `undo` and
  `params`. `revert_config` takes an optional `{"key": <setting>}` (section 3), `failover` takes `{"to":
  "standby" | "primary"}` (default `standby`), and `quarantine` takes `{"item": <extra.head_item.id>}`. The
  restart description warns that a restart of call-handling cuts off calls being answered;
- four forbidden lines: "close or cancel an incident", "change a call's priority", "stand down or reassign a
  unit committed to an incident" and "contact a caller". No action does any of these;
- one contact per component: shift supervisor (call-handling, dispatcher); CAD administrator (cad, cad-db,
  unit-sync, incident-archive); radio and alerting technician (alerting, alerting-backup); call network provider
  (call-network).

## 3. Settings

Every setting is a JSON number or a named choice. A bool is never usable, and neither is a number written as a
string, such as `"10"`; a whole-number setting also takes `20.0`. The defaults are safe. A component reads
its settings at most 0.2 s old. The workers sleep in 0.25 s slices and wake early when a setting changes. The
sleep compares with the settings the cycle started with, so a change made during a cycle also cuts short the
sleep its old `poll_interval_s` set. So `revert_config` takes effect within about 0.25 s, or about 0.25 s after
the cycle in progress ends. With `{"key": k}`, `revert_config` restores the value that the newest change to k (not
yet undone) replaced, not the default. With no key it undoes the newest change on that component, not yet undone,
that the agent did not make. Either way the undo is a new version and a new change in the feed.

| Component | Setting | Default | Usable values | When unusable |
|---|---|---|---|---|
| call-handling | `positions` | 14 | whole number 1-64 | `/dial` and `/report` answer 503 `{"error": "call handling unavailable (settings)", "at": "call-handling"}` |
| call-handling | `rollover_s` | 2.5 | number, 0 < v ≤ 10 | same |
| call-handling | `ali_timeout_s` | 0.5 | number, 0 < v ≤ 5 | same |
| call-handling | `cad_timeout_s` | 1.0 | number, 0 < v ≤ 5 | same |
| cad | `repeat_match` | `"ani_open"` | `"ani_open"` (link a call to this number's open incident) or `"off"` (always a new incident) | `/calls` and `/mdt` answer 503 `{"error": "cad unavailable (settings)"}` |
| cad | `write_timeout_ms` | 1000 | whole number 1-10000 | same |
| dispatcher | `poll_interval_s` | 0.2 | number, 0 < v ≤ 60 | dispatching stops |
| dispatcher | `batch_size` | 20 | whole number 1-10000 | dispatching stops |
| dispatcher | `ack_timeout_s` | 2.0 | number, 0 < v ≤ 60 | dispatching stops |
| dispatcher | `alert_timeout_s` | 1.0 | number, 0 < v ≤ 10 | dispatching stops |
| dispatcher | `recommend_by` | `"closest"` | `"closest"` or `"station_order"` (the first free unit in roster order) | dispatching stops |
| unit-sync | `poll_interval_s` | 0.2 | number, 0 < v ≤ 60 | applying stops |
| unit-sync | `batch_size` | 200 | whole number 1-10000 | applying stops |
| unit-sync | `max_message_age_s` | 10.0 | number, 0 < v ≤ 3600 | applying stops |

- alerting, alerting-backup and call-network have no settings.
- **Unusable.** A component with an unusable value writes an ERROR line `settings_unusable` at once, then at most
  one every 2 s until the setting changes. The line names the key, in its message and its `key` field, and never
  the value; a worker's reads "setting batch_size cannot be used; work is paused until it changes". The component
  does not crash, and it stays up and answering. A worker pauses: it runs no cycle, so the dispatcher neither
  commits, alerts nor expires assignments, and unit-sync reads no report and raises no `attempts`.
- **Harmful.** A usable but harmful value is used as given. A dispatcher `poll_interval_s` of 30 makes every
  dispatch late.

**Harmless ranges**, for background changes. Measured on one copy while three other copies shared the
machine, with healthy links. Each value was held 35 s, then judged on three 20 s windows (lag 10 s) 20 s apart.
Every value tried was green in all three windows.

| Component | Setting | Values tried | Harmless range |
|---|---|---|---|
| call-handling | `positions` | 6, 4 | 4-14 |
| call-handling | `positions`, during a surge at the cap (3.0 per second, medical mix) | 14, 12, 10 | 10-14 (answer p95 at most 103 ms) |
| call-handling | `rollover_s` * | 1.0, 5.0 | 1.0-5.0 |
| call-handling | `ali_timeout_s` * | 0.3, 2.0 | 0.3-2.0 |
| call-handling | `cad_timeout_s` * | 0.5, 3.0 | 0.5-3.0 |
| cad | `write_timeout_ms` * | 200, 5000 | 200-5000 |
| dispatcher | `poll_interval_s` | 0.5, 1.0 | 0.2-1.0 |
| dispatcher | `ack_timeout_s` | 1.5, 1.0, 10 | 1.0-10 |
| dispatcher | `alert_timeout_s` * | 0.5, 3 | 0.5-3 |
| unit-sync | `poll_interval_s` | 0.5, 1.0 | 0.2-1.0 |
| unit-sync | `batch_size` | 50, 10 | 10-200 |
| unit-sync | `max_message_age_s` | 2, 1 | 1-10 |

- \* These five were changed together: all five low values in one test, all five high values in another.
- The ranges assume healthy links. No value tried was red, so where harm starts is not known.
- `positions` 4 leaves answer p95 unchanged without a surge, because everyday callers arrive every 0.35-0.55 s,
  not at random.
- Not measured: dispatcher `batch_size` and `recommend_by`, `positions` below 4, and any setting other than
  `positions` during a surge. cad `repeat_match` "off" is a break (section 12).

## 4. Data

`cad-db` is `<data>/cad.db`: SQLite in WAL mode with `synchronous=NORMAL` (`targets/dispatch/cadstore.py`).

```sql
CREATE TABLE incidents (id INTEGER PRIMARY KEY AUTOINCREMENT, first_call_id TEXT NOT NULL, ani TEXT NOT NULL,
  nature TEXT NOT NULL, priority INTEGER NOT NULL, unit_type TEXT NOT NULL, narrative TEXT NOT NULL,
  x REAL NOT NULL, y REAL NOT NULL, location_source TEXT NOT NULL,      -- ali | verbal
  status TEXT NOT NULL,                       -- pending | dispatched | enroute | onscene | closed | cancelled
  test INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, release TEXT,
  created_t REAL NOT NULL, pending_since REAL, updated_t REAL NOT NULL, closed_t REAL, close_reason TEXT);
CREATE TABLE calls (call_id TEXT PRIMARY KEY, incident_id INTEGER NOT NULL, ani TEXT NOT NULL,
  linked INTEGER NOT NULL, test INTEGER NOT NULL DEFAULT 0, t REAL NOT NULL);
CREATE TABLE units (id TEXT PRIMARY KEY, type TEXT NOT NULL, station TEXT NOT NULL, test INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,                       -- available | enroute | onscene | outofservice
  incident_id INTEGER, status_t REAL, status_since REAL NOT NULL, applied_t REAL, source TEXT);
CREATE TABLE unit_history (id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id TEXT NOT NULL, status TEXT NOT NULL,
  incident_id INTEGER, t REAL NOT NULL);
CREATE TABLE incident_events (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL,
  op TEXT NOT NULL, status TEXT, first_call_id TEXT, test INTEGER, t REAL NOT NULL);   -- op: insert | update | delete
CREATE TABLE assignments (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL, unit_id TEXT NOT NULL,
  status TEXT NOT NULL,                       -- assigned | alerted | acked | onscene | cleared | no_ack | cancelled
  source TEXT NOT NULL, test INTEGER NOT NULL DEFAULT 0,               -- source: dispatcher | field
  assigned_t REAL NOT NULL, alerted_t REAL, next_alert_t REAL, acked_t REAL, closed_t REAL);
CREATE TABLE field_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id TEXT, payload_json TEXT NOT NULL,
  status TEXT NOT NULL,                       -- pending | applied | skipped | quarantined
  attempts INTEGER NOT NULL DEFAULT 0, created_t REAL NOT NULL, updated_t REAL NOT NULL);
CREATE TABLE rms_export (incident_id INTEGER PRIMARY KEY, exported_t REAL NOT NULL);
```

**Indexes:** incidents (status, priority, id) and (ani, status); calls (incident_id); unit_history (unit_id, t);
incident_events (incident_id); assignments (status, unit_id) and (incident_id); field_queue (status, id),
(unit_id, status, id) and (updated_t).

**Triggers are the checker's evidence.** No component writes `unit_history` or `incident_events`; triggers do,
stamped with the database clock:

- `units_history_insert`: after an insert into `units`;
- `units_history_update`: after an update of `units.status` or `units.incident_id` that changes either;
- `incident_events_insert`: after an insert into `incidents`;
- `incident_events_status`: after an update that changes `incidents.status`;
- `incident_events_delete`: after a delete from `incidents` (op `delete`).

**Open sets.** Open incidents are `pending`, `dispatched`, `enroute` and `onscene`. Open assignments are
`assigned`, `alerted`, `acked` and `onscene`. Nothing sets `cancelled`; the checker treats it as closed. Every
move to a closed assignment state, and every incident close, sets `closed_t`.

**Who writes what.**

- cad inserts `incidents` and `calls` in one transaction per call (11.1, Behaviour the methods carry), and inserts
  `field_queue` rows.
- The dispatcher inserts and updates `assignments`, and moves incidents between `pending` and `dispatched`. It
  closes an `enroute` or `onscene` incident whose last open assignment expires (`completed`). It never writes
  `units`.
- unit-sync writes `units`, and updates `assignments`, `incidents` and `field_queue` from the reports.
- `units` holds only what the field reported, plus the seed and the probe's TEST-1 cleanup.
- incident-archive `--export` inserts `rms_export` rows only.

**Growth.** Nothing prunes `field_queue`. It grows by about 28 rows a second, every heartbeat and status report.
In the 30-minute soak (section 7) it reached about 53,000 rows and 11 MB with its indexes, 70% of cad.db, which
reached about 16 MB per copy, plus a 4.4 MB write-ahead log.

**Seed.**

- **Stations** on a 20 × 20 km grid: S1 (4, 4), S2 (16, 4), S3 (10, 10), S4 (4, 16), S5 (16, 16).
- **Units.** Station Sk has medics M(2k−1) and M(2k) and engines E(2k−1) and E(2k): M1-M10 and E1-E10. S2 has
  M3, M4, E3 and E4. Roster order, which `station_order` follows, goes station by station: M1, M2, E1, E2, M3,
  M4, E3, E4, and so on.
- **Test unit.** `TEST-1` (`test` 1, type `test`) at station `TEST` (0, 0). No crew serves it.
- Every unit starts `available`, with no incident.

**Natures** (code, priority, preferred unit, weight in the everyday mix):

| Code | Priority | Unit | Weight |
|---|---|---|---|
| cardiac | 1 | medic | .15 |
| breathing | 1 | medic | .15 |
| fall | 2 | medic | .20 |
| collision | 2 | medic | .10 |
| structure_fire | 1 | engine | .10 |
| vehicle_fire | 2 | engine | .10 |
| alarm | 3 | engine | .20 |
| test | 3 | test | the probe only |

Each real nature has three made-up narrative sentences. They are stored only in `incidents.narrative`. They are
never logged or raised.

**Files in the data folder.**

| File | What |
|---|---|
| `cad.db` | cad-db |
| `cad_locks.json` | `{"holders": [...]}`: registered lock holders |
| `surge.json` | `{"helpers": [...]}`: running call surge helpers |
| `surge-slots/<k>` | the number block of each surge helper (k 0-4) |
| `people.jsonl` | the users' log (section 5) |
| `alerts-alerting.jsonl`, `alerts-alerting-backup.jsonl` | the station inboxes, one JSON line per alert |
| `probe.json` | `{"seq": n}`: the probe's counter |
| `checker_baseline.json` | the warm-up baseline (section 10) |
| `logs/<component>.jsonl`, `logs/*.out` | component logs and process output |
| `logs/call-surge-<pid>.jsonl` | each surge helper's caller lines |
| `releases/<component>/v<x_y>.py` | a copy of each release deployed with `module_path` (11.1, Releases) |
| `actions.jsonl`, `changes.jsonl` | the agent's actions, and every recorded change: deploys and rollbacks, setting changes and reverts, stops and starts made with `log_change` true, restarts, failovers, quarantines and lock releases. A kill, a link change, a spawn or surge, a hang and a datastore write record nothing. observe() shows the changes of the last 15 minutes |

## 5. Users and the users' log

The users run as one process, `targets.dispatch.people`. It writes `<data>/people.jsonl`, one JSON line per
record, flushed on every write. `paths()["traffic_log"]` and `paths()["users_log"]` both name it.

### 5.1 Callers

A new everyday emergency starts every 0.35-0.55 s, about 2.2 per second, each in its own thread. Each one gets
an `emergency_id` (`E-N-<n6>`), the next number of the everyday pool, a nature from the mix, a narrative
sentence, and its true location. Each call writes exactly one caller line when it ends.

1. **Dial.** POST `/dial {"ani", "test": 0}`, with a 3.5 s client timeout.
2. **Read-back.** If the location answered is missing or more than 0.05 km from the caller's own, the caller
   gives it by voice. That adds 1.2-2.0 s, and the report carries `location`.
3. **Talk.** 0.8-1.6 s; a callback talks 0.2-0.3 s.
4. **Report.** POST `/calls/<call_id>/report {"nature", "narrative", "location"?}`, with a 2.0 s client timeout.
   On 200 the caller is told help is on the way.

| Outcome | When |
|---|---|
| `told` | the report answered 2xx with a JSON object holding `"told": true` and a whole incident id, 0 < id < 2^63 (the releases here answer 200) |
| `rolled_over` | the dial got 503 `{"error": "rolled over"}` |
| `not_answered` | the dial got another 5xx; or a malformed HTTP answer, or a 2xx answer that is not a JSON object holding a call id, a string of 1-64 characters (both `status` `bad_response`) |
| `rejected` | the dial got a 4xx, or the report a 4xx other than 404 |
| `refused` | the dial's connection was refused |
| `cut_off` | the dial's connection was reset, as a restart of call-handling does |
| `dropped` | after the answer, the report got 404, or a refused or reset connection |
| `not_entered` | the report got a 5xx; or a malformed HTTP answer, or a 2xx answer that is not a JSON object holding `"told": true` and a whole incident id (both `status` `bad_response`). So a release whose report answer lacks the incident id fails its callers as "answered but not told help is on the way" (`not_told`), not under `told_without_incident` |
| `timeout` | a client timeout at either step |

- **Windows.** There a connection to a closed local port is refused only after about 2 s. So a report sent while
  call-handling is down usually ends as `timeout` (its client timeout is 2.0 s), not `dropped`, and does not
  count in `calls_dropped`; a dial then takes about 2 s before `refused`. The verdict is red either way. Not
  measured: it follows from the code and that platform behaviour.
- **Redial.** After `refused`, `cut_off`, `not_answered`, `dropped`, `not_entered` or `timeout`, the caller
  dials again 0.3-0.6 s later: kind `redial`, the same number, a new call. Only while the emergency's first dial
  is under 7.0 s old, and at most 3 calls in all. Never after `rolled_over` (the backup centre has the call),
  `rejected`, or being told.
- **Callback.** 10% of told emergencies call again 0.2-0.5 s after being told: kind `callback`, the same number
  and nature, an empty narrative. CAD links it to the open incident. A callback is never redialled.
- The longest call is 3.5 + 2.0 + 1.6 + 2.0 = 9.1 s, under the checker's 10 s lag.

### 5.2 Crews

There are 20 crews, one per real unit, in the people process.

- **One scheduler** runs every 0.05 s. It reads the new lines of both station inboxes and makes every crew
  transition and heartbeat.
- **Alert.** For an alert to one of its units with a whole-number `incident_id` (0 < id < 2^63), it writes an
  `alert` line, with `taken` true only if the crew is free. A repeated `assignment_id`, or an incident the crew
  has taken before, is ignored and not logged: a crew never takes the same incident twice. A busy crew does not
  respond. A crew that takes an alert drives to the alert's `x` and `y`, taking the 1.8 s cap when they are
  missing.
- **Taken.** After turnout of 0.2-0.4 s: `status enroute`. After the drive: `onscene`. After 0.6-1.2 s on scene:
  `available` with no incident.
- **Log before post.** Each transition is written to the log at its time `t`, then a report with the same `t`
  is queued. Per unit, `t` strictly increases.
- **Heartbeat.** Every 1.0 s per unit, staggered: a `heartbeat` report with the full current state. Heartbeats
  are not logged.
- **Posting.** Four uplinks; unit k always sends through uplink k mod 4, so its reports stay in order. Each
  uplink holds at most 200 reports, dropping the oldest heartbeat first when full. A report older than 2.0 s
  when its turn comes is dropped: the next heartbeat carries the state. POST cad `/mdt` with a 1.0 s timeout. A
  failed post is never retried.

A report: `{"unit": "M3", "kind": "status" | "heartbeat", "status": "enroute", "incident_id": 512 | null, "t":
1767225600.123}`.

### 5.3 Record shapes

**Caller line**, one per call:

```json
{"who": "caller", "source": "normal", "emergency_id": "E-N-000123", "kind": "first", "attempt": 1,
 "call_id": "C-3f9a1c2e", "ani": "012-555-0147", "nature": "cardiac",
 "t_start": 0.0, "t_answer": 0.0, "answer_ms": 14.2, "location": "ali",
 "t_told": 0.0, "incident_id": 512, "linked": false, "outcome": "told", "status": 200, "t_end": 0.0}
```

- `kind` is `first`, `redial` or `callback`. `location` is `ali`, `verbal` or null.
- `call_id`, `t_answer`, `answer_ms`, `t_told`, `incident_id` and `linked` are null when the call never got
  that far.
- `status` is the last HTTP status, or the error kind (`refused`, `reset`, `timeout`, `bad_response`).

**Crew lines:**

```json
{"who": "crew", "event": "start",  "unit": "M3", "status": "available", "incident_id": null, "t": 0.0}
{"who": "crew", "event": "alert",  "unit": "M3", "incident_id": 512, "assignment_id": 913, "via": "alerting", "t": 0.0, "taken": true}
{"who": "crew", "event": "status", "unit": "M3", "status": "enroute", "incident_id": 512, "t": 0.0}
```

`via` is `alerting` or `alerting-backup`. A status line's `status` is `enroute`, `onscene` or `available`.

**Rules.** The users' log holds ids, codes and the fictional number, never a narrative or free text. Surge
callers write `<data>/logs/call-surge-<pid>.jsonl` in the same shape, with `"source": "surge"` and
`emergency_id` `E-S<pid>-<n6>`.

### 5.4 Number pools

Numbers are fictional: `0PP-555-01NN`. No area code starts with 0, and 555-01NN is reserved for fiction.

| Who | PP | Numbers | Reuse |
|---|---|---|---|
| Everyday callers | 10-39 | 3,000, in turn | each number after about 23 minutes |
| Surge callers | 40-89, five blocks of ten PP (1,000 numbers each) | one block per helper, so at most five helpers at once; a helper continues its block where the last one stopped | after its block has placed 1,000 more emergencies, at least 333 s at the cap |
| The probe | 99 (`099-555-0100` to `099-555-0199`) | NN = seq % 100 | |

- **Surge blocks.** A helper takes the first block no running helper holds. Its numbers go in turn:
  `area.surge_number(block, index)` takes the index modulo 1,000. The slot file `surge-slots/<k>` holds
  `{"pid", "next"}`. While a helper runs, the file's `next` stays up to ten numbers ahead of the ones it has used;
  when it ends, it saves its exact place. The next helper on that block goes on from `next`, so a helper killed
  mid-run makes its successor skip at most about ten numbers and never repeat one. One surge starts at most 1,000
  emergencies (11.3), so one run never uses a number twice.
- **A number comes round.** An everyday number returns after about 23 minutes. If that number's incident is
  still open then, cad links the new emergency's call to it, and the checker counts that caller under
  `told_without_incident` (`other_emergency`). This matters only on a copy that has run for more than about 22
  minutes.

## 6. Load, capacity and drain

**Everyday load on one copy.**

- About 2.2 emergencies per second plus 10% callbacks: about 2.4 calls per second, about 49 calls per 20 s
  window. The checker needs at least 20. In the soak (section 7) a 20 s window outside surges held 43-54 calls
  (median 48-49), and up to 122 during a surge at the cap.
- About 20% of positions busy, and about 20% of units committed. A call holds its position from the answer until
  its report is answered: the caller's 0.8-1.6 s of talk (0.2-0.3 s for a callback) plus a few ms, and 1.2-2.0 s
  more when the location is given by voice. That keeps about 2.7 of 14 positions busy on average outside surges
  (from the code, not measured). In the soak:
  at most 5 positions busy outside surges, and 3-4 of 20 units committed at the median (at most 16).
- About 27 field reports per second: 20 heartbeats plus about 7 status changes.

**Capacity.** Measured on one copy while three other copies shared the machine. Each surge ran 150 s with the
normal mix, judged on 20 s windows (lag 10 s). The medical row is one 240 s surge, with `positions` set to 14,
then 12, then 10.

| Extra calls/s (surge) | Calls per window | Windows breaching | Medical incidents sent an engine | Incidents waiting: pending max, oldest |
|---|---|---|---|---|
| 0 (none) | 47-50 | 0 of 3 | 0 of 76 | 1-2, 0.16 s |
| 1.1 (surge 1.0) | 66-77 | 0 of 7 | 0 of 283 | 2, 0.19 s |
| 2.1 (surge 2.0) | 79-98 | 0 of 7 | 1 of 360 | 2, 0.19 s |
| 3.5 (surge 3.0, the cap) | 107-128 | 0 of 7 | 21 of 463 | 3, 0.19 s |
| 3.3 (surge 3.0, medical) | 97-131 | 0 of 9 | 164 of 1,037 | 4, 0.20 s |

- The checker's `incidents_waiting` was 0 in every window. A rate above the cap cannot be run: the helper refuses
  it.
- In the soak, all three copies ran a medical surge at the cap at once and none breached. Call-taker positions
  are the tightest resource: 13 of 14 busy at the peak.

**Drain.** The dispatcher stopped for D seconds, then started, with no surge, on the same copy. Times are from
the start.

| D | Backlog (pending max) | Backlog cleared | Fresh calls reached again | First green verdict |
|---|---|---|---|---|
| 10 s | 22 | 4.0 s | at once | 28.6 s |
| 30 s | 68 | 10.1 s | after 4.7 s (7 calls failed) | 35.0 s |
| 60 s | 133 | 19.1 s | after 14.7 s (18 calls failed) | 46.1 s |

- The first green window was also the first in which every call reached a crew within 3 s. A verdict cannot be
  green sooner than 30 s after the last failing call (window 20 s plus lag 10 s).
- The drain with a surge was not measured.

**Drain after a unit-sync outage**, measured with the 30 s re-offer rule.
An unreadable report stopped unit-sync for F seconds, then `quarantine` and
`restart`, with no surge, on one copy (seed 11) alone on the machine (one run each, sampled every 5 s). Times are from the
fix.

| F | Backlog (dispatcher `queue_depth` at the fix) | Backlog cleared | First green verdict | Verdict 125 s after the break |
|---|---|---|---|---|
| 30 s | 51 | by 15 s | 40.3 s | green |
| 60 s | 120 | by 25 s | 50.6 s | green |
| 90 s | 185 | by 41 s | 66.1 s | red: "31 of 47 calls failed: 31 with no crew en route within 3 s of being told" |

- While unit-sync is down, crews still take alerts and serve incidents, but CAD never hears of it: each
  assignment becomes `no_ack`, and its incident returns to `pending` and is sent to another unit. No incident
  closes, so the dispatcher's `queue_depth` grows by about 2 a second (the backlog column). Its `processed_per_s`
  runs at several times the everyday rate, as each unit CAD shows free is committed again about every 2 s (from
  the code, not measured). Once unit-sync
  is back, the reports from the outage are too old (`max_message_age_s`, 10 s) or superseded by each unit's
  newest report, so every incident that no crew is serving at that moment is dispatched again, by
  priority then id. A crew never takes an incident it has already taken (5.2), so offering one to a crew that took
  it during the outage holds the unit for `ack_timeout_s` (2.0 s) for nothing, and only a crew that has not taken
  it before can take it now (from the code, not measured).
  The backlog grows with the outage, and fresh calls wait behind it: they were reached again
  by about 10, 21 and 36 s after fixes at 30, 60 and 90 s (the first green verdict less 30 s).
- At the harness's timing (11.6) a unit-sync outage is therefore judged recovered only when its fix comes within
  about 70 s of the break. A dispatcher outage drains faster (the table above).

**One call in N.** A scored window holds about 49 calls. A mechanism that touches one call in N misses a whole
window with probability about (1 − 1/N)^49. Every failed call counts (section 10, zero failed calls).

## 7. Service level

**The scaling table** (centre clock, 1:20):

| Real target | Real value | Dispatch value |
|---|---|---|
| NENA call answering: 90% of calls answered | 15 s | answer time p90 at most 750 ms |
| NENA call answering: 95% of calls answered | 20 s | answer time p95 at most 1000 ms (the SLO `p95_ms`) |
| Call dispatchable after answer (NENA/NFPA 1225 alarm processing), applied to every call | 60 s | the caller is told help is on the way at most 3.0 s after answer |
| Crew notified and en route (alerting plus turnout, NFPA 1710) | 60 s | the first real crew is en route at most 3.0 s after the caller is told |
| CAD unit-status lag a centre tolerates | 60 s | unit-record lag allowance 3.0 s |
| Rollover to the backup centre | 50 s | `rollover_s` 2.5 |
| Re-alert or reassign after no acknowledgement | 40 s | `ack_timeout_s` 2.0 |

**The SLO.** The journey is `emergency_call`, the default, with entry `call-handling` and side effects
`test_data`: "a 9-1-1 caller is answered, gives the location and the emergency, is told help is on the way, and
a crew is en route soon after". The SLO is `{"success_rate": 0.99, "p95_ms": 1000}`. `p95_ms` is answer time.

The checker also holds answer p90 at most 750 ms, the two 3.0 s targets, and a band on answer p95 around the
warm-up p95 (section 10).

**The main journey on a healthy copy** (design values):

| Stage | Who | Design time | What the checker allows |
|---|---|---|---|
| Dial to answer: queue, then ALI | call-handling, call-network | 10-60 ms | p90 at most 750 ms; p95 within the band |
| Answer to told: talk, report, CAD write | caller, call-handling, cad | 0.8-1.7 s; a spoken location adds 1.2-2.0 s, which a healthy copy never needs | 3.0 s |
| Told to unit committed | dispatcher | at most one poll, 0.2 s | |
| Committed to alert delivered | dispatcher, alerting | under 0.05 s | |
| Alert to crew en route | crew | 0.25-0.45 s | en route at most 3.0 s after told |
| Crew report to CAD record | terminal, cad, unit-sync | 0.05-0.5 s | lag allowance 3.0 s |
| En route to on scene, then available | crew | drive 0.3-1.8 s, then 0.6-1.2 s on scene | the 4.0 s status timer (a monitor) |

**Healthy times, measured.** A 30-minute soak of three copies (port bases 9600, 9700 and 9800), with a fourth
copy sharing the machine throughout. Each copy ran two 150 s surges at the cap (five medical, one normal), one of
them at minute 20 on all three copies at once, and one copy ran an `--export`. All 16,047 calls succeeded: 0
failed calls in all 270 back-to-back 20 s windows and in 5,343 sliding ones, and all 183 live verdicts were
green. Seed 0 makes the three copies replay the same callers, so they are not independent samples.

| Measure (three copies pooled) | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|
| Answer time, all 16,047 calls (ms) | 5.8 | 7.1 | 7.5 | 8.8 | 54.0 |
| Answer time, the 5,096 calls during surges (ms) | 5.8 | 7.1 | 7.4 | 8.7 | 11.9 |
| Told after answer (s) | 1.17 | 1.52 | 1.56 | 1.59 | 1.64 |
| First crew en route after told, first calls (s) | 0.45 | 0.56 | 0.59 | 0.62 | 0.69 |

**Record lag**, from a crew's status line to the matching `unit_history` row, over 43,802 status changes: p50
0.104 s, p90 0.183 s, p99 0.202 s, p99.9 0.209 s, max 0.356 s (p99.9 0.216 s during surges). No status change
was skipped, and no row showed a state its crew had already left.

**The p95 band is kept**: the bank's `min(1000, max(2b, b + 250))`, with b the copy's warm-up answer p95
(DECISIONS, dispatch row 2). No healthy window came near it.

| Copy | Warm-up p95 b | Band | Worst 20 s window p95 |
|---|---|---|---|
| 9600 | 7.9 ms | 257.9 ms | 10.8 ms |
| 9700 | 7.5 ms | 257.5 ms | 9.4 ms |
| 9800 | 8.5 ms | 258.5 ms | 9.3 ms |

Answer p90 never went above 8.7 ms in a window. The band is never below 250 ms, though the warm-up baseline
holds only about 21 calls.

## 8. Monitors

The kit fills the standard fields: rps, error and reject rates, latency, `dependencies`, the exit keys,
`not_answering`, `active` (alerting) and `running` (incident-archive). `dependencies` gives, for each component
a process calls, `{n, rps, p95_ms, error_rate, reject_rate}` as that process saw its calls over the observe()
window: a reject is a 4xx answer, and an error any other failure (a 5xx, a timeout or a failed connection).
`active`, on alerting only, is the side routing names, "primary" or "standby"; only `failover` changes it.
Dispatch adds the keys below. Each sits on the component that owns that watchdog in a real centre. Each is
current state and drops back to 0 once its cause is fixed. Integrity counts, and the dispatcher's `queue_depth`
and `oldest_pending_s`, leave out test rows and TEST-1; the other queue keys, the dispatcher's `processed_per_s`
included, count every row.

| On | Key | Definition | Reason (real practice) | Healthy |
|---|---|---|---|---|
| call-handling | `queue_depth`, `oldest_pending_s`, `processed_per_s` | calls ringing now; the longest current ring; calls answered per second | the call queue wallboard | 0-1; under 0.1 s; about 2.4 |
| dispatcher | `queue_depth`, `oldest_pending_s`, `processed_per_s` | real `pending` incidents; seconds since the oldest was created; units the dispatcher committed per second. Read from cad-db, so they show while the dispatcher is down. No `head_item`: these are live calls | CAD's pending-incident list | 0-2, up to 5 during a surge at the cap; under 0.3 s |
| dispatcher | `integrity.units_not_acknowledging` | real units with an assignment still `assigned` or `alerted` more than 3.0 s after it was committed. With `ack_timeout_s` at 2.0 the acknowledgement timer ends such an assignment first, so it reads above 0 only while that timer runs late or not at all | the "dispatched, not acknowledged" timer | 0 |
| cad | `integrity.unit_status_timers_expired` | real units whose record has shown the same `enroute` or `onscene` status and incident for more than 4.0 s, timed from when unit-sync applied that change (`units.status_since`); a move from en route to on scene restarts the timer | the en-route and on-scene status (welfare) timers | 0 |
| cad | `integrity.possible_duplicate_incidents` | open real incidents that share a number with another open real incident | duplicate-call detection by number | 0 |
| unit-sync | `queue_depth`, `oldest_pending_s`, `processed_per_s`, `head_item {id, age_s, attempts}`, `quarantined_items` | pending field reports; age of the oldest; reports applied or skipped per second; the oldest pending report; reports set aside so far. Read from cad-db | the terminal message queue monitor | 0-30; under 0.5 s |
| unit-sync | `integrity.unit_reports_overdue` | real units with no report applied for more than 3.0 s | the terminal-not-reporting indicator | 0 |
| cad-db | `lock_holders [{session, mode, held_s, statement}]` | the live registered lock holders | the database lock view | `[]` |
| cad-db | `write_errors` | failed writes of cad, the dispatcher and unit-sync together; null when none of them answers | the failed-write counter | 0 |
| cad-db | `up` false with `extra.error` "cad-db cannot be read (<ExceptionType>)" | cad.db cannot be opened or read | | up true |
| incident-archive | `runs`, `cpu_pct`, `mem_mb` | running jobs named `incident-archive`, and their CPU and memory, summed over each run and the processes it started (on Windows a venv's `python.exe` is a launcher that runs Python as its child). `cpu_pct` is the CPU since the previous observe(), so the first observe() of a run reads 0 | the job monitor | 0, null |

In the 30-minute soak (section 7) every monitor stayed at its healthy value, `write_errors` stayed 0 and no lock
holder showed, even during an `--export`. The dispatcher's `queue_depth` reached 3-5 only during surges at the
cap, and no component wrote a WARN or ERROR line. Two breaks barely show in observe():

- **A short `ack_timeout_s`** shows in no integrity key, and in the measured run observe() showed nothing. The
  changes feed shows it, and so does the dispatcher's log: a WARN `no_acknowledgement` line, "<unit> did not
  acknowledge incident N in time", for every assignment that expires, with no rate limit. At 0.05 s nearly every
  assignment expires before its crew's en route report is applied, so these lines come several a second. From
  the code, not measured: most incidents are then committed to two units or more, so the dispatcher's
  `processed_per_s` runs at about twice the rate of new incidents or more.
- **`repeat_match` "off"** shows in the changes feed, and in cad's `possible_duplicate_incidents` again and again
  while it lasts, though any one observe() more often reads 0. Each callback opens a second incident, and the
  count includes both incidents of that number from then until the first one closes, about 1-2 s. Callbacks come
  about every 4.5 s, so roughly one observe() in three or four reads 2 (estimated from the code; measured: 2 at
  15 s into the break).

Section 12 gives what observe() showed for each break.

The checker's counts (section 10) never appear in observe(). Staff learn of them through callbacks, crews on the
radio, or later review. The adapter has no checker call: it offers describe(), observe(), logs(), probe() and
act(). The harness takes the verdict once, after the agent's turn (`eval/runner.py`).

**Logs.** Besides the WARN and ERROR lines, most journey steps write an INFO line: call-handling's
`call_answered`, then `call_entered` naming the incident id cad answered; cad's `incident_created` or
`call_linked`, naming the same id; the dispatcher's `unit_assigned`; and unit-sync's `status_applied` for each
change of a unit's status or incident. alerting writes no line for an alert. Each process also writes an INFO
`start` line naming its release when it starts. logs() returns the newest 200 lines of the last 60 s by
default, so at everyday load it holds only about the last 30 s of unit-sync's log and 40 s of call-handling's,
and less while a fault adds lines (from the code, not measured).

## 9. The probe

`probe("emergency_call")` places one test call along the main journey. Any other journey name answers `ok`
false with one step `journey`, "no journey named that". The probe never raises.

- Each probe takes the next `seq` from `probe.json` and calls from `099-555-01NN` (NN = seq % 100). ALI places
  the number at station TEST (0, 0). The call is `test: 1`, nature `test`, with an empty narrative.
- **Before step 1** (not a step) it cleans up test rows directly, with a 0.5 s busy timeout, and skips this when
  cad-db is busy: open test incidents close with `close_reason` `test_cleanup`, TEST-1's open assignments are
  cleared, and TEST-1 becomes `available` with no incident.
- Each step is `{"step", "component", "ok", "ms", "detail"}`. Details are plain words and ids.
- Steps 1-3 and 5-7 are chained: the probe stops at the first that fails. Step 4 records its result and the
  probe goes on.

| # | Step | Passes when | Detail on failure |
|---|---|---|---|
| 1 | call-handling | POST `/dial` (3.5 s timeout) answers with a `call_id` | the status and error, e.g. "503 rolled over", or the error kind (`refused`, `timeout`, `bad_response`); "answered without a call id" when the answer holds no string `call_id` |
| 2 | cad | the report (nature `test`, with a location only if ALI gave none or one more than 0.05 km from (0, 0)) answers told with an `incident_id`; a 502 or 504 whose `at` is `cad` names cad, any other error names call-handling | the status and error, or the error kind; "the caller was not told help is on the way" (step cad) when the answer's `told` is missing or false, or its `incident_id` is not a whole number |
| 3 | cad-db | the incident exists with `test` 1, is open, holds this call, and has the test location and priority | "incident not recorded" or "incident differs from the call" |
| 4 | call-network | the dial carried a location within 0.05 km of (0, 0) | "location not verified (unavailable)" or "location not verified (differs)" |
| 5 | dispatcher | an assignment of the incident to TEST-1 appears within 2.5 s | "no unit committed within 2.5 s" |
| 6 | alerting, or alerting-backup after a failover | the active side's inbox holds that assignment within 1.0 s | "alert not delivered on primary within 1.0 s", or "on standby" after a failover |
| 7 | unit-sync | the probe, as TEST-1's terminal, posts `enroute` to cad `/mdt`, and TEST-1's record shows exactly `enroute` with the test incident within 1.5 s; then it posts `available` without waiting. A failed post is reported as step `cad` | "unit record not updated within 1.5 s"; for a failed post, "unit report not taken in: " and the status and error, or the error kind |

A healthy probe takes about 0.3 s. The worst case, every step slow but passing, is about 13.5 s (0.5 s cleanup,
3.5 + 2.5 s for the call, 2.5 + 1.0 s of polls, then 1.0 + 1.5 + 1.0 s for TEST-1's two reports), inside the
adapter's 15 s. No crew is ever alerted: TEST-1 has no crew, and `test_alerts_to_crews` proves it. Test rows
are left out of every integrity monitor and checker count (some queue keys count them, section 8), and the
probe never writes the users' log.

## 10. The checker

`targets/dispatch/checker.py`:

- `verify(control, *, window_s=20.0, lag_s=10.0, since_t=None)` gives the verdict;
- `record_baseline(control, window_s=10.0)` runs once at the end of warm-up;
- `p95_allowed(baseline)` gives the band.

It reads the users' log, every surge log, cad-db (read-only, 5000 ms busy timeout) and `checker_baseline.json`.
It never reads observe(), monitors, `changes.jsonl`, `actions.jsonl` or labels.

**Cost.** Every call reads the whole users' log and `incident_events`, so `verify` slows as a copy runs, even
without `since_t`. In the soak (section 7, four copies sharing the machine) it took 14-19 ms at minute 1. At
minute 30 it took about 190 ms without `since_t` (291 ms at most) and about 400 ms with `since_t` at the start
(482 ms at most).

### 10.1 Constants

| Constant | Value | Meaning |
|---|---|---|
| `MIN_JOURNEYS` | 20 | fewest calls in a window |
| `SUCCESS_RATE` | 0.99 | |
| `ANSWER_P90_MS` | 750 | NENA 15 s at 1:20 |
| `SLO_P95_MS` | 1000 | NENA 20 s at 1:20 |
| p95 band | `min(1000, max(2b, b + 250))`, b the warm-up answer p95; 1000 with fewer than 10 answered warm-up calls | the bank's rule |
| `DISPATCHABLE_S` | 3.0 | told at most this long after answer |
| `REACH_LIMIT_S` | 3.0 | first real crew en route at most this long after told |
| `LAG_ALLOW_S` | 3.0 | unit-record lag allowance |
| `CLOCK_TOL_S` | 0.05 | a record may lead its crew by at most this much |
| `RECORD_SAMPLE_S` | 0.1 | sample step for rule S |
| `STUCK_S` | 3.0 | an assignment older than this, with no crew, is no longer being worked |
| `LOC_TOL_KM` | 0.1 | incident location tolerance |
| `BUCKET_S` | 5 | impact buckets |
| `IMPACT_SAMPLE_S` | 0.5 | impact's unit-record sampling |
| `FOR_OPERATIONS_CAP` | 50 | |
| `FIELD_WAIT_S` | 3.0 | a pending report older than this is waiting (information only) |

**`LAG_ALLOW_S` stays 3.0 s** (DECISIONS, dispatch row 2). Over 43,802 status changes the healthy apply lag
was 0.209 s at p99.9 and 0.356 s at most (section 7), so amendment D5 allowed 1.5 s. It stays 3.0 s because
every table and break-and-heal result here was measured at 3.0 s, and the transfer run puts three copies on one
laptop. The cost: a record that lags its crew by less than 3.0 s, still showing a state the crew held in the
last 3.0 s, is never counted. A record that is simply wrong is counted however briefly it lasts: a row showing a
state the crew did not hold from 3.0 s before it to 0.05 s after it counts under rule W (10.4), for example
`onscene` written while the crew is still en route. A crew is away from `available` for at most about 2.9 s per
job, so a unit record stuck at `available` is never counted: a unit frozen there shows as incidents with two
crews en route, not as wrong unit records (10.4, 11.7).

### 10.2 Notation

- **Window.** `hi = now − lag_s` and `lo = hi − window_s`. W is the caller lines, from both sources, with
  `lo ≤ t_start < hi`. Test numbers never count.
- **E(c)** is every caller line with c's `emergency_id`.
- **Reached(I)** is the earliest crew `status enroute` line for incident I from a real unit.
- **F_u(x)**, the crew truth for unit u, is the state of u's latest crew `start` or `status` line at or before
  x, or (available, none) before the first. **R_u(x)**, CAD's record, is the state of u's latest `unit_history`
  row at or before x.
- **belongs(c)**, for a told call c with incident I: I was inserted with `test` 0 (from `incident_events`); its
  `first_call_id` is a call of c's emergency; it was not deleted before c was told; and a linked call was linked
  while I was still open. Otherwise the reason is the first that applies, in this order: `missing` (never
  inserted, or deleted before c was told; an insert made after c was told still counts), `test`,
  `other_emergency` or `closed_before_link`.
- **details_ok(c)**: cad holds the call on I. When the call created I, I also carries the caller's number and
  nature, the nature's priority, and a location within 0.1 km of the caller's.

### 10.3 Journeys

A call in W succeeds when the caller was told, at most 3.0 s after answer; the incident belongs; the details
are right; and a real crew went en route at most 3.0 s after told (for a linked call, an earlier reach counts).

`journeys` holds `n`, `ok`, `success_rate`, `p95_ms` and `p90_ms` (answer time over answered calls, null when
none), `p95_allowed_ms`, `by_source {normal: {n, ok}, surge: {n, ok}}`, `linked`, and `failures`. Each failed
call counts once, in its first failing category. `failures` and the reason sentence list the categories in the
order below, leaving out those with no call:

| Key | Reason text |
|---|---|
| `not_answered` | not answered |
| `rolled_over` | rolled over to the backup centre |
| `not_told` | answered but not told help is on the way |
| `slow_entry` | told more than 3 s after answer |
| `no_incident` | told with no incident of theirs in CAD |
| `details_wrong` | entered with details other than the caller's |
| `not_reached` | with no crew en route within 3 s of being told |

**Zero failed calls on a healthy copy.** A window holds about 49 calls and the success rate must be at least
0.99, so one failed call makes a window red (48 of 49 is 0.98). A healthy copy fails none.

### 10.4 Integrity

Each blocking count is exact, reads 0 when healthy, and blocks `recovered`. Its reason sentence is the one the
verdict shows. A count over calls takes every call in W that fits it, whatever its category in 10.3: a call told
more than 3 s after answer is `slow_entry` there, and still counts here if its incident does not belong or its
details are wrong.

| Key | Definition | Reason sentence |
|---|---|---|
| `told_without_incident` | calls in W told help is on the way that do not belong. `told_without_incident_by` splits them `{missing, test, other_emergency, closed_before_link}` | "N callers were told help is on the way but CAD holds no incident of theirs" |
| `incidents_dropped` | distinct incidents I told to a call in W that belongs, told at least 3.0 s before the verdict, where no real crew ever went en route to I and, at the verdict, CAD is not working I: I is not `pending` and has no `assigned` or `alerted` assignment made in the last 3.0 s. So a closed incident stops being worked the moment it closes, whatever its `close_reason` (the checker never reads it), and an incident deleted after the caller was told counts here. An incident whose assignment has waited more than 3.0 s for its alert or for the acknowledgement timer also counts while it waits, though CAD has not given it up | "N incidents callers were told about were dropped: no crew ever went en route and CAD is no longer working them" |
| `unit_records_wrong` | real units wrong by rule W or rule S (below), each counted once. `unit_records_wrong_by` gives `{wrong_writes, units_behind}`: `wrong_writes` is the number of rows that break rule W (one unit can write several), and `units_behind` the number of units that break rule S | "N units' CAD records differed from their crews for longer than the 3 s status lag" |
| `duplicate_incidents` | for each emergency with a call in W, its real incidents (deleted ones included) created while another of them was still open. Two created in the same millisecond (one transaction) are ordered by id, so the second counts | "N incidents duplicate an open incident of the same emergency" |
| `incidents_double_sent` | distinct incidents told to a call in W that belongs, with two or more real crews en route | "N incidents had more than one crew en route" |
| `units_double_committed` | real units with two assignments whose times overlap, the overlap meeting [lo, hi) | "N units were committed to two incidents at once" |
| `incident_details_wrong` | calls in W told, belonging, without details_ok | "N calls were entered in CAD with details other than their callers'" |
| `test_alerts_to_crews` | crew `alert` lines in [lo, hi) for a test incident | "N test alerts reached a crew" |
| `wrongly_quarantined` (also `harmful_quarantines`) | field reports set aside, at any time and by anyone, that are readable (section 11.2) | "N readable field reports have been set aside" |

- **Rule W (wrong write).** A `unit_history` row of u at `t_w` in [lo, hi) shows a state u's crew did not hold
  at any time in [`t_w` − 3.0, `t_w` + 0.05].
- **Rule S (left behind).** At some sample x = lo + k × 0.1 before hi, CAD's record R_u(x) is a state u's crew
  did not hold at any time in [x − 3.0, x + 0.05].
- So CAD's record may show any state the crew held in the last 3.0 s, and may never lead it by more than 0.05 s.
- **Blind spot.** A record stuck at `available` is never counted. Rule W sees only rows written in the window,
  and a stuck record writes none. Rule S allows any state the crew held in [x − 3.0, x + 0.05], and a crew is
  away from `available` for at most about 2.9 s per job: turnout keeps its logged status `available`, the drive
  is at most about 1.6 s inside the grid (1.8 s cap), and the scene at most 1.2 s. A record stuck at `enroute` or
  `onscene` is counted about 3 s after its crew leaves that state, because CAD then never sends the unit again
  and the crew stays free.

**Counted, not blocking:** `calls_dropped` (calls in W with outcome `dropped` or `cut_off`), `incidents_waiting`,
`unreadable_set_aside` (unreadable reports set aside) and `field_messages_waiting` (pending reports older than
3.0 s now).

**The verdict.**

```text
integrity.ok = every blocking count is 0
slo_ok       = n >= 20 and success_rate >= 0.99 and p95_ms <= p95_allowed_ms and p90_ms <= 750
recovered    = slo_ok and integrity.ok
```

`reasons` lists the service-level sentences first, in the order below, then one sentence per blocking count that
is not 0, in the order of the 10.4 table. The failures sentence names its categories in the order of the 10.3
table, and X and Y are in ms, rounded to 0.1 and printed without trailing zeros (for example 257.9 or 2488):

- "only N calls started in the 20 s window; at least 20 are needed";
- "K of N calls failed: <count> <reason text>, ...";
- "no call in the window was answered";
- "answer time p95 X ms is above Y ms";
- "answer time p90 X ms is above 750 ms".

### 10.5 `integrity.for_operations`

People's work. It never blocks on its own. Items are sorted by time (a set-aside report by when it was set
aside, a dropped incident by when it was inserted), and only the first 50 are kept.

- `{"kind": "set_aside", "item": <row id>, "unit": <the report's unit if readable, else null>}` for every field
  report set aside, at any time.
- `{"kind": "dropped_incident", "incident_id": I, "calls": [call ids]}` for every real incident told to a call
  that belongs and started before the window, that no real crew ever reached and CAD is no longer working, and
  whose emergency never had another incident reached (any other incident created by a call of the same
  emergency, such as the new one a callback opens after the first one closed). The window's own dropped
  incidents block through `incidents_dropped` instead.
- Callers told help is on the way with no incident before the window are not listed: CAD holds nothing staff
  could find. Impact counts them.
- `item` and `incident_id` are the identities. `unit` and `calls` are information.

### 10.6 Impact (with `since_t`)

- Calls with `since_t ≤ t_start < hi`, from both sources, go into 5 s buckets. A bucket meets the SLO when its
  success rate is at least 0.99 and its answer p95 at most 1000 ms (the flat SLO, not the band).
- `breach_seconds` is 5 × the buckets that missed. `failed_journeys` is the calls in the span that did not
  succeed. `time_to_mitigate_s` and `mitigation_censored` follow the kit's rule.
- Dispatch also gives `since_t`, `until_t`, and over [since_t, hi): `told_without_incident`,
  `incidents_dropped`, `unit_record_wrong_seconds` (rule S on a 0.5 s grid, wrong units × 0.5 s),
  `calls_dropped`, `duplicate_incidents` and `incidents_double_sent`.

### 10.7 Baseline and the command line

- **Baseline.** At the end of warm-up the checker reads the warm-up's calls and writes `{t, window_s, n,
  success_rate, answer_p95_ms, answer_p90_ms}` to `checker_baseline.json`, with nulls below 10 answered calls.
  It never raises. Only `p95_allowed` uses it.
- **CLI.** `python -m targets.dispatch.checker --data runs/dispatch-9500 [--window 20] [--lag 10] [--since T]`.

## 11. What each dispatch channel offers a fault

These are facts about dispatch, not recipes. The incident's author picks the component, mechanism, class,
values and channel. A Control `deploy` or `set_config`, a `stop` or `start` with `log_change` true, and each
action the agent carries out record a change in the feed observe() shows. `kill`, `link`, `admin`, `spawn`,
`surge` and datastore writes record nothing.

### 11.1 Channels

| Channel | Dispatch detail |
|---|---|
| Processes | `control.kill(component) -> bool` crashes a process with no change recorded; observe() then shows the exit (`exits_15m`, `last_exit_code`). `control.stop(component, actor="operator", log_change=True) -> bool` and `control.start(component, actor="operator", log_change=True) -> bool` work for call-handling, cad, dispatcher, alerting, alerting-backup, unit-sync and call-network. A stop records a change but no exit, so observe() shows the process `up` false with no new exit. start returns False while the process runs, a hung one included, so a hung process needs a stop first, or a restart. Nothing restarts by itself. A restart of call-handling loses every call between dial and report: a dial in progress is cut off (`cut_off`), a report gets 404 or a refused connection (`dropped`; on Windows a refused connection usually ends as `timeout`, 5.1), a dial made while it is down is refused (`refused`), and the caller redials. Each of these calls is a failed journey, and the cut-off and dropped ones also count in `calls_dropped`. At everyday load any restart of call-handling, a deploy included, loses about 3 calls and turns the verdict red for about 20 s (measured: from 10.7 s to 29 s after a build-label deploy: "3 answered but not told"), and the lost calls count in impact. During a surge at the cap about twice as many calls are in flight, so a restart loses about twice as many (from the code, not measured). So judge that a change "stays green" at least 30 s after it. A restart of cad likewise fails the reports that reach it meanwhile (call-handling answers 502, `not_entered`); this was not measured |
| Releases | `control.deploy(component, release, module_path=None, actor="pipeline") -> bool` restarts the component on that release, and returns True once the new process answers its health check, within 6 s. With `module_path` (a relative path is taken from the caller's working directory) it first copies the file to `<data>/releases/<component>/v<release, dots as underscores>.py` (release 3.5 is `v3_5.py`), so nothing the agent reads names the source file. A missing file makes `deploy` raise and changes nothing. If the release cannot be found or imported, or its `Release` fails to start, the process exits and `deploy` returns False: the deploy is already in the changes feed, and the component stays down on the new release, with the exit in observe() and the traceback only in `logs/<component>.out`, which logs() does not read. A restart starts the same release again; `rollback` returns to the previous one. The module defines `class Release`, usually subclassing the current one (`from targets.dispatch.releases.cad.v3_4 import Release as Base`). The repository's releases are `targets.dispatch.releases.<image>.v<x_y>`, with image `call_handling`, `cad`, `dispatcher`, `unit_sync`, `alerting` (alerting-backup's too) or `call_network`. A deployed release must not import anything from `faults/`, or that path shows in its tracebacks: component logs strip only the repository root and the data folder from traceback paths. Keep what it needs in that one file. Besides the Python standard library (threads included), import only from `targets.dispatch.releases`, the shared modules (`worker`, `cadstore`, `fieldmsg`, `area`) and `ic.kit`. Release labels look like normal versions (3.5, 2.1.2). Use one the component has not run: a deploy under the running label adds nothing for `rollback` to return to, and one under a repository label (3.4.1, say) replaces that release on this copy. Every `up` starts from an empty data folder. Releases in the repository: call-handling 5.2 and 5.2.1; cad 3.4 and 3.4.1; dispatcher 2.1 and 2.1.1; unit-sync 4.0 and 4.0.1; alerting and alerting-backup 1.6 and 1.6.1; call-network 1.0. Each x.y.1 is a harmless build label. `rollback` returns to the previous release on call-handling, cad, dispatcher and unit-sync. alerting has no rollback: its fix is `failover`. alerting-backup's releases matter only after a failover. A release on call-network is an external outage |
| Release API | Frozen at the merge. After the link thresholds below: each release's methods, what they take and return, which calls which, and the behaviour they carry |
| Settings | Section 3. `control.set_config(component, key, value, actor="operator") -> bool` stores any JSON value, usable or not, versions it, shows it in `changes` and returns True; the component judges the value when it next reads its settings (a worker at the start of its next cycle), within about 0.5 s on a healthy copy. A worker paused by an unusable value stays up and answering but does no work, so unit-sync's `head_item.attempts` does not rise. `revert_config` with `{"key": k}` restores the value that the newest change to k replaced, not the default; with no key it undoes the newest change the agent did not make. Which alerting side the dispatcher uses is routing state that only `failover` changes |
| Pending incidents | `incidents.status = 'pending'`, dispatched by priority then id, up to `batch_size` per cycle every `poll_interval_s`. Test incidents come first, from their own query, and an incident with no free unit does not use up the batch. A unit is free when its record shows `available` and it holds no open assignment (the 30 s rule below also applies). An incident gets a free unit of its preferred type when there is one, else of any type: the closest, ties going to the lower unit id compared as text (M10 before M9), or the first in roster order under `station_order`. With no free unit an incident waits; nothing closes it. An unacknowledged assignment becomes `no_ack` after `ack_timeout_s`, and its incident returns to `pending`. That unit is not offered that incident again for 30 s (`REOFFER_S`, counted from the `no_ack`), so the next free unit goes; after that it may be. So during an alerting outage incidents keep cycling through the units. While no acknowledgement reaches CAD (alerting down, or unit-sync applying nothing), each try ends in a WARN `no_acknowledgement` line and a new commit, so the dispatcher's `processed_per_s` stays high (7.3 measured in the alerting hang of section 12) and `queue_depth` grows by about 2 a second, as in the measured run below (for unit-sync, `queue_depth` was measured too, section 6: 51, 120 and 185 after 30, 60 and 90 s; `processed_per_s` is from the code, not measured). The timer runs once per dispatcher cycle, so a try lasts `ack_timeout_s` or a little more, and about 2.5-3.3 s in a hang, where each cycle first waits one `alert_timeout_s` (from the code, not measured). `units_not_acknowledging` therefore reads mostly 0, as the timer ends most assignments before 3.0 s. In a hang a try can now and then pass 3.0 s: that key then reads above 0 for a moment, and a verdict taken at that moment could count the incident as dropped (10.4; from the code, not measured). The measured alerting hang (section 12) showed no incident dropped. (Before this rule, an outage longer than about 40 s, 20 units × 2.0 s, left incidents that every unit had missed waiting for good.) Once alerts get through again, the backlog is dispatched, each incident within 30 s of its last miss when a unit is free. Measured once with this rule, on one copy: during a 75 s alerting outage (a `dispatcher->alerting` drop of 1.0) the dispatcher's `queue_depth` rose to 148, and some incidents went back to pending more than 20 times (up to 29). After the outage ended the backlog read 136, 99, 64, 35, 3 and 0 at 5 s steps. The verdicts, taken every 20 s, were red 20 s after the outage ended ("43 of 46 calls failed: 43 with no crew en route within 3 s of being told" and "7 units were committed to two incidents at once") and 40 s after ("9 of 47 calls failed: 9 with no crew en route within 3 s of being told"), and green from 60 s on. A longer outage leaves a longer backlog, so green comes later after the fix (11.6). An `enroute` or `onscene` incident whose last open assignment expires this way closes `completed`. These are live calls: they cannot be set aside, and the dispatcher skips an unreadable incident rather than crash |
| Field-report queue | Table `field_queue` (pending, applied, skipped, quarantined). unit-sync takes the oldest pending rows in id order, up to `batch_size`, and parses them all before writing. An unreadable report (11.2) crashes unit-sync by design, after the readable reports before it are committed and its own `attempts` raised. unit-sync stays down until restarted, and `head_item` names that report with `attempts` at least 1. A report is skipped when it is too old (`max_message_age_s`), when a later readable report of the same unit is pending as unit-sync takes the batch (superseded: a higher row id, whatever the two reports' `t`, with the unit read from the report itself, not the `unit_id` column), or when it is out of order. cad stores any JSON object of at most 4 KB at intake, without checking fields. Rows can be added through `control.db("cad-db")`, or by a helper posting to cad `/mdt` a bounded, one-off set of reports. Fix: `quarantine` with `params.item` = the row id = `head_item.id`, then `restart`. Each unreadable report needs its own quarantine |
| Ordering memory | unit-sync remembers, in memory only, the newest report time it has applied for each unit, and skips anything not newer. A restart forgets it. Report times are the terminal's clock. This is the system's one in-memory state that only a restart clears |
| Repeat calls (idempotency) | `calls.call_id` is the primary key, and entry is idempotent by `call_id` inside cad's write transaction. Under `repeat_match` "ani_open", cad links a call to this number's open incident (same number and test flag, status pending, dispatched, enroute or onscene) |
| Caller behaviour | Section 5.1: about 2.2 emergencies per second, ring until answer or rollover, ALI read-back with a spoken fallback, talk, report, the redial rules, 10% callbacks, at most 9.1 s per call |
| Crew behaviour | Section 5.2. Crews read both station inboxes, and a busy crew ignores alerts. A full-state heartbeat goes every 1.0 s. A failed post is not retried, and a report older than 2.0 s is dropped at the terminal. Unit records heal within about 1 s once the path works. After a unit-sync outage, add the time unit-sync takes to work through the reports queued meanwhile, which arrive at about 27 a second: it takes at most `batch_size` (200) a cycle, oldest first, a cycle every 0.2 s or a little more, and a record heals only when its unit's newest report is reached. That is a few seconds after a 2-minute outage (from the code, not measured) |
| Unit records | Only unit-sync writes `units`, apart from the seed and the probe's TEST-1 cleanup. Keep the `unit_history` and `incident_events` triggers: they are the checker's evidence. A one-time direct write to `units.status` or `units.incident_id` is overwritten by the next heartbeat within about 1 s, so it never lasts into a verdict |
| Locks | `control.spawn("incident-archive", ["{python}", "-m", "targets.dispatch.jobs.incident_archive", "--data", "{data}", "--hold-lock", "<S>"])` holds `BEGIN IMMEDIATE` on cad-db for S seconds. It registers `{"session": "incident-archive-<pid>", "pid", "since_t", "mode": "write", "statement": "INSERT INTO rms_export ... (export batch)"}` in `cad_locks.json`. observe() shows it under cad-db's `lock_holders`, and `release_lock` on cad-db ends it. Readers keep working (WAL). Every writer waits for its busy timeout and fails. A lock must be held at least about 130 s to still act in the scored window |
| Helper processes | incident-archive modes: `--export` (normal, about 1 s, batches of at most 50 rows, never registers as a lock holder; measured: 2,008 incidents in 0.4 s and 3,679 in 0.8 s, with no lock holder shown and the copy green), `--hold-lock S`, and `--cpu S` (a harmless busy run at low priority: a background change). `runs` counts only running jobs spawned under exactly the name `incident-archive`; `cpu_pct` and `mem_mb` sum each run and the processes it started, and the first observe() of a run reads `cpu_pct` 0. Anything else spawned is invisible to the agent, and no action reaches it, except `release_lock` for registered lock holders |
| Datastore writes | `control.db(name=None) -> sqlite3.Connection`: `db("cad-db")` or `db()` gives autocommit, a 5000 ms busy timeout and `sqlite3.Row`. Any other name raises KeyError. Schema in section 4 |
| Links | `control.link(route, latency_ms=0, jitter_ms=0, drop_pct=0.0) -> bool` sets all three values (one left out goes back to 0), records no change, and acts within about 0.2 s. The relay delays each chunk it reads from the caller by `latency_ms` plus a fresh uniform 0-`jitter_ms` draw; answers are not delayed. A request is usually one chunk, but the client writes its headers and body separately, so now and then a request is delayed twice (from the code, not measured). `drop_pct` is a fraction of connections, 0.0-1.0; a dropped connection is closed before it reaches the far side. The measured thresholds are below the table. `"dispatcher->alerting"` is alerting as the dispatcher sees it; fix: `failover` on alerting, because the backup path bypasses the relay. `"call-handling->call-network"` is ALI as call-handling sees it; this is an external outage: escalate |
| Standby | alerting-backup runs the same image and writes its own inbox, and crews read both. It carries alerts only after `failover`. A change there alone shows nothing to users. `failover` does not check the standby: failing over to a stopped alerting-backup returns ok, and every alert then fails there until alerting-backup is restarted or alerts fail back with `{"to": "primary"}` to a working alerting. A failover with no `to` goes to the standby, and one to the side already active is refused |
| External | call-network is the provider's. Stopping, killing or hanging it, deploying a release to it, or slowing or dropping its link is `external_outage`, and must be escalated: escalating is the agent's outcome `escalated`, not an action. It has no actions, and the agent sees only call-handling's view of it, with no logs. Its observe() entry is that view alone, so a kill or a hang of call-network never shows exit keys (`exits_15m`, `last_exit_code`) or `not_answering` there. observe() shows it `up` false whenever every lookup in the observe() window (10 s by default) ended in an error (a 4xx answer is a reject and leaves it `up`), and `up` null when there was no lookup, so a link that drops every connection, or slows lookups past `ali_timeout_s`, also shows call-network down. Calls then go spoken, so callers are told later: the spoken location adds 1.2-2.0 s. Of the failed lookups, only one that times out also slows the answer, by about `ali_timeout_s` (0.5 s): a link latency of at least 0.5 s (answer p95 503 ms in the link table below), a hang, or a release that answers that late. A stop, a kill, a dropped connection, or a release that answers at once with an error or a wrong location leaves answer time unchanged at everyday load (the measured drop of 1.0 showed no answer-time reason; on Windows a stop or kill times out instead, 5.1). Each spoken call holds its position 1.2-2.0 s longer, so during a surge answers can still slow (from the code, not measured) |
| Admin hooks | `control.admin(component, op, payload=None) -> dict`, with `op="hang"` (the only op), on any process, returns `{"ok": true, "hung": true}`. Its HTTP server stops answering, `/health` and `/metrics` included, so observe() shows it `up` false with `not_answering` true and no exit keys, and every background loop stops at its gate. Nothing is recorded in the changes feed, and the hang lasts until the process is restarted: a stop then a start, or a `restart`, deploy or rollback, each of which restarts it |
| Call surge | `control.surge(rate_per_s, seconds, seed=0, mix="normal") -> int`, the helper's own pid (11.3). It is the only source of extra calls |
| Other Control calls | `control.snapshot() -> dict`, `control.baseline(window_s=10.0) -> dict`, `control.paths() -> dict`, `control.shutdown()` |
| Capacity and drain | The tables of section 6. A scored window holds about 49 calls, so a mechanism that touches one call in N misses a window with probability about (1 − 1/N)^49 |
| Checker rules a fault must respect | Section 10 exactly. Unreadable is 11.2. A readable report set aside keeps the checker red for good, so label `quarantine` only for unreadable rows. A call counts as reached only when a crew's own log says en route. Records may lag by 3.0 s and never lead by more than 0.05 s. Test data is excluded everywhere. The timing rule (11.6) |
| Actors and words | Actors are drawn from `pipeline`, `operator`, `ops-maintenance` and `scheduler`, and passed on every deploy, setting change, stop and start. No release label, session name, statement, log line, change detail or payload contains a fault type or class name, or the words fault, faults, inject, sealed, heldout, exam, poison, stale or chaos. These match as whole words, case ignored, with `_` counting as a word break, as `RESERVED` in `tests/dispatch/test_static.py` matches them (so `poison_message` counts and "example" does not). A lock holder's session name and statement show in observe(), and `release_lock` repeats the session names in its answer and in the changes feed. Use only made-up callers from the fictional number pools. Never log a caller's number, words or location |

**Link thresholds**, with no action. Measured on one copy while three other copies shared the machine, in the
same way as the harmless ranges (section 3): held 35 s, then three 20 s windows (lag 10 s) 20 s apart. Green
and red mean all three windows; flaky means a mix. The copy's band was 257.9 ms.

| Route | Change | Result | Reasons when red |
|---|---|---|---|
| `dispatcher->alerting` | latency 100 or 300 ms | green | |
| `dispatcher->alerting` | latency 600 or 900 ms | red | nearly every call not reached within 3 s; at 600 ms once also 7 incidents dropped |
| `dispatcher->alerting` | latency 1200 or 1500 ms | red | every call not reached; 7-11 units double committed; 2-5 incidents double sent |
| `dispatcher->alerting` | latency 300 ms, jitter 300 ms | red | 23-45 calls per window (of 48-53) not reached |
| `dispatcher->alerting` | latency 300 ms, jitter 800 ms | red | every call or all but one not reached; 5-7 incidents dropped; 2-3 units double committed; 1 incident double sent |
| `dispatcher->alerting` | drop 0.05 or 0.2 | green | |
| `dispatcher->alerting` | drop 0.5 | red | 32-41 of about 48 calls not reached; 4-7 incidents double sent; 12-17 units double committed |
| `dispatcher->alerting` | drop 1.0 | red | every call not reached |
| `call-handling->call-network` | latency 100 or 200 ms | green | (answer p95 108 and 209 ms) |
| `call-handling->call-network` | latency 300 ms | red | only answer p95, 308 ms |
| `call-handling->call-network` | latency 500 or 1000 ms | red | 9-17 calls per window told more than 3 s after answer; answer p95 503 ms |
| `call-handling->call-network` | latency 200 ms, jitter 200 ms | red | only answer p95, 385-401 ms |
| `call-handling->call-network` | drop 0.05 | flaky | 2 of 46, 0 of 49 and 1 of 49 calls told late |
| `call-handling->call-network` | drop 0.2 or 0.5 | red | 2-5 calls per window told late |
| `call-handling->call-network` | drop 1.0 | red | 10-19 of 45-52 calls told late |

- **`dispatcher->alerting` is limited by throughput**, not by `alert_timeout_s`. Alerts go out one at a time
  inside the dispatcher's cycle, so it alerts about 1/latency incidents per second (600 ms gives about 1.7,
  against about 2.2 arriving). The edge lies between 300 ms and a mean of about 450 ms (latency 300 ms with
  jitter 300 ms), far below `alert_timeout_s` (1.0 s). Red points went green 30-49 s after the undo. The
  dispatcher's `processed_per_s` counts commits, not alerts delivered: a commit made while alerts are held (after a
  failed alert) sends none, and a new commit follows each expired assignment, so it can read above 1/latency. From
  the code, not measured: an alert answered within `alert_timeout_s` holds nothing, however slowly it comes, so a
  cycle waits for each due alert in turn and can last many seconds. The timer then runs late, an incident whose
  assignment has waited more than 3.0 s counts as dropped while it waits (10.4), and the probe can fail at the
  dispatcher step ("no unit committed within 2.5 s") as well as at alerting.
- **Above `alert_timeout_s`** each alert times out, but the relay still delivers it, so a crew turns out just as
  the 2.0 s timer gives the incident to another unit: hence the double counts.
- **`call-handling->call-network`:** the latency edge is the p95 band, b + 250 ms, so it moves with the copy's
  warm-up p95 (about 258 ms on the measured copies). From 500 ms (`ali_timeout_s`) every lookup fails and calls
  go spoken. A call-network drop of 0.05 is flaky.
- Measured before the 30 s re-offer rule. With it, incidents no longer stay pending for good after a drop of 1.0
  (11.1, Pending incidents); the rest of this table should not change, but it was not measured again.

**Release API**, frozen at the merge; a rename needs a new row here. `->` gives what a method returns. Apart from
`routes()` and `extra_metrics(window_s)`, which the kit reads, the methods shown without it return nothing that is
used. A route's dict is its 200 answer:

| Release | Methods |
|---|---|
| call-handling 5.2 | `routes()`, `dial(request) -> {call_id, location, position}`, `take_position(call)`, `lookup_location(ani) -> {x, y} or None`, `report(request) -> enter_incident's answer`, `enter_incident(call, body) -> {told: true, incident_id, linked}`, `release_position(call)`, `background()`, `extra_metrics(window_s)` |
| cad 3.4 | `routes()`, `validate_call(body) -> call`, `find_call(conn, call_id) -> {incident_id, linked} or None`, `find_open_incident(conn, ani, test) -> incident id or None`, `create_incident(conn, call) -> incident id`, `link_call(conn, incident_id, call)`, `create_call(request) -> {incident_id, linked}` (201 for a new incident, below), `mdt(request) -> {queued: row id}`, `extra_metrics(window_s)` |
| dispatcher 2.1 | `cycle(conn, settings)`, `retry_alerts(conn, settings)`, `expire_unacknowledged(conn, settings)`, `pending_batch(conn, settings) -> [incident]`, `free_units(conn, incident) -> [unit]`, `recommend(incident, units, settings) -> unit or None`, `assign(conn, incident, unit) -> assignment or None`, `send_alert(conn, assignment, settings) -> bool` (delivered), and the helpers `any_unit_free(conn) -> bool`, `alerts_held() -> bool` and `unreadable(incident, incident_id) -> bool` |
| unit-sync 4.0 | `cycle(conn, settings)`, `take_batch(conn, settings) -> (items, latest)`, `parse(item) -> msg`, `in_order(msg) -> bool`, `apply_reports(conn, readable, settings, latest)`, `apply(conn, item, msg, settings, latest)`, `apply_unit(conn, msg)`, `apply_assignment(conn, msg)`, `clear(conn, unit, keep, now)` |
| alerting 1.6 | `routes()`, `alert(request) -> deliver's answer`, `deliver(alert) -> {delivered: true}` |
| call-network 1.0 | `routes()`, `ali(request) -> {x, y}`, `locate(ani) -> (x, y)` |
| `worker.Worker` (dispatcher and unit-sync) | `background()`, `run_loop()`, `wait(seconds)`, `db() -> conn`, `write_error()`, `extra_metrics(window_s)` |

**What the methods take.**

- **Requests.** A route gets `request`, a dict `{method, path, tail, query, body, headers}`: `body` is the parsed
  JSON (`{}` when empty), and `tail` is what follows a route path ending in `/*`. It returns a dict, answered 200,
  or raises `net.Reply(status, body)`. A `ValueError` that escapes it answers 400 `{"error": "request was not
  valid JSON"}` and logs nothing. Any other exception answers 500 and logs an ERROR `unhandled_exception` line
  with a traceback, at most one every 2 s for each exception type and path. Each request runs on its own thread,
  so state shared between requests needs a lock.
- **`settings`** is the component's settings as a dict, already checked (section 3), whole-number ones as int.
- **`conn`** is a cad-db connection in autocommit mode. Its rows are `sqlite3.Row`, read by name; `dict(row)`
  makes a dict. cad's `create_call` and `mdt` run their work in one `BEGIN IMMEDIATE` that cad commits, so
  `find_call`, `find_open_incident`, `create_incident` and `link_call` run inside it and must not begin or commit
  one. A `sqlite3.Error` there rolls it back and answers 503 ("cad-db busy" or "cad-db unavailable"), counted in
  `db_write_errors`. A worker's `cycle` gets its thread's connection with no transaction open, and each statement
  commits by itself unless a method opens `BEGIN IMMEDIATE` and commits it, as `expire_unacknowledged`, `assign`
  and `apply_reports` do. Leave none open: the next `BEGIN IMMEDIATE` on that connection then fails.
- **A worker's errors.** A `sqlite3.DatabaseError`, busy or locked included, ends the cycle: it is rolled back,
  counted in `db_write_errors` and logged as WARN `db_busy` or ERROR `db_error`, and the next cycle tries again.
  Any other exception crashes the process (ERROR `crash` with a traceback, exit code 1), and it stays down.
- **call-handling.** `call` is a dict `{call_id, ani, test, answered_t, position, location}`, where `location` is
  ALI's `{x, y}` or None. `enter_incident`'s `body` is `{nature, narrative, location}`, with the location the
  caller spoke or None; cad gets the spoken location when there is one, else ALI's.
- **cad.** `validate_call` returns `call`, a dict `{call_id, ani, nature, narrative, location: {x, y},
  location_source, test}`, or answers 400 naming the first wrong field.
- **dispatcher.** An `incident` is a dict `{id, nature, priority, unit_type, x, y, test}`, and a `unit` is `{id,
  type, station}`. An `assignment` is the alert that `send_alert` posts, `{assignment_id, incident_id, unit,
  station, priority, nature, x, y}`; one that `retry_alerts` reads also carries `unit_type` and `test`.
- **unit-sync.** `item` is a queue row as a dict `{id, payload_json, attempts}`. `msg` is `fieldmsg.Report`, an
  immutable namedtuple `(unit, kind, status, incident_id, t)` with `t` a float, read by field name (`msg.status`).
  `msg["status"]` and `dict(msg)` raise, and so crash unit-sync.
  `readable` is a list of `(item, msg)` pairs, and `latest` maps each unit to the id of its newest readable
  pending row.
- **The base class.** Each process builds one `Release(ctx)` and calls `serve()`; an `__init__` override calls
  `super().__init__(ctx)`. `ctx` is `{system, component, version, data_dir, port, ports, admin_token}`, and
  `self.version` is the release label. `background()` runs on its own thread. Every stop, restart, deploy and
  rollback kills the process, so what it held in memory (positions, the ordering memory, threads) is gone.
  `self.call(dep, method, url, payload, timeout)` returns `(status, body)` or raises `net.CallError`, whose
  `kind` is timeout, refused, http (a 4xx or 5xx, with `status` and `body`) or bad_response, and it counts the
  call under `dep` in observe()'s `dependencies`. `self.log.info`, `.warn` and `.error(event, msg, **fields)`
  append a line to `logs/<component>.jsonl`, which logs() reads; `self.log_every(key, interval_s, level, event,
  msg, **fields)` writes at most one line per interval, with an `occurrences` count. "Actors and words" applies.

**Who calls whom.** Base methods call each other through `self`, so an override changes what its callers get.

- call-handling: `dial` checks the body, then calls `take_position`, which holds the lowest free position and sets
  the call's `position` and `answered_t`, and then `lookup_location`. `report` takes the call out of memory,
  checks the body, answers with what `enter_incident` returns, and calls `release_position` whatever the answer.
- cad: `create_call` calls `validate_call`, then, in its transaction, `find_call`. For a call it does not hold it
  calls `find_open_incident` under "ani_open", and `link_call` when that finds an incident, else `create_incident`.
- dispatcher: `cycle` calls `retry_alerts` (which calls `send_alert` for each due alert), `expire_unacknowledged`
  and `pending_batch`, then for each incident `free_units`, `recommend`, `assign` and `send_alert`, with
  `unreadable`, `alerts_held` and `any_unit_free` as helpers.
- unit-sync: `cycle` calls `take_batch`, which also calls `parse` on every pending row it reads, to find `latest`
  (rows past the batch come as `sqlite3.Row` with `id` and `payload_json` only). It then calls `parse` on each
  item; the first item whose `parse` raises anything is treated as unreadable (11.1, Field-report queue). `cycle`
  then calls `apply_reports`, which calls `apply` for each readable report. `apply` calls `in_order` and, for a
  report it applies, `apply_unit` and then `apply_assignment` with the same `msg`; `apply_assignment` calls
  `clear`.
- alerting: `alert` calls `deliver`. call-network: `ali` calls `locate`. A worker's `background` calls
  `run_loop`, which calls `db`, `cycle` and `wait`, and ignores what `cycle` returns.

**Behaviour the methods carry.**

- call-handling seats each call, in ring order, at the lowest free position while fewer than `positions` are
  held, and after `rollover_s` answers 503 `{"error": "rolled over", "at": "call-handling"}`. A call holds its
  position from its answer until its report is answered, whatever the answer; a call never reported is freed
  15 s after its answer. `lookup_location` returns None when ALI fails or takes over `ali_timeout_s`, and the
  call goes on with a spoken location. `enter_incident` tells the caller whenever cad answers 200 or 201 with a
  whole-number `incident_id`, without reading cad-db (the caller then needs 0 < id < 2^63, 5.1). It passes a
  cad 4xx on as it is, and answers 504 when cad does not answer within `cad_timeout_s` and 502 otherwise, each
  with `"at": "cad"`.
- cad's `create_call` answers a `call_id` it already holds with that call's incident (200). Under "ani_open" a
  call from a number with an open incident (same test flag) is linked to the newest one: `link_call` inserts the
  call's row with `linked` 1 (200). Otherwise `create_incident` inserts the incident (`pending`, `release` the
  release label) and the call's row, and returns the new id. A new incident is answered 201 `{"incident_id",
  "linked": false}`, raised as `net.Reply`, so code that wraps `super().create_call(request)` gets an exception
  there, not a return value; the others get 200 `{"incident_id", "linked"}`. Nothing reads the incident back.
- The dispatcher's `pending_batch` lists every pending test incident, then the real ones by priority then id,
  leaving out unreadable ones. `free_units` gives the units shown `available` with the incident's test flag
  that hold no open assignment, except one that failed to acknowledge this incident in the last 30 s
  (`REOFFER_S`). `recommend` gives a test incident only TEST-1 and a real one never. It keeps the units of the
  incident's `unit_type` if any are free, else all, and picks the closest station, ties going by unit id as
  text (M1 before M2, but M10 before M9), or under "station_order" the first in roster order (section 4). When
  a real incident gets no unit and no real unit is free at all, the batch ends. `assign` re-checks, in its
  transaction, that the incident is still pending and the unit still free.
- `send_alert` posts the alert to the active side with `alert_timeout_s`. Delivered, the assignment becomes
  `alerted`; otherwise it is sent again 0.3 s later. When an alert fails other than with a 4xx (no answer, a
  closed connection, a 5xx), alerts are held for 0.3 s: `retry_alerts` sends none while the hold lasts, and
  commits made meanwhile send none either (theirs go out on a later retry). So a silent path costs a cycle one
  `alert_timeout_s`, and one more each time a commit comes after a hold has ended. A path that is slow but
  answers holds nothing: each due alert and each commit's alert waits for its answer in turn, so a cycle can
  last seconds, the acknowledgement timer runs late, and an incident no crew has reached whose assignment has
  waited over 3.0 s for its alert counts in `incidents_dropped` (10.4). From the code, not measured; the link
  thresholds above show such counts.
- No release holds a cad-db transaction across a network call.
- unit-sync's `apply` skips a report that is too old, superseded or out of order (Field-report queue row), and
  otherwise calls `apply_unit` and then `apply_assignment` with the same report. `apply_unit` sets `status`,
  `incident_id`, `status_t` (the report's `t`), `applied_t` (unit-sync's clock) and `source` `field`. It moves
  `status_since` to unit-sync's clock only when the status or the incident changes, as the history trigger
  does, and cad's status timer (`unit_status_timers_expired`, section 8) counts from `status_since`.
  `apply_assignment` keeps assignments in step with the state a report carries: `enroute` or `onscene` for X acks
  (or inserts, source `field`) the unit's assignment to X, moves X on (never back, and never out of `closed`) and
  clears its other acked or on-scene ones; `available` clears acked and on-scene assignments and leaves
  `assigned` and `alerted` ones to the timer; `outofservice` changes only the unit record. An incident left with
  no open assignment closes `completed`. A report for an incident that does not exist changes only the unit
  record, with a WARN line.
- call-handling, cad, the dispatcher and unit-sync each log an INFO line for their normal work, with the ids
  involved: call-handling `call_answered` and `call_entered`, cad `incident_created` and `call_linked`, the
  dispatcher `unit_assigned`, and unit-sync `status_applied` when a unit's status or incident changes. So
  logs() shows the incident ids a release hands out. An override that skips a base method also skips its line.

### 11.2 Unreadable field reports

`fieldmsg.parse(payload_json)` is the one definition, shared by unit-sync and the checker. `unreadable(payload)`
is true exactly when `parse` raises. A report is unreadable when any of these holds:

- the payload is not valid JSON, or not an object;
- `unit` is missing, not a string, or names no roster unit (TEST-1 is on the roster);
- `kind` is not `status` or `heartbeat`;
- `status` is not `available`, `enroute`, `onscene` or `outofservice`;
- `incident_id` is neither null nor a positive whole number below 2^63 (a bool is not a number);
- the status and the incident disagree: `enroute` and `onscene` need an `incident_id`; `available` and
  `outofservice` need it null;
- `t` is missing, or not a finite number (a bool is not a number).

A future `t` is readable. Extra keys are ignored. Every report the crews and the probe build is readable, and a
readable report never crashes unit-sync 4.0. The checker judges with `fieldmsg` whatever a unit-sync release's
`parse` does: a report set aside that `fieldmsg` can read counts as `wrongly_quarantined` (10.4).

### 11.3 The call surge

```python
pid = control.surge(rate_per_s, seconds, seed=0, mix="normal")
# or directly:
control.spawn("call-surge", ["{python}", "-m", "targets.dispatch.surge", "--data", "{data}",
                             "--rate", "2.0", "--seconds", "150", "--seed", "7", "--mix", "normal"])
```

- `rate_per_s` is **emergencies per second**; each makes about 1.1 calls. All surges together are capped at
  **3.0 emergencies per second**, and a healthy copy stays green at the cap.
- `seconds` is 1-900. A surge whose `rate_per_s × seconds` is above 1,000 is refused. Arrivals are random, so a
  surge starts about `rate_per_s × seconds` emergencies, and it never starts more than 1,000: at the 1,000th it
  stops starting new ones but still runs its full `seconds`.
- `mix` is `normal` (everyday weights), `medical` (cardiac, breathing, fall, collision) or `fire`
  (structure_fire, vehicle_fire, alarm).
- `control.surge` returns the helper's own pid once it is registered in `surge.json`: the pid in its log file's
  name, its `emergency_id`s and its printed lines. It waits up to 5 s. On Windows a venv's `python.exe` is a
  launcher and the helper is its child, so this pid can differ from the one `control.spawn` returns.
- Numbers: the helper takes the first free number block and goes on from where that block got to (5.4).
- **Refused, never clamped.** A surge over the cap, with no free number block or with a bad argument, exits
  with code 2, prints one line `call-surge <pid>: refused: <reason>` to `logs/call-surge.out`, and places no
  call. `control.surge` then raises `RuntimeError("call surge refused: <reason>")`. If the helper neither
  registers nor exits within 5 s, it raises `RuntimeError("call surge <pid> neither registered nor refused
  within 5 s")`. Reasons include "the surges together would start 3.50 emergencies per second, above the cap of
  3", "all 5 number blocks are held by running surges", "rate x seconds is ... emergencies, more than the 1000
  numbers ...", "rate must be a number above 0 and at most 3 (emergencies per second)", "seconds must be a
  number from 1 to 900" and "mix must be normal, medical or fire".
- Emergencies start at random (exponential) gaps, each in its own thread, at most 64 at once. They follow the
  callers' redial, callback and timeout rules. The helper runs its full `seconds` whatever call-handling does,
  but starts no emergency, redial or callback after them. It then waits up to 10 s for calls in flight, and exits.
- It writes `logs/call-surge-<pid>.jsonl`, and prints only a started line, counts every 10 s, and a finished
  line.
- It is not a component, and it records nothing in the changes feed. The agent sees a surge only as more calls
  (rps, the call queue keys, the pending board).
- Measured: a surge of 3.0 per second for 150 s registered within 0.07-0.18 s, ran 151 s and placed 445
  emergencies (482 calls, all told). A second surge that would pass the cap was refused within 0.1 s.
- A fault that acts only during a surge needs the surge to cover the scored window, the calls that start 95-115 s
  after the last fault the case injects (11.6): start it with at least 130 s, and d s more when it starts d s
  before that fault.

### 11.4 Not a channel

No action can repair these, or they touch the users or the checker's evidence:

- direct writes to `incidents`, `calls`, `assignments`, `unit_history` or `incident_events`, or to the
  triggers;
- deleting a `units` row, or editing its `id`, `type`, `station` or `test`. The units channel is an UPDATE of
  `status` and `incident_id`;
- a helper that writes tables without a registered lock;
- a helper that keeps posting to cad `/mdt`. Only a bounded, one-off set of `field_queue` rows is a channel;
- `people.jsonl`, `logs/call-surge-*.jsonl`, the station inboxes and the people process, which must never be
  touched.

### 11.5 Root-cause classes on dispatch

| Class | Where it can arise |
|---|---|
| `process_down` | processes |
| `bad_release` | releases on call-handling, cad, dispatcher and unit-sync |
| `bad_config` | settings |
| `lock_held` | cad-db |
| `dependency_slow` | the alerting link, or a slow alerting release (failover) |
| `poison_message` | the field-report queue |
| `stale_cache` | the ordering memory (restart) |
| `resource_exhaustion` | a release that exhausts its process: CPU, memory, disk, connections or file handles used up, which a restart relieves only for a while (CONTRACT 4: restart buys time, then escalate). A release that ties up call-taker positions or another count it keeps in memory, and that a rollback cures, is `bad_release`, since the class names the mechanism that the fix reverses |
| `external_outage` | call-network and its link. No action reaches them: the agent escalates, which is an outcome (`escalated`), not an action |

### 11.6 Timing rule

The harness takes one verdict, about 125 s after the last fault the case injects (the alert 5 s after it, the
agent's 90 s, the 20 s soak and the 10 s lag), on calls that started 95-115 s after that fault (`window_s` 20,
`lag_s` 10), with `since_t` the first fault. A fault's time is the `t` in its manifest entry, else when its
`inject()` returns, so all the writes one fault makes count as one. Every fault counts, whatever it does: a kill,
a link change, a hang, a surge or a datastore write counts, although none of them shows in the changes feed. The
agent acts from about 5 s to 95 s after the last fault and never sees the verdict or its reasons.
**A fault must still act 95-115 s after the last fault.**
One that ends by itself before then (a short lock, a short surge, a one-time record write) is green with no
action, and the case is excluded.

A fix must also come early enough. A break that leaves incidents waiting for a unit (a stop, kill
or hang of the dispatcher, alerting or unit-sync, an unusable setting of the dispatcher or unit-sync, or a red
`dispatcher->alerting` link change) builds a backlog that grows with the outage, and fresh calls keep failing
until it has drained (section 6). Measured on unit-sync: the right fix applied 60 s
after the break was green at the verdict, and applied 90 s after it, red. An arm that fixes a unit-sync outage
later than about 70 s after the break is judged red even with the right fix. The 75 s alerting outage in 11.1
(Pending incidents), a `dispatcher->alerting` drop of 1.0 then undone, was red 40 s after the undo and green
from 60 s, so an arm that ends an outage of alerting or its link much later than about 70 s after the break is
likely judged red too (estimated from that run, not measured at the harness's timing). A dispatcher outage
drains faster (section 6). A break that leaves no backlog, of call-handling, cad or a lock on cad-db, is green
about 30 s after its fix (section 12).

### 11.7 The far-future report

A report dated far ahead freezes its unit's CAD record until unit-sync restarts: the ordering memory skips every
later report as out of order. It freezes the unit **only if no later report of that unit (a higher row id,
whatever its `t`) is pending when unit-sync next takes a batch**; otherwise it is skipped as superseded. Confirm
the freeze once its `field_queue` row has left `pending`: the row is `applied`, and the unit's `units.status_t`
equals the `t` you inserted. A `skipped` row was superseded, so insert it again (in the measured run the first
insert was superseded and the second froze the unit). A row still pending can still freeze its unit later, so
insert again only after the first has left `pending`.

What the verdict shows depends on the state the report carries, which is the state the record freezes in:

- **Frozen at `available`** (the crew is free or in turnout, the usual case). CAD keeps offering the unit. Its
  crew takes alerts, but its acknowledgements never reach CAD, so the 2.0 s timer sends each such incident to a
  second unit: "N incidents had more than one crew en route", and some calls may also miss the 3 s reach. The
  unit-records sentence never appears: the checker cannot count a record stuck at `available` (10.4, Blind
  spot). Measured: red after 16 s with "4 incidents had more than one crew en route" and nothing else; green 26 s
  after the restart.
- **Frozen while busy** (`enroute` or `onscene`, with the crew's incident). CAD shows the unit busy for good, so
  it is never sent again, and its crew clears and stays free. Rule S counts the record from about 3 s after the
  crew leaves that state, so the verdict (lag 10 s) shows "1 units' CAD records differed from their crews for
  longer than the 3 s status lag" from about 13 s after the crew leaves it, about 13-15 s after the freeze (the
  drive is at most 1.8 s, the scene at most 1.2 s). It goes on showing it until about 30 s after the restart
  (window 20 s plus lag 10 s), since the record heals within about 1 s of the restart. Until the restart the
  unit's last incident keeps its open assignment and stays open; then the crew's next report frees the unit and
  closes that incident `completed`. Not measured live.
- **observe().** Frozen at `available`, observe() showed only unit-sync's `unit_reports_overdue` 1. Frozen while
  busy, cad's `unit_status_timers_expired` also reads 1 once the record has shown that state for 4.0 s (from the
  code). Either way, unit-sync's log shows WARN `skipped` lines, "report N from <unit> skipped (out of order)",
  at most one every 2 s for each skip reason across the whole of unit-sync, not per unit; each names one report,
  and its `occurrences` counts the reports skipped for that reason since the previous line. A report skipped as
  superseded logs at INFO instead. The healthy soak wrote no WARN line.
- A report that changes the record to a state its crew did not hold in the last 3 s is also a wrong write (Rule
  W). One that repeats the record's current state writes no `unit_history` row, so it is never a wrong write;
  rule S judges the record as it stands.

## 12. Break and heal by hand

The validity matrix. Each row is red with no action at verdict time, and green within the soak after its
labelled fix when the fix comes early enough
(11.6). `control` is the copy's Control and `adapter` its adapter. A fix goes through the adapter, as
the agent's would. The reason column gives the sentences the verdict should show; N and K are counts, and X and Y
times in ms, rounded to 0.1 and printed without trailing zeros. A verdict gives the service-level sentences first,
then the integrity ones in the order of the 10.4 table, whatever their order in a cell.

**Timing, measured on one copy** with the checker's 20 s window and 10 s lag, before the 30 s re-offer rule
and with each break held about 35-40 s: red about 10 s after the break
(12-18 s for `positions` 1, `repeat_match` "off", the far-future report and the call-network drop), and green
26-41 s after the fix (the first of two green verdicts in a
row). The checker judges calls and records 10 s late (the lag), so a row
turns red about 10 s after its break, and green no sooner than 30 s after the last failing call.
After a longer outage of the dispatcher, alerting or its link, or unit-sync, green comes later, since fresh calls
wait behind a backlog that grows with the outage (section 6), and at the harness's timing such a fix can come
too late (11.6). A break that
fails calls already under way (for example a kill, stop or hang of call-handling, cad, the dispatcher or
alerting) can turn it red up to about 2 s sooner, about 4 s if callers give the location by voice: such a call
started before the break, and one failed call makes an everyday window (about 49 calls) red. Any restart of
call-handling, a build label on it included, loses the calls in flight (about 3 at everyday
load) and is red for about 20 s, so judge that a
change "stays green" at least 30 s after it.

| Break (Control) | Reasons with no action | Labelled fix (adapter) |
|---|---|---|
| `control.kill("call-handling")`, or `stop`, or `admin("call-handling", "hang")` | "K of N calls failed: K not answered"; "no call in the window was answered" | `act("restart", "call-handling")` |
| `control.kill("cad")`, or `stop`, or `admin("cad", "hang")` | "K of N calls failed: K answered but not told help is on the way"; also "N units' CAD records differed from their crews for longer than the 3 s status lag" (reports to `/mdt` are lost) | `act("restart", "cad")` |
| `control.kill("dispatcher")`, or `stop`, or `admin("dispatcher", "hang")` | "K of N calls failed: K with no crew en route within 3 s of being told" | `act("restart", "dispatcher")` |
| `control.stop("unit-sync")`, or `kill`, or `admin("unit-sync", "hang")` | "K of N calls failed: K with no crew en route within 3 s of being told"; "N units' CAD records differed from their crews ..." for the units whose record showed `enroute` or `onscene` when unit-sync stopped (a record stuck at `available` is never counted, 10.4). Acknowledgements never reach CAD and no incident closes, so each assignment expires after 2.0 s and its incident is sent again, and the units keep going to the oldest open incidents (priority, then id). Newer incidents soon get no unit at all: from about a minute after the break every call in the window fails this way, at the 125 s verdict too, and "N incidents had more than one crew en route" shows only in earlier verdicts. In section 6's runs, the verdicts taken 60 and 90 s after an unreadable report stopped unit-sync showed every call failing, with only the first two sentences (the "more than one crew" sentence showed at 30 s); the 125 s verdict with no action is from the code, not measured | `act("restart", "unit-sync")` |
| `control.admin("alerting", "hang")`, or `kill` or `stop` | "K of N calls failed: K with no crew en route within 3 s of being told". Nothing was dropped in the measured runs: when an alert fails, the dispatcher holds the other alerts 0.3 s and keeps committing, and incidents cycle through the units (11.1, Pending incidents). In a hang a try can now and then pass 3.0 s, so a verdict can also show "N incidents callers were told about were dropped: no crew ever went en route and CAD is no longer working them" (11.1; from the code, not measured) | `act("restart", "alerting")`; `act("failover", "alerting", {"to": "standby"})` also works, but only while alerting-backup runs: failover does not check it (from the code, not measured) |
| `control.set_config("call-handling", "positions", 1)` | "K of N calls failed: K rolled over to the backup centre"; "answer time p95 X ms is above Y ms"; "answer time p90 X ms is above 750 ms" | `act("revert_config", "call-handling", {"key": "positions"})` |
| `control.set_config("dispatcher", "ack_timeout_s", 0.05)` | "N incidents had more than one crew en route"; also "N units were committed to two incidents at once". No integrity key shows it; the changes feed does, and the dispatcher's log has a WARN `no_acknowledgement` line for nearly every assignment (section 8) | `act("revert_config", "dispatcher", {"key": "ack_timeout_s"})` |
| `control.set_config("cad", "repeat_match", "off")` | "N incidents duplicate an open incident of the same emergency". The changes feed shows it, and cad's `possible_duplicate_incidents` reads 2 for about 1-2 s after each callback, again and again while it lasts (section 8) | `act("revert_config", "cad", {"key": "repeat_match"})` |
| an unusable setting, e.g. `control.set_config("dispatcher", "batch_size", 0)` | the verdict is as if the component were stopped (section 3, Unusable). The dispatcher pauses: "K of N calls failed: K with no crew en route within 3 s of being told". unit-sync pauses and applies no report: as a stopped unit-sync (the unit-sync stop row above), counting the units whose record showed `enroute` or `onscene` at the change. call-handling answers 503 to `/dial` and `/report`: "K of N calls failed: K not answered"; "no call in the window was answered". cad answers 503 to `/calls` and `/mdt`: "K of N calls failed: K answered but not told help is on the way"; also "N units' CAD records differed ..." for the units whose record showed `enroute` or `onscene` at the change (from the code, not measured) | `act("revert_config", <component>, {"key": <key>})` |
| `control.link("dispatcher->alerting", latency_ms=1500)` (above `alert_timeout_s` 1.0), or `drop_pct=1.0` | "K of N calls failed: K with no crew en route within 3 s of being told". With the latency, also "N incidents had more than one crew en route" and "N units were committed to two incidents at once": each alert times out at 1.0 s but the relay still delivers it, so a crew turns out just as the 2.0 s timer gives the incident to another unit. With `drop_pct=1.0`, only the first sentence | `act("failover", "alerting", {"to": "standby"})` |
| `control.spawn("incident-archive", ["{python}", "-m", "targets.dispatch.jobs.incident_archive", "--data", "{data}", "--hold-lock", "600"])` (at least 130 s) | "K of N calls failed: K answered but not told help is on the way"; often "answer time p95 ...", "answer time p90 ..." and "N units' CAD records differed ..." | `act("release_lock", "cad-db")` |
| an unreadable report, inserted through `control.db()` (below) | unit-sync crashes, and from then on the verdict is that of a stopped unit-sync (the unit-sync stop row above), counting the units whose record showed `enroute` or `onscene` at the crash | `act("quarantine", "unit-sync", {"item": <head_item.id>})`, then `act("restart", "unit-sync")`; `for_operations` then lists `{"kind": "set_aside", "item": <id>, ...}` |
| a far-future report for one unit (below) | depends on the state it freezes (11.7). Frozen at `available`, the usual case: "N incidents had more than one crew en route", perhaps also "... no crew en route within 3 s ...", and never the unit-records sentence. Frozen at `enroute` or `onscene`: "1 units' CAD records differed from their crews ...", counted from about 3 s after its crew moves on, so shown from about 13 s after | `act("restart", "unit-sync")` |
| a bad release: `control.deploy(component, "<version>", module_path=<file>)` | depends on the mechanism; each shape is counted exactly | `act("rollback", component)` |
| call-network: `control.stop("call-network")`, or `control.link("call-handling->call-network", drop_pct=1.0)`, or a latency of at least `ali_timeout_s` (500 ms) | calls go spoken: "K of N calls failed: K told more than 3 s after answer"; with the latency also "answer time p95 X ms is above Y ms", as every lookup waits out `ali_timeout_s`. observe() shows call-network `up` false even when only the link drops every connection or slows every lookup past `ali_timeout_s`. A smaller delay (latency plus jitter) made no call spoken in the measured runs (a request the relay delays twice, 11.1 Links, can now and then pass `ali_timeout_s`; from the code, not measured): it is red only by "answer time p95 X ms is above Y ms", once answer p95 passes the band (about 258 ms), and green below it (11.1, Link thresholds) | escalate (no action); red with no action by design |
| a surge at or below the cap; `control.stop("alerting-backup")` alone; `--cpu`; a build label (`control.deploy("call-handling", "5.2.1")`); a harmless setting move | green; a build label on call-handling only from about 30 s after the deploy (its restart loses about 3 calls) | none: healthy or a background change |

**Measured** on one copy, before the 30 s re-offer rule; rows whose break leaves assignments
unacknowledged may differ under it (the header). Each break was held about 35-40 s before its fix. Red is
seconds from the break to the first red verdict, and green from the fix to the first of two green verdicts in a
row. The red reasons are those of the verdict just before the fix, about 35 s after the break; the harness's
verdict, 125 s after it, can differ (the unit-sync rows above).

| Break | Red reasons seen | What observe() showed | Red | Green |
|---|---|---|---|---|
| kill cad | 137 of 137 not told; 4 unit records | cad `up` false; call-handling `dependencies.cad` error rate 1.0; unit-sync `processed_per_s` 0 | 10.1 | 32.9 |
| stop unit-sync | 33 of 46 not reached; 14 double sent; 4 unit records | unit-sync `up` false, `queue_depth` 1212, `unit_reports_overdue` 20 | 10.1 | 40.7 |
| hang dispatcher | 47 of 47 not reached | dispatcher `not_answering`, `processed_per_s` 0, `queue_depth` 83 | 10.1 | 35.6 |
| hang alerting | 49 of 49 not reached; 45 of 45 in the failover run; nothing dropped | alerting `not_answering`; the dispatcher still committing 7.3 units/s; the probe fails at alerting | 10.4 | 40.5 (restart), 37.8 (failover) |
| kill call-handling | 135 of 135 not answered | call-handling `up` false | 10.1 | 30.8 |
| `positions` 1 | 29 of 46 rolled over; answer p95 2488 ms, p90 2481 ms | call-handling p95 2501 ms, error rate 0.44; the probe fails at call-handling, "503 rolled over" | 12.7 | 30.7 |
| `ack_timeout_s` 0.05 | 44 double sent; 15 units double committed | nothing; the changes feed shows it | 10.1 | 30.8 |
| `repeat_match` "off" | 6 duplicates | cad `possible_duplicate_incidents` 2 at 15 s, 0 by 35 s; the changes feed | 17.9 | 28.3 |
| link latency 1500 ms | 49 of 49 not reached; 3 double sent; 12 units double committed | dispatcher `dependencies.alerting` error rate 1.0; the probe fails at alerting, and after the failover names alerting-backup | 10.4 | 37.9 |
| hold-lock 600 | 129 of 129 not told; answer p95 863 ms, p90 770 ms; 4 unit records | cad-db `lock_holders` names the incident-archive session from 0.1 s after the spawn; `write_errors` 122 | 10.3 | 31.0 |
| unreadable report | 35 of 47 not reached; 11 double sent; 2 unit records | unit-sync `up` false, `last_exit_code` 1, `head_item.id` the inserted row with `attempts` 1 | 10.2 | 39.1 |
| far-future report, frozen at `available` | 4 double sent | unit-sync `unit_reports_overdue` 1, nothing else | 16.0 | 26.0 |
| call-network link drop 1.0 | 12 of 52 told more than 3 s after answer | call-handling `dependencies.call-network` error rate 1.0; call-network `up` false; the probe fails at call-network | 12.9 | no fix; still red 25 s later |
| build labels 5.2.1 and 2.1.1 | "3 answered but not told" from 10.7 s to 29 s after the call-handling deploy, then none | the changes feed | | |
| a surge at the cap, 150 s, medical | none | | | |
| alerting-backup stopped, with an `--export` | none for 60 s | alerting-backup `up` false; no lock holder | | |

- The kit's `exits_15m` and `last_exit_code` stay set for 15 minutes after an exit, so a copy that ran an
  earlier break still shows them.

**Inserting a report** (both report rows):

```python
import json, time
conn = control.db()
try:
    now = time.time()
    payload = json.dumps({"unit": "M3", "kind": "status", "status": "en route", "incident_id": None, "t": now})
    item = conn.execute("INSERT INTO field_queue (unit_id, payload_json, status, attempts, created_t, updated_t) "
                        "VALUES ('M3', ?, 'pending', 0, ?, ?)", (payload, now, now)).lastrowid
finally:
    conn.close()
```

- That payload is unreadable ("en route" is not a status). Within about 0.2 s unit-sync stops, and observe()
  shows unit-sync down with `head_item` `{"id": item, "attempts": 1, ...}`.
- For a far-future report, put the unit's current crew state and a `t` an hour ahead, for example `{"unit":
  "M3", "kind": "heartbeat", "status": "available", "incident_id": null, "t": now + 3600}`. Then check that
  `SELECT status_t FROM units WHERE id = 'M3'` equals that `t` (11.7). That example freezes M3 at `available`,
  which shows as incidents with two crews en route. To freeze it busy, send the `enroute` or `onscene` state
  with its incident while its crew holds it. CAD's own record, `units.status` and `units.incident_id`, follows
  the crew within about 0.2 s (the record lag in section 7).

**At the real timing.** The live tests run three families this way: kill dispatcher; hold-lock 600; an
unreadable report. With no action the verdict 125 s after the break (with `since_t` the break) is red. With the
labelled fix applied 5 s after the break it is green. No other row was run at the real timing; section 6 gives the
unit-sync verdict 125 s after the break for later fixes.

## 13. Running it

```text
python run.py up     --system dispatch --port-base 9500 --seed 7
python run.py status --system dispatch --port-base 9500
python run.py check  --system dispatch --port-base 9500
python run.py act restart unit-sync --system dispatch --port-base 9500
python run.py down   --system dispatch --port-base 9500
python -m targets.dispatch.checker --data runs/dispatch-9500 --window 20 --lag 10 --since <T>
```

- `up` starts every component in the start order, waits for health, warms up for 10 s, then records the
  checker's baseline. The data folder is `runs/dispatch-<port base>`.
- `status` shows every component as the agent sees it, and one probe. `check` gives the verdict.
- Pass `--system` and `--port-base` every time when more than one copy runs.

From Python:

```python
import time
from ic import systems

platform = systems.platform("dispatch", port_base=9500, data_dir="runs/dispatch-9500", seed=7)
platform.start()                                   # warm-up 10 s, then the baseline
adapter, control = platform.adapter(), platform.control()
try:
    t_break = time.time()
    control.set_config("cad", "repeat_match", "off", actor="operator")
    pid = control.surge(2.0, 150, seed=7, mix="medical")
    time.sleep(125)
    verdict = systems.checker("dispatch").verify(control, window_s=20, lag_s=10, since_t=t_break)
    print(verdict["recovered"], verdict["reasons"])
finally:
    platform.stop()
```

- `control.paths()` names every file the checker and harness read: `data_dir`, `logs`, `actions`, `changes`,
  `traffic_log`, `users_log`, `surge_logs`, `datastores`, `cad_db`, `locks`, `surge_registry`, `alert_inboxes`
  and `checker_baseline`.
- `tests/dispatch/test_live.py` brings copies up and down, and breaks and heals them. `IC_SLOW=1` runs the CI
  tier: one copy on port base 9700, about three minutes. `IC_SLOW=1` with `IC_DISPATCH_LONG=1` also runs the
  long tier: three copies on 9600, 9700 and 9800, the whole table and the real timing, about 25 minutes.
