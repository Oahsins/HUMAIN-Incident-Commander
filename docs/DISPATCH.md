# Dispatch: the test dispatch centre

Dispatch is the second test system. It is a simulated 9-1-1 dispatch centre that runs on `ic/kit`, like the
bank, behind the same adapter. This document gives the facts about it that an incident needs: what runs, what
the users do, what the checker counts, and what each channel offers a fault. You can write incidents from it
without reading the code in `targets/dispatch/`.

The facts follow the code. A line that starts with `MEASURED:` marks a number the measurement step still owes.
Do not use a guess in its place.

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

- the six actions with the bank's `est_seconds`, `undo` and `params`. `failover` takes `{"to": "standby" |
  "primary"}`, and `quarantine` takes `{"item": <extra.head_item.id>}`. The restart description warns that a
  restart of call-handling cuts off calls being answered;
- four forbidden lines: "close or cancel an incident", "change a call's priority", "stand down or reassign a
  unit committed to an incident" and "contact a caller". No action does any of these;
- one contact per component: shift supervisor (call-handling, dispatcher); CAD administrator (cad, cad-db,
  unit-sync, incident-archive); radio and alerting technician (alerting, alerting-backup); call network provider
  (call-network).

## 3. Settings

Every setting is a number or a named choice. A bool is never usable. The defaults are safe. A component reads
its settings at most 0.2 s old. The workers sleep in 0.25 s slices and wake early when a setting changes, so
`revert_config` takes effect within about 0.25 s.

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
- **Unusable.** A component with an unusable value writes one ERROR line `settings_unusable`, naming the key and
  never the value, every 2 s until the setting changes. It does not crash. A worker pauses its work.
- **Harmful.** A usable but harmful value is used as given. A dispatcher `poll_interval_s` of 30 makes every
  dispatch late.

**Harmless ranges**, for background changes:

MEASURED: the harmless range of every setting above, on three copies with a surge at the cap and without one
(`positions` both ways, dispatcher `poll_interval_s`, `ack_timeout_s`, unit-sync `batch_size`,
`max_message_age_s`, and the rest), from the step-7 soak.

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

- cad inserts `incidents` and `calls` in one transaction, and inserts `field_queue` rows.
- The dispatcher inserts and updates `assignments`, and moves incidents between `pending` and `dispatched`. It
  closes an `enroute` or `onscene` incident whose last open assignment expires (`completed`). It never writes
  `units`.
- unit-sync writes `units`, and updates `assignments`, `incidents` and `field_queue` from the reports.
- `units` holds only what the field reported, plus the seed and the probe's TEST-1 cleanup.
- incident-archive `--export` inserts `rms_export` rows only.

**Seed.**

- **Stations** on a 20 × 20 km grid: S1 (4, 4), S2 (16, 4), S3 (10, 10), S4 (4, 16), S5 (16, 16).
- **Units.** Station Sk has medics M(2k−1) and M(2k) and engines E(2k−1) and E(2k): M1-M10 and E1-E10. S2 has
  M3, M4, E3 and E4.
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
| `actions.jsonl`, `changes.jsonl` | the agent's actions, and every recorded change |

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
| `told` | the report answered 200 |
| `rolled_over` | the dial got 503 `{"error": "rolled over"}` |
| `not_answered` | the dial got another 5xx, or an answer without a call id |
| `rejected` | the dial got a 4xx, or the report a 4xx other than 404 |
| `refused` | the dial's connection was refused |
| `cut_off` | the dial's connection was reset, as a restart of call-handling does |
| `dropped` | after the answer, the report got 404, or a refused or reset connection |
| `not_entered` | the report got a 5xx |
| `timeout` | a client timeout at either step |

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
- **Alert.** For an alert to one of its units, it writes an `alert` line, with `taken` true only if the crew is
  free. A repeated `assignment_id`, or an incident the crew already served, is ignored and not logged. A busy
  crew does not respond.
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
| Surge callers | 40-89, five blocks of ten PP (1,000 numbers each) | one block per helper, so at most five helpers at once; a helper continues its block where the last one stopped | after 1,000 emergencies, at least 333 s at the cap |
| The probe | 99 (`099-555-0100` to `099-555-0199`) | NN = seq % 100 | |

## 6. Load, capacity and drain

**Everyday load on one copy.**

- About 2.2 emergencies per second plus 10% callbacks: about 2.4 calls per second, about 49 calls per 20 s
  window. The checker needs at least 20.
- About 20% of positions busy, and about 20% of units committed.
- About 27 field reports per second: 20 heartbeats plus about 7 status changes.

**Capacity.**

MEASURED: the capacity table, live on three copies: extra calls/s | calls per window | windows breaching |
medical incidents sent an engine | incidents waiting.

**Drain.**

MEASURED: the drain table: after the dispatcher has been out for D = 10, 30 and 60 s, with no surge and with a
surge at the cap, how long until fresh calls meet the reach target again.

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

MEASURED: healthy times on three copies with a surge at the cap: answer time p50, p90, p95, p99 and max;
told after answer; en route after told; record lag.

MEASURED: the p95 band chosen (the bank's band `min(1000, max(2b, b + 250))` with b the warm-up answer p95, or
a flat 1000 ms if the three-copy soak breached it), with the measured b.

## 8. Monitors

The kit fills the standard fields: rps, error and reject rates, latency, `dependencies`, the exit keys,
`not_answering`, `active` (alerting) and `running` (incident-archive). Dispatch adds the keys below. Each sits
on the component that owns that watchdog in a real centre. Each is current state and drops back to 0 once its
cause is fixed. Integrity counts leave out test rows and TEST-1; queue keys count every row.

| On | Key | Definition | Reason (real practice) | Healthy |
|---|---|---|---|---|
| call-handling | `queue_depth`, `oldest_pending_s`, `processed_per_s` | calls ringing now; the longest current ring; calls answered per second | the call queue wallboard | 0-1; under 0.1 s; about 2.4 |
| dispatcher | `queue_depth`, `oldest_pending_s`, `processed_per_s` | real `pending` incidents; seconds since the oldest was created; units the dispatcher committed per second. Read from cad-db, so they show while the dispatcher is down. No `head_item`: these are live calls | CAD's pending-incident list | 0-2; under 0.3 s |
| dispatcher | `integrity.units_not_acknowledging` | real units with an assignment `assigned` or `alerted` for more than 3.0 s | the "dispatched, not acknowledged" timer | 0 |
| cad | `integrity.unit_status_timers_expired` | real units whose record has been `enroute` or `onscene` for more than 4.0 s | the en-route and on-scene status (welfare) timers | 0 |
| cad | `integrity.possible_duplicate_incidents` | open real incidents that share a number with another open real incident | duplicate-call detection by number | 0 |
| unit-sync | `queue_depth`, `oldest_pending_s`, `processed_per_s`, `head_item {id, age_s, attempts}`, `quarantined_items` | pending field reports; age of the oldest; reports applied or skipped per second; the oldest pending report; reports set aside so far. Read from cad-db | the terminal message queue monitor | 0-30; under 0.5 s |
| unit-sync | `integrity.unit_reports_overdue` | real units with no report applied for more than 3.0 s | the terminal-not-reporting indicator | 0 |
| cad-db | `lock_holders [{session, mode, held_s, statement}]` | the live registered lock holders | the database lock view | `[]` |
| cad-db | `write_errors` | failed writes of cad, the dispatcher and unit-sync together; null when none of them answers | the failed-write counter | 0 |
| cad-db | `up` false with `extra.error` "cad-db cannot be read (<ExceptionType>)" | cad.db cannot be opened or read | | up true |
| incident-archive | `runs`, `cpu_pct`, `mem_mb` | running jobs named `incident-archive`, and their CPU and memory | the job monitor | 0, null |

The checker's counts (section 10) never appear in observe(). Staff learn of them through callbacks, crews on the
radio, or later review.

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
| 1 | call-handling | POST `/dial` (3.5 s timeout) answers with a `call_id` | the error, e.g. "rolled over" |
| 2 | cad | the report (nature `test`, a spoken location only if ALI gave none) answers told with an `incident_id`; a 502 or 504 whose `at` is `cad` names cad | the status and error |
| 3 | cad-db | the incident exists with `test` 1, is open, holds this call, and has the test location and priority | "incident not recorded" or "incident differs from the call" |
| 4 | call-network | the dial carried a location within 0.05 km of (0, 0) | "location not verified (unavailable)" or "location not verified (differs)" |
| 5 | dispatcher | an assignment of the incident to TEST-1 appears within 2.5 s | "no unit committed within 2.5 s" |
| 6 | alerting, or alerting-backup after a failover | the active side's inbox holds that assignment within 1.0 s | "alert not delivered on <side> within 1.0 s" |
| 7 | unit-sync | the probe, as TEST-1's terminal, posts `enroute` to cad `/mdt`, and TEST-1's record shows it within 1.5 s; then it posts `available` without waiting. A failed post is reported as step `cad` | "unit record not updated within 1.5 s" |

A healthy probe takes well under 1 s. The worst case is about 11 s, inside the adapter's 15 s. No crew is ever
alerted: TEST-1 has no crew, and `test_alerts_to_crews` proves it. Test rows are left out of every monitor and
checker count, and the probe never writes the users' log.

## 10. The checker

`targets/dispatch/checker.py`:

- `verify(control, *, window_s=20.0, lag_s=10.0, since_t=None)` gives the verdict;
- `record_baseline(control, window_s)` runs once at the end of warm-up;
- `p95_allowed(baseline)` gives the band.

It reads the users' log, every surge log, cad-db (read-only, 5000 ms busy timeout) and `checker_baseline.json`.
It never reads observe(), monitors, `changes.jsonl`, `actions.jsonl` or labels.

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

MEASURED: the lag allowance, only if the measurement step changes `LAG_ALLOW_S` from 3.0 (never below 1.5 s).

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
  while I was still open. Otherwise the reason is `missing`, `test`, `other_emergency` or `closed_before_link`.
- **details_ok(c)**: cad holds the call on I. When the call created I, I also carries the caller's number and
  nature, the nature's priority, and a location within 0.1 km of the caller's.

### 10.3 Journeys

A call in W succeeds when the caller was told, at most 3.0 s after answer; the incident belongs; the details
are right; and a real crew went en route at most 3.0 s after told (for a linked call, an earlier reach counts).

`journeys` holds `n`, `ok`, `success_rate`, `p95_ms` and `p90_ms` (answer time over answered calls, null when
none), `p95_allowed_ms`, `by_source {normal: {n, ok}, surge: {n, ok}}`, `linked`, and `failures`. Each failed
call counts once, in its first failing category:

| Key | Reason text |
|---|---|
| `rolled_over` | rolled over to the backup centre |
| `not_answered` | not answered |
| `not_told` | answered but not told help is on the way |
| `slow_entry` | told more than 3 s after answer |
| `no_incident` | told with no incident of theirs in CAD |
| `details_wrong` | entered with details other than the caller's |
| `not_reached` | with no crew en route within 3 s of being told |

**Zero failed calls on a healthy copy.** A window holds about 49 calls and the success rate must be at least
0.99, so one failed call makes a window red (48 of 49 is 0.98). A healthy copy fails none.

### 10.4 Integrity

Each blocking count is exact, reads 0 when healthy, and blocks `recovered`. Its reason sentence is the one the
verdict shows.

| Key | Definition | Reason sentence |
|---|---|---|
| `told_without_incident` | calls in W told help is on the way that do not belong. `told_without_incident_by` splits them `{missing, test, other_emergency, closed_before_link}` | "N callers were told help is on the way but CAD holds no incident of theirs" |
| `incidents_dropped` | distinct incidents I told to a call in W that belongs, told at least 3.0 s ago, where no real crew ever went en route to I and CAD is no longer working I (not `pending`, and no `assigned` or `alerted` assignment newer than 3.0 s). An incident deleted after the caller was told counts here | "N incidents callers were told about were dropped: no crew ever went en route and CAD is no longer working them" |
| `unit_records_wrong` | real units wrong by rule W or rule S (below). `unit_records_wrong_by` gives `{wrong_writes, units_behind}` | "N units' CAD records differed from their crews for longer than the 3 s status lag" |
| `duplicate_incidents` | for each emergency with a call in W, its real incidents (deleted ones included) created while another of them was still open | "N incidents duplicate an open incident of the same emergency" |
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

**Counted, not blocking:** `calls_dropped` (calls in W with outcome `dropped` or `cut_off`), `incidents_waiting`,
`unreadable_set_aside` (unreadable reports set aside) and `field_messages_waiting` (pending reports older than
3.0 s now).

**The verdict.**

```text
integrity.ok = every blocking count is 0
slo_ok       = n >= 20 and success_rate >= 0.99 and p95_ms <= p95_allowed_ms and p90_ms <= 750
recovered    = slo_ok and integrity.ok
```

`reasons` lists the service-level sentences first, then one sentence per blocking count that is not 0:

- "only N calls started in the 20 s window; at least 20 are needed";
- "K of N calls failed: <count> <reason text>, ...";
- "no call in the window was answered";
- "answer time p95 X ms is above Y ms";
- "answer time p90 X ms is above 750 ms".

### 10.5 `integrity.for_operations`

People's work. It never blocks on its own. In time order, at most 50.

- `{"kind": "set_aside", "item": <row id>, "unit": <the report's unit if readable, else null>}` for every field
  report set aside, at any time.
- `{"kind": "dropped_incident", "incident_id": I, "calls": [call ids]}` for every real incident told to a call
  that belongs and started before the window, that no real crew ever reached and CAD is no longer working, and
  whose emergency never had another incident reached. The window's own dropped incidents block through
  `incidents_dropped` instead.
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
values and channel.

### 11.1 Channels

| Channel | Dispatch detail |
|---|---|
| Processes | `control.kill(component) -> bool` crashes a process with no change recorded. `control.stop(component, actor="operator", log_change=True) -> bool` and `control.start(...)` work for call-handling, cad, dispatcher, alerting, alerting-backup, unit-sync and call-network. Nothing restarts by itself. A restart of call-handling loses every call between dial and report: a dial in progress is cut off (`cut_off`), a report gets 404 or a refused connection (`dropped`), and the caller redials. The checker counts these calls in `calls_dropped` and as failed journeys |
| Releases | `control.deploy(component, release, module_path=None, actor="pipeline") -> bool` copies the file to `<data>/releases/<component>/v<release>.py` and restarts the component. The module defines `class Release`, usually subclassing the current one (`from targets.dispatch.releases.cad.v3_4 import Release as Base`). Releases in the repository: call-handling 5.2 and 5.2.1; cad 3.4 and 3.4.1; dispatcher 2.1 and 2.1.1; unit-sync 4.0 and 4.0.1; alerting and alerting-backup 1.6 and 1.6.1; call-network 1.0. Each x.y.1 is a harmless build label. `rollback` returns to the previous release on call-handling, cad, dispatcher and unit-sync. alerting has no rollback: its fix is `failover`. alerting-backup's releases matter only after a failover. A release on call-network is an external outage |
| Release API | Frozen at the merge (below) |
| Settings | Section 3. `control.set_config(component, key, value, actor="operator") -> bool` is versioned and shown in `changes`. Which alerting side the dispatcher uses is routing state that only `failover` changes |
| Pending incidents | `incidents.status = 'pending'`, dispatched by priority then id, up to `batch_size` per cycle every `poll_interval_s`. Test incidents are taken in their own query, and an incident with no free unit does not use up the batch. With no free unit an incident waits; nothing closes it. An unacknowledged assignment becomes `no_ack` after `ack_timeout_s`, and its incident returns to `pending` (that unit is never sent to it again). An `enroute` or `onscene` incident whose last open assignment expires this way closes `completed`. These are live calls: they cannot be set aside, and the dispatcher skips an unreadable incident rather than crash |
| Field-report queue | Table `field_queue` (pending, applied, skipped, quarantined). unit-sync takes the oldest pending rows in id order, up to `batch_size`, and parses them all before writing. An unreadable report (11.2) crashes unit-sync by design, after the readable reports before it are committed and its own `attempts` raised. unit-sync stays down until restarted, and `head_item` names that report with `attempts` at least 1. A report is skipped when it is too old (`max_message_age_s`), superseded by a newer pending report of the same unit (judged from the reports themselves, not the `unit_id` column), or out of order. cad stores any JSON object of at most 4 KB at intake, without checking fields. Rows can be added through `control.db("cad-db")`, or by a helper posting to cad `/mdt` a bounded, one-off set of reports. Fix: `quarantine` with `params.item` = the row id = `head_item.id`, then `restart`. Each unreadable report needs its own quarantine |
| Ordering memory | unit-sync remembers, in memory only, the newest report time it has applied for each unit, and skips anything not newer. A restart forgets it. Report times are the terminal's clock. This is the system's one in-memory state that only a restart clears |
| Repeat calls (idempotency) | `calls.call_id` is the primary key, and entry is idempotent by `call_id` inside cad's write transaction. Under `repeat_match` "ani_open", cad links a call to this number's open incident (same number and test flag, status pending, dispatched, enroute or onscene) |
| Caller behaviour | Section 5.1: about 2.2 emergencies per second, ring until answer or rollover, ALI read-back with a spoken fallback, talk, report, the redial rules, 10% callbacks, at most 9.1 s per call |
| Crew behaviour | Section 5.2. Crews read both station inboxes, and a busy crew ignores alerts. A full-state heartbeat goes every 1.0 s. A failed post is not retried, and a report older than 2.0 s is dropped at the terminal. Unit records heal within about 1 s once the path works |
| Unit records | Only unit-sync writes `units`, apart from the seed and the probe's TEST-1 cleanup. Keep the `unit_history` and `incident_events` triggers: they are the checker's evidence. A one-time direct write to `units.status` or `units.incident_id` is overwritten by the next heartbeat within about 1 s, so it never lasts into a verdict |
| Locks | `control.spawn("incident-archive", ["{python}", "-m", "targets.dispatch.jobs.incident_archive", "--data", "{data}", "--hold-lock", "<S>"])` holds `BEGIN IMMEDIATE` on cad-db for S seconds. It registers `{"session": "incident-archive-<pid>", "pid", "since_t", "mode": "write", "statement": "INSERT INTO rms_export ... (export batch)"}` in `cad_locks.json`. observe() shows it under cad-db's `lock_holders`, and `release_lock` on cad-db ends it. Readers keep working (WAL). Every writer waits for its busy timeout and fails. A lock must be held at least about 130 s to still act in the scored window |
| Helper processes | incident-archive modes: `--export` (normal, about 1 s, batches of at most 50 rows, never registers as a lock holder), `--hold-lock S`, and `--cpu S` (a harmless busy run at low priority: a background change). `runs` counts only running jobs spawned under exactly the name `incident-archive`. Anything else spawned is invisible to the agent, and no action reaches it, except `release_lock` for registered lock holders |
| Datastore writes | `control.db(name=None) -> sqlite3.Connection`: `db("cad-db")` or `db()` gives autocommit, a 5000 ms busy timeout and `sqlite3.Row`. Any other name raises KeyError. Schema in section 4 |
| Links | `control.link(route, latency_ms=0, jitter_ms=0, drop_pct=0.0) -> bool`. `drop_pct` is a fraction of connections, 0.0-1.0. `"dispatcher->alerting"` is alerting as the dispatcher sees it; fix: `failover` on alerting, because the backup path bypasses the relay. `"call-handling->call-network"` is ALI as call-handling sees it; this is an external outage: escalate |
| Standby | alerting-backup runs the same image and writes its own inbox, and crews read both. It carries alerts only after `failover`. A change there alone shows nothing to users |
| External | call-network is the provider's. Stopping, killing or hanging it, deploying a release to it, or slowing or dropping its link is `external_outage`, and must be escalated. It has no actions, and the agent sees only call-handling's view of it. Calls then go spoken: answers are slower and callers are told later |
| Admin hooks | `control.admin(component, op, payload=None) -> dict`, with `op="hang"`, on any process. Its HTTP server stops answering (`not_answering`), and every background loop stops at its gate |
| Call surge | `control.surge(rate_per_s, seconds, seed=0, mix="normal") -> int` (11.3). It is the only source of extra calls |
| Other Control calls | `control.snapshot() -> dict`, `control.baseline(window_s=10.0) -> dict`, `control.paths() -> dict`, `control.shutdown()` |
| Capacity and drain | The tables of section 6. A scored window holds about 49 calls, so a mechanism that touches one call in N misses a window with probability about (1 − 1/N)^49 |
| Checker rules a fault must respect | Section 10 exactly. Unreadable is 11.2. A readable report set aside keeps the checker red for good, so label `quarantine` only for unreadable rows. A call counts as reached only when a crew's own log says en route. Records may lag by 3.0 s and never lead by more than 0.05 s. Test data is excluded everywhere. The timing rule (11.6) |
| Actors and words | Actors are drawn from `pipeline`, `operator`, `ops-maintenance` and `scheduler`, and passed on every deploy, setting change, stop and start. No release label, session name, statement, log line, change detail or payload contains a fault type or class name, or the words fault, inject, poison, stale or chaos. Use only made-up callers from the fictional number pools. Never log a caller's number, words or location |

**Link thresholds.**

MEASURED: for each link route (`dispatcher->alerting`, `call-handling->call-network`), the latency, jitter and
drop values that are reliably green, flaky, or reliably red with no action.

**Release API**, frozen at the merge; a rename needs a new row here:

| Release | Methods |
|---|---|
| call-handling 5.2 | `routes()`, `dial(request)`, `take_position(call)`, `lookup_location(ani)`, `report(request)`, `enter_incident(call, body)`, `release_position(call)`, `background()`, `extra_metrics(window_s)` |
| cad 3.4 | `routes()`, `validate_call(body)`, `find_call(conn, call_id)`, `find_open_incident(conn, ani, test)`, `create_incident(conn, call)`, `link_call(conn, incident_id, call)`, `create_call(request)`, `mdt(request)`, `extra_metrics(window_s)` |
| dispatcher 2.1 | `cycle(conn, settings)`, `retry_alerts(conn, settings)`, `expire_unacknowledged(conn, settings)`, `pending_batch(conn, settings)`, `free_units(conn, incident)`, `recommend(incident, units, settings)`, `assign(conn, incident, unit)`, `send_alert(conn, assignment, settings)` |
| unit-sync 4.0 | `cycle(conn, settings)`, `take_batch(conn, settings)`, `parse(item)`, `in_order(msg)`, `apply(conn, item, msg, settings, latest)`, `apply_unit(conn, msg)`, `apply_assignment(conn, msg)` |
| alerting 1.6 | `routes()`, `alert(request)`, `deliver(alert)` |
| call-network 1.0 | `routes()`, `ali(request)`, `locate(ani)` |
| `worker.Worker` (dispatcher and unit-sync) | `background()`, `run_loop()`, `wait(seconds)`, `db()`, `write_error()`, `extra_metrics(window_s)` |

**Behaviour the methods carry.**

- The dispatcher's `send_alert` posts to the active side with `alert_timeout_s`. A failed alert is retried every
  0.3 s.
- No release holds a cad-db transaction across a network call.
- unit-sync's `apply_unit` sets `status`, `incident_id`, `status_t` (the report's `t`) and `applied_t`.
  `apply_assignment` keeps assignments in step with the state a report carries: `enroute` or `onscene` for X acks
  (or inserts, source `field`) the unit's assignment to X and clears its other acked or on-scene ones;
  `available` clears acked and on-scene assignments and leaves `assigned` and `alerted` ones to the timer. An
  incident left with no open assignment closes `completed`. A report for an incident that does not exist changes
  only the unit record, with a WARN line.

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
readable report never crashes unit-sync.

