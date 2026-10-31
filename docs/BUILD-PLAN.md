# Build plan: ABCDE Incident Commander

Challenge 1 (an AI agent that recovers a failing system). Plan written 29 Oct 2026 and updated the same night after five reviews. All times are Riyadh time (UTC+3).

- Event days: Fri 30 and Sat 31 Oct; the exact hours and the deadline are in Omar's private notes. Our own target is to publish by Sat 19:00.
- Interfaces between the parts: [CONTRACT.md](CONTRACT.md) (version 1.1). Codex's brief: [CODEX-HANDOFF.md](CODEX-HANDOFF.md).

## 1. What we are building

An AI incident commander that keeps a failing multi-service system running. It uses the method emergency medicine uses for several injuries at once:

1. **Survey.** Check every component, in a fixed ABCDE order, before fixing anything: Access, Bottlenecks, Capacity, Dependencies, Events. One containment step is allowed before the survey ends: a single failover.
2. **Triage.** Order the faults by weighted shortest-job-first: customer impact divided by time to fix, upstream first.
3. **Remediate.** Use only six bounded, safe actions from an allowlist, through a safety wrapper that refuses anything else.
4. **Verify.** Say "recovered" only when the system's own measures agree for a sustained window.
5. **Hand over.** End with an SBAR handover, or escalate to a person when no safe action fixes the fault.

An independent checker then decides whether the system really recovered, using evidence the agent never sees. We run a sealed exam of 60 incidents against a scripted runbook with no AI, and against weaker versions of the agent.

**Built to plug into other systems.** The agent is system-agnostic. It needs only a 5-function adapter (describe, observe, logs, probe, act). A test system also supplies a control layer (how faults are injected) and a checker (what "recovered" means there). The main test system is a small bank: an app gateway, a payments service, fraud screening with a standby, a clearing worker and a simulated national payment network, around a double-entry ledger, with test customers paying nonstop. The transfer test runs the frozen agent on a second system, an emergency dispatch system that Claude builds after the freeze, so the frozen hashes show the agent never saw it. If Friday's brief supplies an organiser system, it replaces dispatch as the transfer test (section 12).

```
 test customers ──► gateway ──► payments ──► screening (+ standby)
   (own log)                      │
                                  ├──► ledger (SQLite, double-entry)
                                  └──► clearing queue ──► clearing worker ──► payment network (external)

 agent ──► guard ──► adapter: describe · observe · logs · probe · act   (never sees the control layer or the customers' log)
 injector ──► control: kill · deploy · set_config · link · db           (privileged)
 checker ──► customers' log + full ledger audit                         (independent)
```

## 2. Who does what

| Who | Owns | Does not do |
|---|---|---|
| **Omar** | Every decision; the lead story; merging pull requests; the freeze go-ahead; starting the final run in his own PowerShell window; making the repository public; the video, the deck, the project page and the free-text answer, in his own voice | Write code |
| **Claude (cloud)** | The plan, the test design, the contract; the test kit, the bank, its 7 practice faults and its checker; the agent, its three ablation arms, the safety wrapper and the model client; the demo; 32 practice scenarios; the dispatch system (except its faults), after `freeze-1`; reviews of Codex's pull requests; drafts of the deck (from the banking deck draft, kept outside the repository), the page and the video script | See the sealed exam or the dispatch faults before the run |
| **Codex Session A** (laptop, `%USERPROFILE%\Documents\HUMAIN-Incident-Commander`) | C0 setup check; C1 the sealed exam (3 named held-out fault types, 1 blind type, 60 incidents); C4 Windows bring-up; C5 sealed-fault dry run and seal 2; C6 the freeze tag and clean-clone pass 1; C7 the dispatch faults, 20 sealed incidents and the transfer run; the secret scan and clean-clone pass 2 | Run any agent arm before seal 2 is on GitHub; edit Claude's files |
| **Codex Session B** (laptop, `%USERPROFILE%\Documents\HUMAIN-IC-baseline`) | C2 the scripted runbook; C2b its check on the merged bank; C3 the evaluation harness, statistics and charts; the model-key check, the pilot, the dry run, `baselines/FROZEN.json` and the results report | See the sealed files; edit Claude's files |

