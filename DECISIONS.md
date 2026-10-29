# Decisions and trade-offs

Dated log of design decisions. Times are Riyadh (UTC+3). Codex records its hashes in `baselines/FROZEN.json` and `scenarios/heldout/SEALED.json`; Claude copies them here.

| Date | Decision | Why / consequence |
|---|---|---|
| 2026-10-29 | Challenge 1, idea C1-H1: the ABCDE incident commander | Highest-scoring idea after the full-marks hunt and Codex's independent run; Omar's own method (primary survey, triage, SBAR) is the design. |
| 2026-10-29 | Banking is the main test system and carries the sealed exam; a second system is the transfer test; the lead story is chosen at Fri 14:00 | Banking gives an exact recovery check (the ledger must balance, every payment posts once). The transfer test shows the same frozen agent works on a system it was never tuned on. |
| 2026-10-29 | The agent is system-agnostic: a 5-function adapter is all it needs; a test system adds a control layer and a checker | Omar's requirement: it must plug into any system, including one the organisers supply. |
| 2026-10-29 | The agent's author never writes the exam | Claude builds the agent and the practice faults; Codex writes the held-out and blind faults, the sealed exam and the scripted runbook baseline. Removes the "tested on its own faults" objection. |
| 2026-10-29 | Two Codex sessions on the laptop | Session A writes and holds the sealed exam and runs no agent arm before seal 2; Session B builds the runbook and the harness, runs the pilot, and never sees the sealed files. |
| 2026-10-29 | The exam is sealed twice, and the push time is the evidence | Seal 1 (scenarios, by 03:00 Fri) and seal 2 (plugin code, by Fri 14:00). The time GitHub received each push proves when the exam was fixed; commit times are set by the committer. The core40 and robust20 lists are pre-registered in `SEALED.json`. |
| 2026-10-29 | The dispatch system is built after `freeze-1`, by Claude; its faults and incidents by Codex | The frozen hashes then show the agent never saw the second system, and its author never sees the transfer exam before the run. A 10-incident transfer run is never cut. |
| 2026-10-29 | The runbook freezes with the agent at `freeze-1` | Both get the same tuning window, which is fairest. After the tag, only an exception fix, with a new hash and a `FROZEN.json` line. |
| 2026-10-29 | Provider errors and harness timeouts are not agent failures | `api_error` and `harness_timeout` cases are re-run once at the end and reported separately (CONTRACT section 11). |
| 2026-10-29 | The model robustness condition is `model_swap` (renamed from the cheaper-model condition) | The robustness question is whether the frozen agent works on a model it was not tuned on, not whether it is cheap. |
| 2026-10-29 | Contract version 1.1: the bank profile and the review fixes | After 1.1, sections 3, 5, 7, 8 and 9 change only by adding optional fields with defaults until `freeze-1`. `CONTRACT_VERSION` in `ic/contract.py` stays 1 until something is published. |
| 2026-10-29 | Deck-review trims adopted | No ECC-style record; English-only SBAR; "weighted shortest-job-first", not START; Smith's rule dropped as evidence; the first-come-first-served ablation is kept because it was cheap to build; deck cut to 10 slides. |
| 2026-10-29 | 30 practice scenarios, written by `scenarios/dev/make_dev.py`: dev-01 to dev-20 for tuning, dev-21 to dev-30 for the pilot only | The agent and the runbook tune on the same 20 cases, and the pilot uses 10 that neither was tuned on. Each case has 1 to 3 harmless background changes from its own seed. Every case was run on a live copy with its labelled fixes before the push. |
| 2026-10-29 | Standard-library services plus psutil, no Docker, no web framework | Fewer moving parts on Windows; each service is a small Python web server Omar can read. |
| 2026-10-29 | Work started on 29 Oct, before the event | The organisers said in a pre-event session that an existing project can be a starting point. Disclosed here and in the README. |

## Freeze record

To be filled at the freeze: the `freeze-1` tag, its commit, the five group hashes from `python run.py hash` (agent, system, baseline, scorer, settings), the runbook hash from `baselines/FROZEN.json` and the push times of both seals.