### 11.3 The call surge

```python
pid = control.surge(rate_per_s, seconds, seed=0, mix="normal")
# or directly:
control.spawn("call-surge", ["{python}", "-m", "targets.dispatch.surge", "--data", "{data}",
                             "--rate", "2.0", "--seconds", "150", "--seed", "7", "--mix", "normal"])
```

- `rate_per_s` is **emergencies per second**; each makes about 1.1 calls. All surges together are capped at
  **3.0 emergencies per second**, and a healthy copy stays green at the cap.
- `seconds` is 1-900. One surge places at most 1,000 emergencies (`rate_per_s × seconds` ≤ 1000).
- `mix` is `normal` (everyday weights), `medical` (cardiac, breathing, fall, collision) or `fire`
  (structure_fire, vehicle_fire, alarm).
- `control.surge` returns the helper's pid once it is registered in `surge.json`. It waits up to 5 s.
- **Refused, never clamped.** A surge over the cap, with no free number block or with a bad argument, exits
  with code 2, prints one line `call-surge <pid>: refused: <reason>` to `logs/call-surge.out`, and places no
  call. `control.surge` then raises `RuntimeError("call surge refused: <reason>")`. If the helper neither
  registers nor exits within 5 s, it raises `RuntimeError("call surge <pid> neither registered nor refused
  within 5 s")`. Reasons include "the surges together would start 3.50 emergencies per second, above the cap of
  3", "all 5 number blocks are held by running surges", "rate x seconds is ... emergencies, more than the 1000
  numbers ...", "seconds must be a number from 1 to 900" and "mix must be normal, medical or fire".