Why the split is drawn this way: **the agent's author never writes the exam.** Claude builds the agent, so Codex writes the held-out faults, the sealed scenarios and the baseline. That answers the obvious judge question ("didn't you just test it on faults you designed it for?"). Claude keeps the 7 practice faults because they were needed to build and test the agent, and they are only used for practice. Session A holds the sealed files; Session B never sees them, so it can run the agent before seal 2.

## 3. Rules and claims we hold to

- Terminology: "system" or "target system", never the medical word for the person being treated. The steps are inject, survey, triage, remediate, verify, hand over. ABCDE, triage and SBAR keep their names.
- Trims adopted from the deck review: no ECC-style incident record; the handover is short and in English only; the ordering is called weighted shortest-job-first (never START); Smith's rule is not used as evidence; the FIFO comparison is run only if time allows; the deck is cut to 10 slides.
- Claims: never name a Saudi bank; never claim SAMA or NCA compliance (say "relevant to"); the SAMA 79% figure is exposure, not outages; cite ITBench from ICML 2025, not the preprint, and carefully: 102 scenarios across three domains, 42 of them SRE; the paper gives 11.4% and 13.8% for the SRE scenarios its agents resolve, so say "fewer than one in seven"; never describe the build as production-ready.
- Results: fill the results slide and page only from real runs, with n/N and intervals. The pilot's numbers stay internal. Add a "measured vs proposed" slide.
- Sealing: the time GitHub received the push (shown on the pull request) proves the exam was fixed before tuning; commit times are set by the committer.
- Prior work: Omar's private notes hold the basis for building before the event. If the final rules say otherwise, Omar asks the organisers and keeps the answer; Claude and Codex never contact them. We started building on 29 Oct, so `DECISIONS.md` and the README say so plainly. The commit history shows it anyway.
- The NDA (the repository will be public): no platform name, domain or links, no organiser email address, no participant or mentor names and no platform content in the repository. Before it goes public, Codex scans the full history for secrets, and Omar searches it for the platform's name and domain (listed in Omar's private notes).
- Authorship: Omar writes the video, the free-text answer and the page in his own voice. Claude and Codex draft and build; every commit says who made it.

## 4. Tonight, Thursday 29 Oct, and the night to Friday

**Before pasting the handoff (Omar, Thu night, once Claude's handoff fixes are merged):** the six steps at the top of `docs/CODEX-HANDOFF.md`: the power settings; Windows Update paused for a week; `ANTHROPIC_API_KEY` set in "Edit environment variables for your account", not typed into PowerShell; the two clones and `HUMAIN-sealed` made in Documents; each session opened in its own folder, allowed to work without asking, with network access, and Session A also able to write `HUMAIN-sealed`; pushes to `codex/*` pre-approved. Each Codex session sets its own git identity in its clone (Omar's GitHub no-reply address), so Omar sets none.

| Time | Omar | Claude (cloud) | Codex Session A | Codex Session B |
|---|---|---|---|---|
| until 00:30 | Review and merge pull request #1 (bank, kit, contract, CI, these documents) once green; the steps above; paste the handoff into both sessions | Pull request #1 | - | - |
| 00:30-01:20 | Answer setup questions, then sleep | Agent pull request | C0: setup check, install `requirements.txt` | C2: venv and `requirements.txt`, then the runbook |
| 01:20-03:00 | Sleep | Agent pull request: all four arms, the demo, fast tests, by 03:00 | C1: design the exam and check each sealed type live; seal 1 pushed by 03:00 (05:00 at the latest) | C2: the runbook against the contract, on a fake adapter |
| 03:00-09:00 | Sleep | Tuning on practice scenarios, starting only once seal 1's push is on GitHub (until then, tests only), with the real model if a key is in the cloud environment; the 30 practice scenarios; tests | C1: plugin tests until seal 2 is due; `NIGHT-REPORT.md` | C3: evaluation harness and charts, on fakes; `NIGHT-REPORT.md` |