- Emergencies start at random (exponential) gaps, each in its own thread, at most 64 at once. They follow the
  callers' redial, callback and timeout rules. The helper runs its full `seconds` whatever call-handling does,
  then up to 10 s more for calls in flight, and then exits.
- It writes `logs/call-surge-<pid>.jsonl`, and prints only a started line, counts every 10 s, and a finished
  line.
- It is not a component. The agent sees a surge only as more calls (rps, the call queue keys, the pending
  board).
- A fault that acts only during a surge needs the surge to cover the scored window: start it with at least
  130 s.

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
| `resource_exhaustion` | a release that exhausts a process |
| `external_outage` | call-network and its link |

### 11.6 Timing rule

The harness takes its verdict about 125 s after the last change it makes, on calls that started 95-115 s after
it (`window_s` 20, `lag_s` 10), with `since_t` the first change. **A fault must still act 95-115 s after it.**
One that ends by itself before then (a short lock, a short surge, a one-time record write) is green with no
action, and the case is excluded.

### 11.7 The far-future report

A report dated far ahead freezes its unit's CAD record until unit-sync restarts: the ordering memory skips every
later report as out of order. It freezes the unit **only if no newer report of that unit is pending at
unit-sync's next cycle**; otherwise it is skipped as superseded. Confirm the freeze took effect: the unit's
`units.status_t` equals the `t` you inserted. If it does not, insert it again.