Each Codex session pushes each finished task to its `codex/*` branch, opens a draft pull request and carries on without waiting for replies. Sealed content is never pushed, only `SEALED.json`.

**Milestones.** M0: plan, contract and handoff on `main`. **M1a (tonight, pull request #1):** the bank half, green on windows-latest and ubuntu-latest: the bank starts with one command, all 6 practice faults break it, manual fixes heal it, and the checker tells the two apart. **M1b (by 03:00 Fri):** the agent pull request: all four arms, the demo and fast tests, and the agent completes a 2-fault practice incident end to end. C4, C2b and C5 depend on M1a only.

## 5. Friday 30 Oct

Moved earlier on Friday morning (`DECISIONS.md`, 30 Oct): GO/NO-GO 1 passed on the morning rehearsal, and the freeze is at about 18:00 so the full exam fits overnight. Moved again at 16:29: Omar added a bank practice fault for silent drops before the freeze (`unrecorded_payments`, dev-31 and dev-32), which changes the system hash, so Session A runs C5's sealed self-test again on the new `main` and the freeze is at about 19:00. Times after 10:30 are targets; each step still waits for the one before it. "Green" means the tests workflow passes on ubuntu-latest and windows-latest.

| Time | Omar | Claude | Codex Session A | Codex Session B |
|---|---|---|---|---|
| **08:00-10:30 (done)** | Merged the overnight pull requests; pasted the early prompts; added the model key to the cloud environment | Checked the harness end to end on the real bank; a tuning thread tuned the agent on dev-01 to dev-20 with the real model (pull request #12, merged 10:17) | C4 rehearsal: GO/NO-GO 1 steps 1-4 passed; C5a: the `extra_service` variants and the strata check; C5: the sealed faults dry-run without the agent, seal 2 pushed at 09:58 (pull request #11) | `python run.py demo` once (model-key check); C3a (pull request #9); the harness end to end on 3 practice scenarios, 1 copy then 3 copies; C2b (pull request #10) |
| **10:31 GO/NO-GO 1** | Counted the rehearsal as GO/NO-GO 1 (section 7) | | | |
| 10:30-11:00 | Merge #11, then #9 and #10 after Claude's review | Review #9 and #10 | - | - |
| 11:00-13:00 | If the briefs are out, decide on an organiser system (otherwise at 14:00) | Tune the agent on dev-01 to dev-20 only, with the real model (tuning thread) | - | Tune the runbook on dev-01 to dev-20 only |
| 13:00-13:45 | Read the pilot results | Pick the bulk model from the pilot's measured cost and seconds per call | - | Pilot: dev-21 to dev-30 × abcde, react, runbook, on 3 copies |
| **13:45 GO/NO-GO 2** | Decide the framing (section 7) | | | |
| **14:00-14:30** | Read the final brief. Confirm Challenge 1. Choose the lead story: banking (default) or dispatch. The bank carries the sealed exam either way; choosing dispatch makes it the video demo. Create the project page (name, one-sentence description) | Adjust the plan to the brief | Pull `main` | Pull `main` |
| 14:30-15:00 | - | The bulk model in `configs/models.json`; tests green on Windows | - | Check `configs/prices.json`; test resume |
| 15:00-16:00 | 20-minute explain-back: Claude walks Omar through every file | `DECISIONS.md` (ablation diffs, analysis plan) | - | Dry run `dry-1` on 6 practice scenarios on 3 copies, plus 1 scenario under `log_format_v2` and `extra_service` (runbook) and 1 under `model_swap` (abcde); checker calibration with noop, 4 runs each of the 3 healthy practice cases (dev-09, dev-18, dev-24) |
| **16:00 GO/NO-GO 3** | Set the run size (section 7) | | | |
| 16:00-18:00 | Start the video script outline with Claude; merge the bank fault pull request once green | The last agent pull request green by 17:00; the silent-drop practice fault and its pull request; regression tests | C5's sealed self-test again, on `main` once the bank fault pull request has merged; report pass or fail per fault only | - |
| **18:30-19:00 FREEZE** | Merge every open pull request (including `baselines/FROZEN.json`); approve the tag | Record the tag, the commit and the five group hashes in `DECISIONS.md` | C6: tag `freeze-1`, push the tag, clean-clone pass 1 into `%USERPROFILE%\Documents\HUMAIN-final` with the sealed files copied in | `baselines/FROZEN.json` (no backup demo take: the recorded replay on `main` already matches the agent, `DECISIONS.md`) |
| about 19:00 | Start the final run in his own PowerShell window in `HUMAIN-final`, with the 5-try auto-resume loop from the handoff; leave the laptop on mains power. Then the second explain-back while it runs | Build the dispatch platform, adapter, control and checker with `ic/kit`, following `docs/ADDING-A-SYSTEM.md`, with integrity counts for the three transfer shapes (CONTRACT section 8), `docs/DISPATCH.md` (its facts and fault channels, like CONTRACT section 7.3) and a burst helper started through `Control.spawn`, the only source of extra calls in a surge (19:00 to about 01:00) | - | - |

The final run goes case-major in the line order of `heldout.jsonl` (its first 40 ids are `core40`) (case 1 under every arm, then case 2), so a partial run is still paired: the main exam first, then the robustness subset. It must finish by 06:00 Sat. Progress: `Get-Content results\final.log -Tail 20`.

## 6. Saturday 31 Oct

Changed on Sat 31 Oct at 07:30: the final run did not start on Friday night. It started at 07:28 with the core40 cut in full and ends about 12:45 (`DECISIONS.md`, 31 Oct). C7 keeps 09:00-12:00 and overlaps it; the 11:00 stop no longer applies. The 12:00 row now starts when the final run ends: Session B's results tables from about 12:45, a 10-minute dispatch soak on the laptop at about 12:45-13:00, then the transfer run at about 13:15-14:25, stopped 2 h 15 min after it starts (about 15:30) whatever its state.

| Time | Omar | Claude | Codex Session A | Codex Session B |
|---|---|---|---|---|
| 09:00-12:00 | Check the final run finished; merge the dispatch pull request once green | Record the dispatch tree id in `DECISIONS.md` at the merge (CONTRACT section 15); fix anything in dispatch (each fix gives a new id, and Session A re-checks its incidents on it) | C7: write the dispatch faults and 20 sealed incidents from the dispatch adapter and control interfaces, with at least one of each of the three shapes in CONTRACT section 8; push only `scenarios/transfer/SEALED.json`. At 11:00, if the main exam is incomplete, stop the robustness subset and report the completed paired cases as n of N | - |
| **12:00-13:00** | Read the results; then the 12-case clinician check with `scripts/clinician_draw.py`, about 40 minutes (declared exploratory, `DECISIONS.md`) | Results write-up: tables with intervals, paired tests, where the script ties or wins | The transfer run: the frozen agent's `abcde` arm and the frozen `runbook`, with `noop` and `oracle` for validity, 3 copies on port bases 9100, 9200 and 9300; stop at 14:15 whatever its state | Results table and charts in `HUMAIN-final`: `python run.py eval --report final-1`; then the off-list table with its `react` sensitivity row (declared exploratory, `DECISIONS.md`) |
| 13:00-14:30 | Choose the demo seed with Claude | Fill the deck's results slide from real runs only | The `codex/reveal` pull request with the sealed files and the per-case evidence | Charts for the deck |
| **14:30-16:00** | Record the 3 to 4 minute video (demo plus results), then upload it to a public link | The video script and the 75-second demo scenario | Keep the demo machine clean | - |
| 16:00-17:30 | Make the repository public after Codex's secret scan; write the free-text answer in his own words; check the deck | Deck cut to 10 slides plus PDF; page text (sections as in Omar's private notes); README final | Secret scan of the full history; then clean-clone pass 2: an anonymous clone, the README steps, `python run.py demo` live and again with the key unset (it must print the REPLAY line) | - |
| 17:30-18:30 | Fill the project page | Fix anything from pass 2 | Repeat the clean-clone check at 18:00 | - |
| **18:30-19:00 PUBLISH** | Publish. Open every link in a private window | - | - | - |
| 19:00-19:45 | Buffer. Republish if anything changed. Stop editing at 19:45 | - | - | - |

## 7. Go/no-go checks

**GO/NO-GO 1 (passed: Session A's morning rehearsal passed all four steps, and Omar counted it at 10:31 Fri).** On Omar's Windows laptop, on the eval port bases:

1. `python run.py up` starts the bank with one command, and `python run.py status` shows every component healthy.
2. All 6 practice faults, one at a time, each break payments in a way that `status` shows at once and `check` shows from 30 s after the injection.
3. Each heals within 30 s of the matching action, and `check`, run 30 s after it heals, returns `recovered: true` with the ledger exact.
4. Three copies (8100, 8200, 8300) each complete 10 up/down cycles without a port-in-use error. While two copies start and stop, a healthy third copy's checker stays green in at least 19 of 20 consecutive 20 s windows.

If step 1, 2 or 3 fails and isn't fixed by 16:30, take the cut path. It keeps every Adapter and Control signature and every component name: `link()` becomes an in-service delay, and failover to `screening-standby` uses a cached decision list. If only step 4 fails, run on the copies that passed, and GO/NO-GO 3 sets the exam size.

**GO/NO-GO 2, Fri about 13:45 (the pilot).** Count the checker-recovered cases out of 10: A for `abcde` and R for `runbook`. Apply the first rule that matches.

1. A is 6 or fewer: the agent is unreliable. Cut the `react` and `naive_verify` arms, work only on `abcde`'s reliability until 17:00, then freeze as planned.
2. A is at least R + 2: keep the pitch as planned.
3. Otherwise: keep the build and reframe it honestly. The script handles known faults; the agent is for held-out, compound and changed-condition faults, and it writes the handover. The sealed exam then tests exactly that claim.

**GO/NO-GO 3, Fri about 16:00 (run size).** From the dry run, m = mean minutes per incident and c = the number of copies that ran without interference. Hours = (60 × arms + 220) × m / (60 × c). The run must end by 05:30 Sat, half an hour before the 06:00 deadline, counted from its planned start (about 19:00 since the 16:29 change, so about 10.5 hours). If it fits, run 60. Otherwise cut to the pre-registered core40 and keep only `four_faults` and `model_swap`, so hours = (40 × arms + 100) × m / (60 × c). If that still does not fit, also cut `naive_verify`. If the start slips, recompute from the actual start: the run must finish by 06:00.

## 8. Cut lines

Each cut belongs to a decision point. Never cut the bottom block.

| Decision point | Cuts, in this order |
|---|---|
| GO/NO-GO 1 (passed) | The TCP link proxy (use in-service delays; the cut path in section 7) |
| GO/NO-GO 2 (about 13:45) | The FIFO arm; the rich console timeline (plain text instead); the naive-verify arm; the free-form ReAct arm |
| GO/NO-GO 3 (about 16:00) | The extra robustness conditions (keep `four_faults` and `model_swap`); then the exam from 60 to the core40 list; then the naive-verify arm |
| Sat 12:00 | The transfer run from 20 incidents to its first 10 |

**Never cut:** the one-command run; the sealed exam; the independent checker with the ledger check; the scripted runbook baseline; the SBAR handover and escalation; the first 10 transfer incidents (the agent must be shown to plug into another system); the video.

## 9. Test design

**Practice set (Claude, 32 scenarios, dev-01 to dev-32):** the 7 practice fault types, single and compound, plus healthy distractors (`noise`) and must-escalate cases (`network_outage`). Used for building and tuning only: dev-01 to dev-20 for tuning the agent and the runbook, dev-21 to dev-30 for the pilot. dev-31 and dev-32 (payments answered as posted but never written, alone and beside a stopped worker) were added after the pilot, so no tuning or pilot run used them.

**Sealed exam (Codex Session A, 60 scenarios):**

- 20 single-fault cases: about 6 healthy distractors (no fault, but a noisy metric or a harmless release), about 6 must-escalate cases (nothing allowlisted can fix them) and about 8 genuine single faults.
- 25 double-fault cases and 15 triple-fault cases, built from confusable pairs that share symptoms.
- Three named held-out fault types (`poison_payment`, `stale_balances`, `double_posting`) appear in at least a third of the cases. One blind type appears in 6 to 10 cases, marked `"blind": true`; `SEALED.json` counts it only as "blind", and its plugin has a neutral file name.
- `scenarios/heldout/robustness.jsonl` holds the four-fault cases (practice faults added until there are four) and the `extra_service` variants, sealed with the rest.
- `SEALED.json` pre-registers `core40` (the first 40 ids in run order: 13 singles, including 4 healthy and 4 must-escalate; 17 doubles; 10 triples) and `robust20` (20 ids drawn from `core40` with `random.Random(2026).sample`, at least 2 healthy and 2 must-escalate).

**Arms on identical seeds:** `abcde`, `runbook` (no AI), `react`, `naive_verify` and, if time allows, `fifo`. The harness adds `noop` and `oracle` as validity checks: a fixable case the oracle cannot fix is excluded by the rule in CONTRACT section 11.

**Robustness (robust20):** the held-out and blind faults (built into the exam); `four_faults`; `log_format_v2`; `extra_service`; `model_swap` (the frozen agent on a model it was not tuned on); then the transfer to a second system (dispatch, or the organiser's system). The runbook runs every condition except `model_swap`.

**Ground truth:** diagnosis truth is the injector's manifest. Recovery truth is the checker. No model labels anything.

**Statistics:** n/N with 95% Wilson intervals, and the analysis plan in CONTRACT section 16 (exact McNemar tests for paired yes/no outcomes, Holm's correction, paired bootstrap and Wilcoxon tests), committed before `freeze-1` and unchanged after.

**Run time:** the verdict time is fixed from the alert, so every arm takes about 2.5 minutes per incident: start and stop about 8 s, warm-up 10 s, fault offsets up to 8 s, alert delay 5 s, agent budget 90 s, soak 20 s, verdict lag 10 s. The main exam of 60 incidents × 4 arms takes about 10 hours on one copy or 3.3 hours on three. The robustness subset uses `abcde` and `runbook` (no runbook under `model_swap`), plus `noop` and `oracle` on the 40 new cases (`four_faults` and `extra_service`): 20 cases × 4 conditions, so 220 runs, about 3 hours on three copies. That is why it runs overnight, and why GO/NO-GO 3 sets the size.

**Model cost:** measured at the pilot. Session B checks the prices in `configs/prices.json` on the day, before the final run.

## 10. Models and keys

- The provider is Anthropic. OpenAI's API is blocked from Claude's cloud container; the model client still supports OpenAI, LM Studio, replay and a mock.
- The default model is `anthropic:claude-opus-5-5`; `IC_MODEL` overrides it. The bulk model for the final run is picked at the Friday pilot from the measured cost and seconds per call (candidates: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`) and written to `configs/models.json` as `bulk`. The `swap` model for `model_swap` is `anthropic:claude-haiku-5-5`, or `anthropic:claude-sonnet-5-5` if the bulk model is Haiku.
- Omar adds a spend-capped key as a secret in Claude's cloud environment, so Claude can tune with the real model overnight and on Friday. Without it, the agent pull request is tested with the rule-based test model only, and the first real call is Session B's `python run.py demo` at 10:00 Fri on the laptop.
- Keys live only in environment variables (`ANTHROPIC_API_KEY`, set in the laptop's environment variables for Omar's account), never in files.
- `ic/llm.py` sends no temperature, top_p, top_k or prefill, reads the answer's content blocks by type and sets the effort per call. Every call is logged with its status and error (CONTRACT section 9).
- LM Studio is an extra condition only if Friday's smoke test passes. It runs last, alone, on 1 copy, and LM Studio is quit before the final run.
- With no key, `python run.py demo` replays `replays/demo-frozen.jsonl` (recorded by Claude on 30 Oct on the agent that freezes, pull request #21) and says so. The scripted runbook needs no key at all.

## 11. Where the evidence comes from

| Area | Evidence | Ready by |
|---|---|---|
| Held-out results | The sealed exam: recovery rate, root-cause F1, false all-clears, correct escalations, with intervals | Sat 12:00 |
| Robustness | Held-out and blind faults, four faults at once, changed log format, extra service, a model the agent was not tuned on, a second system built after the freeze | Sat 14:15 |
| Evaluation | `results/runs.csv` from the first run on; the pilot; the ablations; regression tests; a frozen baseline; the pre-registered analysis plan; the decision log | Throughout |
| Design choices | The survey against free-form ReAct; weighted shortest-job-first; the bounded allowlist and the safety wrapper; the independent checker; a trade-offs slide | Sat 16:00 |
| Engineering | One command; Windows checked; the two clean-clone passes; tests; readable code; the contract | Sat 18:30 |
| Presentation | A 10-slide deck, the video, the README, the SBAR handover | Sat 19:00 |

## 12. Risks

| Risk | What we do |
|---|---|
| Windows quirks (killing processes, SQLite locks, ports in use) | Standard-library processes plus `psutil`; the 09:30 rehearsal and GO/NO-GO 1; the cut path in section 7 |
| The laptop sleeps or restarts overnight | The power settings and the paused Windows Update before pasting; the auto-resume loop |
| No working model key on Friday | Omar sets one tonight on the laptop and in Claude's cloud environment; the runbook and the replay work without one |
| The script ties the agent | Known by about 13:45 Friday; the GO/NO-GO 2 rules |
| The overnight run crashes | A 300 s per-case watchdog (`harness_timeout`); provider errors scored `api_error`; both re-run once at the end and reported separately; the 5-try auto-resume loop on 3 copies; case-major order, so a partial run is still paired; at Sat 11:00, if the main exam is incomplete, stop the robustness subset and report n of N |
| A sealed file is committed by mistake | `.gitignore`, staging by explicit path, `git status --short` before every commit, `.git/info/exclude` on the laptop |
| An organiser system is supplied | Decide by Fri 10:00 if the briefs are out (else at 14:00). The bank keeps the sealed exam; the organiser system replaces dispatch as the transfer test. Claude writes its adapter, control and checker; Codex writes its faults and 20 sealed incidents. Before `freeze-1`, Claude runs only the conformance check and the Control tests on it, never the agent. Organiser material never enters the repository unless the brief says it may be redistributed; the adapter reads it from the folder in `IC_ORGANISER_DIR` |
| The brief rules out pre-built work | Omar asks the organisers and keeps the answer (Claude and Codex never contact them); disclose the 29 Oct start |
| Omar can't explain a part in the interview | Two explain-back sessions on Friday; every module starts with a plain-English docstring |

## 13. Open decisions for Omar

1. The lead story, at Fri 14:00: banking (default) or dispatch. An organiser system, by Fri 10:00 if the briefs are out, else at 14:00.
2. Exam size: set by GO/NO-GO 3 at about 16:00.
3. The bulk model: decided, `anthropic:claude-opus-5-5` (`DECISIONS.md`, 30 Oct).
4. When the repository becomes public: after Codex's secret scan on Saturday afternoon, before publishing. Judges need it public by Saturday's publish.