## 12. Break and heal by hand

The validity matrix. Each row is red with no action at verdict time, and green within the soak after its
labelled fix. `control` is the copy's Control and `adapter` its adapter. A fix goes through the adapter, as
the agent's would. The reason column gives the sentences the verdict should show; N, K, X and Y are counts and
times.

| Break (Control) | Reasons with no action | Labelled fix (adapter) |
|---|---|---|
| `control.kill("call-handling")`, or `stop`, or `admin("call-handling", "hang")` | "K of N calls failed: K not answered"; "no call in the window was answered" | `act("restart", "call-handling")` |
| `control.kill("cad")`, or `stop`, or `admin("cad", "hang")` | "K of N calls failed: K answered but not told help is on the way"; also "N units' CAD records differed from their crews for longer than the 3 s status lag" (reports to `/mdt` are lost) | `act("restart", "cad")` |
| `control.kill("dispatcher")`, or `stop`, or `admin("dispatcher", "hang")` | "K of N calls failed: K with no crew en route within 3 s of being told" | `act("restart", "dispatcher")` |
| `control.stop("unit-sync")`, or `kill`, or `admin("unit-sync", "hang")` | "N units' CAD records differed from their crews ..."; "N incidents had more than one crew en route" (acknowledgements never arrive, so the timer re-sends); "... with no crew en route within 3 s of being told" | `act("restart", "unit-sync")` |
| `control.admin("alerting", "hang")`, or `kill` or `stop` | "... with no crew en route within 3 s of being told"; may add "N incidents callers were told about were dropped: ..." | `act("restart", "alerting")`; `act("failover", "alerting", {"to": "standby"})` also works |
| `control.set_config("call-handling", "positions", 1)` | "K of N calls failed: K rolled over to the backup centre"; "answer time p95 X ms is above Y ms"; "answer time p90 X ms is above 750 ms" | `act("revert_config", "call-handling", {"key": "positions"})` |
| `control.set_config("dispatcher", "ack_timeout_s", 0.05)` | "N incidents had more than one crew en route"; also "N units were committed to two incidents at once" | `act("revert_config", "dispatcher", {"key": "ack_timeout_s"})` |
| `control.set_config("cad", "repeat_match", "off")` | "N incidents duplicate an open incident of the same emergency" | `act("revert_config", "cad", {"key": "repeat_match"})` |
| an unusable setting, e.g. `control.set_config("dispatcher", "batch_size", 0)` | a worker stops: "... with no crew en route within 3 s of being told" (dispatcher) or "N units' CAD records differed ..." (unit-sync). call-handling answers 503: "... not answered". cad answers 503: "... answered but not told help is on the way" | `act("revert_config", <component>, {"key": <key>})` |
| `control.link("dispatcher->alerting", latency_ms=1500)` (above `alert_timeout_s` 1.0), or `drop_pct=1.0` | "K of N calls failed: K with no crew en route within 3 s of being told" | `act("failover", "alerting", {"to": "standby"})` |
| `control.spawn("incident-archive", ["{python}", "-m", "targets.dispatch.jobs.incident_archive", "--data", "{data}", "--hold-lock", "600"])` (at least 130 s) | "K of N calls failed: K answered but not told help is on the way"; often "answer time p95 ..." and "N units' CAD records differed ..." | `act("release_lock", "cad-db")` |
| an unreadable report, inserted through `control.db()` (below) | unit-sync crashes: "N units' CAD records differed from their crews ..."; then "... more than one crew en route" and "... no crew en route within 3 s ..." as the board ages | `act("quarantine", "unit-sync", {"item": <head_item.id>})`, then `act("restart", "unit-sync")`; `for_operations` then lists `{"kind": "set_aside", "item": <id>, ...}` |
| a far-future report for one unit (below) | that unit's record is frozen: "N units' CAD records differed from their crews ..." (N ≥ 1) once its crew moves | `act("restart", "unit-sync")` |
| a bad release: `control.deploy(component, "<version>", module_path=<file>)` | depends on the mechanism; each shape is counted exactly | `act("rollback", component)` |
| call-network: `control.stop("call-network")`, or `control.link("call-handling->call-network", drop_pct=1.0)` or a latency | calls go spoken: "K of N calls failed: K told more than 3 s after answer"; with a slow link also "answer time p95 X ms is above Y ms" | escalate (no action); red with no action by design |
| a surge at or below the cap; `control.stop("alerting-backup")` alone; `--cpu`; a build label (`control.deploy("call-handling", "5.2.1")`); a harmless setting move | green | none: healthy or a background change |

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
  `SELECT status_t FROM units WHERE id = 'M3'` equals that `t` (11.7).

**At the real timing.** The live tests run three families this way: kill dispatcher; hold-lock 600; an
unreadable report. With no action the verdict 125 s after the break (with `since_t` the break) is red. With the
labelled fix applied 5 s after the break it is green.

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
- `tests/dispatch/test_live.py` brings copies up and down, and breaks and heals them, under `IC_SLOW=1` (one
  copy on port base 9700, about three minutes) and `IC_DISPATCH_LONG=1` (three copies, the whole table).
