# Handoff to Codex

Written by Claude, 29 Oct 2026. All times are Riyadh time (UTC+3). Codex works in two separate sessions on Omar's laptop, so that the person who writes the runbook never sees the exam:

- **Session A** (exam and laptop checks: C0, C1, C4, C5, C6, C7) works in `%USERPROFILE%\Documents\HUMAIN-Incident-Commander`.
- **Session B** (runbook and evaluation harness: C2, C2b, C3) works in its own clone, `%USERPROFILE%\Documents\HUMAIN-IC-baseline`.

**Before pasting (Omar, Thu night, once Claude's handoff fixes are merged into main):**

1. Plug in the laptop. In PowerShell run `powercfg /change standby-timeout-ac 0`, `powercfg /change hibernate-timeout-ac 0`, `powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0` and `powercfg /setactive SCHEME_CURRENT`.
2. Pause Windows Update for a week (Settings > Windows Update).
3. Set the key without typing it into PowerShell, which saves typed commands to a history file: press Start, type "environment", open "Edit environment variables for your account", click New, enter the name `ANTHROPIC_API_KEY`, paste the key as the value, then OK. If you already set it with `setx`, it is set; to clear the history file, run `Remove-Item (Get-PSReadLineOption).HistorySavePath` (this clears all your PowerShell history). Then close every PowerShell and Codex window, so the windows you open next see the key.
4. Make the three folders. In a new PowerShell window run `cd "$env:USERPROFILE\Documents"`, then `git clone https://github.com/Oahsins/HUMAIN-Incident-Commander`, `git clone https://github.com/Oahsins/HUMAIN-Incident-Commander HUMAIN-IC-baseline` and `New-Item -ItemType Directory -Force HUMAIN-sealed`. If a clone folder already exists, run `git -C <folder> switch main` and `git -C <folder> pull` instead. If git asks you to sign in to GitHub, do it now, so Codex's pushes need no sign-in tonight.
5. Open Session A in `HUMAIN-Incident-Commander` and Session B in `HUMAIN-IC-baseline`. Session A must also be able to write `HUMAIN-sealed`: add it as a second writable folder (Codex CLI: `--add-dir "$env:USERPROFILE\Documents\HUMAIN-sealed"`), or give Session A full access. Let each session edit files and run commands in its folders without asking, with network access (git, pip, GitHub and api.anthropic.com), and pre-approve its pushes to `codex/*` branches.
6. Paste the Session A block into Session A and the Session B block into Session B, each in one go. If a session already has an earlier version of this handoff, paste the new block again: it replaces the old one.

Below the two blocks are short follow-up prompts for later tasks.

## Session A: exam and laptop checks

```text
HANDOFF TO CODEX, SESSION A: HUMAIN hackathon, ABCDE Incident Commander
Written by Claude, 29 Oct 2026. All times Riyadh (UTC+3). Read all of it before acting.

1. GOAL
Help Omar ship a working, measurable, well-explained entry to HUMAIN's
"Future AI Builders" hackathon, Challenge 1 (an AI agent that recovers a
failing system). The event runs on Fri 30 and Sat 31 Oct; we aim to publish
by 19:00 Sat, ahead of the deadline. Judging rewards evidence most: held-out
results, robustness and careful evaluation. Most of that evidence is yours.

2. THE PROJECT IN ONE PARAGRAPH
An AI incident commander keeps a failing multi-service system running using the
method emergency medicine uses for several injuries at once: survey every
component in a fixed ABCDE order (Access, Bottlenecks, Capacity, Dependencies,
Events) before fixing anything (one containment step, a failover, is allowed
first when the main journey fails completely); triage the faults by weighted
shortest-job-first (customer impact / time to fix, upstream first); remediate
with six bounded, safe actions only; verify recovery over a sustained window;
hand over with an SBAR, or escalate to a person when no safe action fixes it.
The agent is SYSTEM-AGNOSTIC: each target system supplies a thin adapter (what
the agent can see and do); a test system also supplies a control layer (how
faults are injected) and a checker (what "recovered" means there). Main test
system: a small bank (gateway, payments, fraud screening with a standby,
clearing worker, simulated payment network, double-entry SQLite ledger, test
customers paying nonstop). Use the words "system" or "target system", never
"patient". The steps are inject, survey, triage, remediate, verify, hand over.

3. WHO DOES WHAT
- Omar: every decision, runs commands on this laptop, video, deck, project page,
  free-text answer. He is not a software engineer and must be able to explain
  every file, so keep code small, readable and commented in plain English.
- Claude (in the cloud): plan, test design, contract, the bank, its 6
  practice faults (needed tonight to build and test the agent), its checker,
  the agent and its ablation arms, the safety wrapper, the demo command, the
  dispatch system's platform, adapter, control and checker (after freeze-1),
  reviews of your pull requests.
- You, SESSION A: the Windows setup check and the laptop checks (C0, C4); the
  sealed exam: the 3 named held-out fault types, one blind type, the 60 sealed
  incidents and the robustness cases (C1); the sealed dry run (C5); the final
  run's preparation and the reveal (C6); the dispatch faults and incidents (C7).
- A second Codex session, SESSION B, writes the scripted runbook and the
  evaluation harness. It never sees the exam. Never share sealed files with it.
- The rule behind the split: THE AGENT'S AUTHOR NEVER WRITES THE EXAM, and the
  runbook's author never sees it.

4. WHERE THINGS ARE
- Repository: https://github.com/Oahsins/HUMAIN-Incident-Commander
- READ FIRST, on main (merged before you start): docs/CONTRACT.md (the
  interfaces; it wins over this handoff if they differ), docs/BUILD-PLAN.md
  (timetable, cut lines, go/no-go checks), DECISIONS.md. If main has no
  docs/CONTRACT.md when you start, stop and tell Omar.
- The contract, plan and bank are on main. Branch from main.
- You may read ic/kit/, ic/contract.py, ic/inject.py, ic/systems.py, configs/
  and targets/bank/ (including checker.py) freely. Never read ic/agent/,
  ic/demo.py, ic/guard.py, ic/llm.py, tests/agent/ or any prompt.
- ic/llm.py (Claude) already exists, ported from your 29 Oct scaffold: do not
  port src/llm.py. Reuse your scaffold's ideas where they help (held-out guard,
  final-run audit, manifests), but do not copy files from it into the repository.
- Your clone: %USERPROFILE%\Documents\HUMAIN-Incident-Commander (Omar made it).
- Sealed files: %USERPROFILE%\Documents\HUMAIN-sealed\ (outside the clone; Omar
  made it and made it writable for you).

5. WORKING RULES
- Windows first: PowerShell, a venv, Python 3.11+. No Linux-only tools, no Docker.
- In PowerShell, write %USERPROFILE% as $env:USERPROFILE (for example
  cd "$env:USERPROFILE\Documents\HUMAIN-final"); never write the Windows user name.
- Git identity, in every clone you commit from (never --global):
  git config user.name "Codex (Session A)" and git config user.email
  "325325232+Oahsins@users.noreply.github.com" (Omar's GitHub no-reply address).
  End every commit message with the line "Made by Codex (Session A)".
- COLLISION RULES (CONTRACT.md section 2): work only on branches named
  codex/<task> made from main; never push to main or to claude/* branches.
  Before a branch's first push: git fetch origin, git rebase origin/main, rerun
  your tests. After it has a pull request: git fetch origin, git merge
  origin/main, rerun your tests, git push. Never force-push. One task per pull
  request; Omar merges with "Create a merge commit"; Claude reviews.
- Green means the GitHub Actions tests workflow passes on ubuntu-latest and
  windows-latest.
- Only edit the paths you own (CONTRACT.md section 2): scripts/preflight.py,
  tests/preflight/, targets/bank/faults/heldout/, scenarios/heldout/,
  targets/dispatch/faults/, scenarios/transfer/, tests/dispatch/. A tiny Windows fix in Claude's files is
  allowed only in its own pull request that says exactly what changed and why.
- Contract changes: open a GitHub issue titled "contract: <change>" or ask Omar;
  Claude makes the change. Never edit DECISIONS.md: record hashes in
  scenarios/heldout/SEALED.json and Claude copies them across.
- If Claude's merged code and the contract disagree, tell Omar; once the
  contract is corrected you may use the corrected field.
- Ports: 8900, the default of run.py up and demo, is yours; eval copies 8100,
  8200, 8300 (keep them free outside C4 and the final run); Session B's copies
  8400-8600; live bank tests 8700; a second system's eval copies 9100-9300.
- CLAIMS, in anything judges may read (reports, chart titles, the dispatch
  incidents' names and test data, the sealed files once revealed): give every
  rate as n/N with its 95% Wilson interval, and say where the runbook ties or
  wins; never present pilot or practice results as exam results; never write
  "production-ready"; never name a Saudi bank or a real emergency service; use
  only made-up customers, callers and addresses; never claim SAMA or NCA
  compliance; never call the named held-out types "blind" or "specified blind".
- Never commit or print secrets. Keys live only in environment variables.
- Never share the hackathon platform link or its content; Omar signed an NDA.
- No sign-ups, purchases or posts without Omar's say-so.
- Run your tests before saying something works, and say what you did not test.
- British English, short sentences.

6. INDEPENDENCE AND SEALING RULES (these protect the judging)
- Write the sealed faults from docs/CONTRACT.md plus the code of the system
  under test (ic/kit/, targets/bank/). Never read ic/agent/, ic/demo.py,
  ic/guard.py, ic/llm.py, tests/agent/ or prompts.
- Write sealed files only in %USERPROFILE%\Documents\HUMAIN-sealed\. Copy them
  into the repository paths only for C1's live check, C5 and the final run.
  Also list the sealed
  paths in .git\info\exclude in your clone.
- Stage files by explicit path only (git add scenarios/heldout/SEALED.json).
  Never git add -A, git add . or git add -f in a clone that holds sealed files.
  Before every commit run git status --short and check that nothing under
  scenarios/heldout/ or scenarios/transfer/ except SEALED.json, and nothing
  under targets/*/faults/heldout/ except .gitkeep, is staged. Run
  git status --ignored before every push.
- Sealed content is never pushed before the final run: only SEALED.json.
- Never run the agent (demo, agent or pilot) before seal 2 is on GitHub, and
  never run it on sealed scenarios or sealed faults before the freeze tag
  freeze-1. Dry-run sealed faults with manual fixes only.
- Never paste sealed scenarios or sealed fault code into a chat with Claude or
  into Session B. Report sealed work as pass/fail counts only. Pull requests
  Claude reviews contain no sealed scenario, parameter, label or plugin code,
  including in tests, fixtures, docs, comments and results files.
- If you need a change in Claude's code, ask for a channel by name only (for
  example "set_config for gateway balance_cache_ttl_s"), never for a fault.
- Dry-run outputs of sealed material go to results/sealed-dryrun/ and are never
  committed before freeze-1.

7. TASKS
Tonight: do C0 now, then C1 (contract 1.1 is on main). After each task, carry
on with the next without waiting for replies: push each finished task to its
codex/* branch and open a draft pull request with gh pr create --draft --base
main. If that fails, write the branch name and the push time in NIGHT-REPORT.md
and carry on: for seal 1 the push is the evidence. Stop after C1 and report.
Write what you built and what you did not test into NIGHT-REPORT.md in your
clone (untracked; it is in .gitignore) for Omar at 09:00.

C0  Setup check (about 01:00-01:20)
    - Your clone already exists: git switch main, git pull, set the git
      identity (section 5), make a venv (python -m venv .venv) and run
      .venv\Scripts\python.exe -m pip install -r requirements.txt.
    - Write scripts/preflight.py as CONTRACT.md section 12 says: standard
      library only, main(argv) -> int, the FAIL and WARN rules there (the eval
      copies' ports must be free), and --live for one tiny model call with
      ic.llm.complete using only the signature in section 9: max_tokens=1000
      and the message "Reply with the single word OK." (an answer cut off at
      max_tokens raises ModelError). While configs/models.json "bulk" is null
      and IC_MODEL is unset, check ANTHROPIC_API_KEY. Key presence is checked
      by name only, never by printing a value. Its tests go in tests/preflight/.
    - If preflight reports the key missing although Omar set it, say so in
      NIGHT-REPORT.md: model runs then start from Omar's own PowerShell window.
    - Done when: python run.py preflight prints a pass/fail table on this laptop,
      and python run.py preflight --live makes its one tiny model call. Put
      both results in NIGHT-REPORT.md, so Omar knows at 09:00 whether the key
      works. This one call is not an agent run.
    - Pull request: codex/preflight.

C1  Design and seal the exam (overnight; seal 1 pushed by 03:00 Fri)
    - First run: git check-ignore -v scenarios/heldout/heldout.jsonl
      targets/bank/faults/heldout/x.py. If either path is not ignored, stop and
      tell Omar.
    - Write the 3 named held-out fault types as plugins (CONTRACT.md section 7):
      poison_payment (a malformed clearing item that stops the worker; label
      it (clearing, poison_message) with fix quarantine, then restart
      clearing, and the item id as a runtime param, section 8; (clearing,
      process_down) is an acceptable secondary pair; see the Work queue row in
      section 7.3),
      stale_balances (balances served stale with a normal success code),
      double_posting (a payments release whose retried payments post twice).
      Use only the channels and facts in sections 5 and 7.3. Label each with
      its (target, class) from section 4 and any acceptable secondary pairs.
    - Also write ONE BLIND fault type of your own choosing (channels in sections
      5 and 7.3, an existing class from section 4), fixable by one of the six
      actions or a must-escalate. Do not name or describe it in any committed
      file, pull request or message to Claude or Session B. Give its plugin a
      neutral file name (for example blind_1.py). Use it in 6 to 10 of the 60
      cases, marked "blind": true; SEALED.json counts it only as "blind".
    - Write your own sealed benign plugin under a type name of your own, with
      background changes such as a no-op release, clearing poll_interval_s 0.2
      to 0.25 or a restart of screening-standby. Healthy distractors use
      mechanisms that are not in the practice noise plugin; write them as
      sealed plugins too. Sealed faults take only {"target", "variant"} params.
      No label, session name, statement, log message, change detail or payload
      may contain a fault-type or class name or the words in section 7.2.
    - Write scenarios/heldout/heldout.jsonl: 60 cases in the section 8 format,
      each root cause with its fix. 20 single (about 6 healthy distractors,
      about 6 must-escalate, about 8 genuine faults), 25 double, 15 triple.
      Must-escalate faults appear only in single-fault cases. Build compound
      cases from confusable pairs that share symptoms. Named held-out types
      appear in at least a third of the cases. For practice types, at least
      half the instances use explicit params outside each plugin's defaults and
      variants (section 7.2). Each case holds 1 to 3 benign changes; in at
      least 15 fault cases put one on another component within 10 s of a real
      fault.
    - Must-escalate faults must differ from the practice network_outage, show
      their evidence through observe(), probe() or logs(), have no allowlisted
      action that fixes them, and keep the checker red until a person acts.
    - Order the lines of heldout.jsonl (the run order) so the first 40 ids
      are in proportion (13 single, including 4 healthy and 4 must-escalate;
      17 double; 10 triple): that is the 40-case subset, core40.
    - The 20 robustness case ids (robust20) are drawn from core40 with
      random.Random(2026).sample(core40, 20), with at least 2 healthy and 2
      must-escalate cases (if a draw has fewer, draw again from the same
      generator). Write scenarios/heldout/robustness.jsonl, 40 lines: for each
      robust20 case, its four-fault case (practice faults added on other
      components until it has four faults; id <its id>-ff, input.condition
      four_faults) and its extra_service variant (id <its id>-xs,
      input.condition extra_service). Every line has "source_id", the robust20
      id it was built from. Section 8 gives the rules.
    - Before seal 1, check every sealed type live, because its labels and
      fixes never change after it. Copy the plugins into
      targets/bank/faults/heldout/ for this check only, run python run.py up,
      inject one case per type with python run.py inject <type> target=<t>
      variant=<v> --sealed, and 30 s later confirm python run.py check says
      NOT RECOVERED. Apply its labelled fixes in order with python run.py act,
      and 30 s after the last one confirm it says RECOVERED (a must-escalate
      case stays NOT RECOVERED). Then python run.py down, and delete the copied
      plugins. Seal 1 may slip to 05:00 for this check; never seal a label that
      failed it.
    - Write scenarios/heldout/SEALED.json as CONTRACT.md section 14 says: seal 1
      with the hashes (SHA-256 of the bytes with every CRLF replaced by LF; write
      files with newline="\n"), the composition counts, and the pre-registered
      40-case subset and 20 robustness case ids.
    - Done when: every line of heldout.jsonl and robustness.jsonl matches
      section 8; every type exists in faults/dev or faults/heldout; every
      target is a section 7.1 component (or notifications); every class is in
      section 4; the counts equal SEALED.json's composition; and each sealed
      plugin's inject() runs against a fake Control, calls only section 5
      methods and returns a manifest entry with a section 4 class.
    - Pull request: codex/sealed-exam with SEALED.json only. Push it and open
      the pull request as soon as SEALED.json exists, and put the push time in
      NIGHT-REPORT.md. Plugin bugs found later may be fixed until seal 2 (end of
      C5), with a re-seal and a note in the re-seal pull request description;
      the scenario files never change after seal 1.

C4  Windows bring-up and GO/NO-GO 1 (rehearsal Fri 09:30-10:00; for real
    14:30-16:30)
    - On main: run python -m pytest -q --tb=line --ignore=tests/agent (the
      agent's own tests run its arms, which you may not do before seal 2; CI
      runs them), then BUILD-PLAN.md section 7, GO/NO-GO 1, steps 1-4, using
      python run.py up, status, inject, act and check. Report each step's result.
    - Fix Windows-only problems in your own pull request, as in section 5,
      except in the files you never read: for a failure there, send Omar only
      the test id and its one-line error, for Claude.

C5  Dry-run the sealed faults without the agent (Fri 12:00-14:00)
    - Copy the sealed plugins in. For each named held-out and blind fault:
      inject it with python run.py inject ... --sealed, confirm the checker goes
      red, apply the intended fix with python run.py act ... (the same
      allowlisted action the agent would use; through Control only when no
      action exists), and confirm the checker goes green. For each
      must-escalate case, confirm that no allowlisted act() call turns the
      checker green.
    - Seal 2: add the plugin hashes as a new entry in SEALED.json and push it.
    - After each merge of Claude's pull requests before freeze-1, rerun this
      sealed self-test. Report pass or fail per fault only.

C6  The final run (prepare Fri 21:00-21:30; it runs overnight)
    - After Omar merges every open pull request and says go: tag that main
      commit freeze-1 and push the tag.
    - Clean-clone pass 1: clone tag freeze-1 into
      %USERPROFILE%\Documents\HUMAIN-final, set the git identity there, make
      .venv and run .venv\Scripts\python.exe -m pip install -r requirements.txt
      -r requirements-eval.txt, copy in the sealed files from HUMAIN-sealed,
      create the results folder, and run .venv\Scripts\python.exe run.py up,
      status, check and down. The final run starts from this folder.
    - Omar starts the run in his own PowerShell window, not inside Codex, with
      the command block from the follow-up prompts (a 5-try auto-resume loop).
      Check that it started; progress: Get-Content results\final.log -Tail 20.
    - At Sat 11:00, if the main exam is incomplete, stop the robustness subset
      and report the completed paired cases as n of N.
    - After the final run: commit the sealed files at their original paths with
      git add -f, in a pull request from codex/reveal, beside the final run's
      per-case evidence.

C7  Dispatch faults for the transfer test (Sat 09:00-12:00)
    - Claude builds targets/dispatch/ (platform, adapter, control, checker) after
      freeze-1. Write its faults (targets/dispatch/faults/heldout/) and 20 sealed
      incidents (scenarios/transfer/dispatch.jsonl) from the dispatch adapter and
      control interfaces only. At least 2 fault types should show symptoms that
      no bank practice fault shows. Use only made-up callers and addresses.
    - Seal them in scenarios/transfer/SEALED.json and push only that file
      before the run. Claude never sees them before the run.
    - The run (Sat 12:00-13:00, about 50 minutes): python run.py eval --split
      transfer --final --arms abcde --copies 1 --name transfer-1 (the frozen
      agent, 1 copy on port base 9100). Stop at 14:15 whatever its state. Run the first
      10 incidents first: those 10 are never cut. Report the agent hash beside
      the results.
    - If an organiser system replaces dispatch as the transfer test, do the same
      for it: its faults and 20 sealed incidents, from its adapter and control.

8. WHEN YOU REPORT BACK TO OMAR
Keep it short: what you built; the commands to run; test results; what you did
not test; anything that needs his decision.
```

## Session B: runbook and evaluation harness

```text
HANDOFF TO CODEX, SESSION B: HUMAIN hackathon, ABCDE Incident Commander
Written by Claude, 29 Oct 2026. All times Riyadh (UTC+3). Read all of it before acting.

1. GOAL
Help Omar ship a working, measurable, well-explained entry to HUMAIN's
"Future AI Builders" hackathon, Challenge 1 (an AI agent that recovers a
failing system). The event runs on Fri 30 and Sat 31 Oct; we aim to publish
by 19:00 Sat, ahead of the deadline. Judging rewards evidence most: held-out
results, robustness and careful evaluation. Most of that evidence is yours.

2. THE PROJECT IN ONE PARAGRAPH
An AI incident commander keeps a failing multi-service system running using the
method emergency medicine uses for several injuries at once: survey every
component in a fixed ABCDE order (Access, Bottlenecks, Capacity, Dependencies,
Events) before fixing anything (one containment step, a failover, is allowed
first when the main journey fails completely); triage the faults by weighted
shortest-job-first (customer impact / time to fix, upstream first); remediate
with six bounded, safe actions only; verify recovery over a sustained window;
hand over with an SBAR, or escalate to a person when no safe action fixes it.
The agent is SYSTEM-AGNOSTIC: each target system supplies a thin adapter (what
the agent can see and do); a test system also supplies a control layer (how
faults are injected) and a checker (what "recovered" means there). Main test
system: a small bank (gateway, payments, fraud screening with a standby,
clearing worker, simulated payment network, double-entry SQLite ledger, test
customers paying nonstop). Use the words "system" or "target system", never
"patient". The steps are inject, survey, triage, remediate, verify, hand over.

3. WHO DOES WHAT
- Omar: every decision, runs commands on this laptop, video, deck, project page,
  free-text answer. He is not a software engineer and must be able to explain
  every file, so keep code small, readable and commented in plain English.
- Claude (in the cloud): plan, test design, contract, the bank, its 6
  practice faults, its checker, the agent and its ablation arms, the safety
  wrapper, the demo command, reviews of your pull requests (interface and
  contract conformance only for baselines/).
- A first Codex session, SESSION A, writes the sealed exam and runs the laptop
  checks. You never see the exam.
- You, SESSION B: the scripted runbook baseline with no AI (C2, C2b); the
  evaluation harness, the noop and oracle arms, statistics, charts and the
  report (C3); the pilot, the dry runs and the results report.
- The rule behind the split: THE AGENT'S AUTHOR NEVER WRITES THE EXAM, and you,
  the runbook's author, never see it.

4. WHERE THINGS ARE
- Repository: https://github.com/Oahsins/HUMAIN-Incident-Commander
- READ FIRST, on main (merged before you start): docs/CONTRACT.md (the
  interfaces; it wins over this handoff if they differ), docs/BUILD-PLAN.md
  (timetable, cut lines, go/no-go checks), DECISIONS.md. If main has no
  docs/CONTRACT.md when you start, stop and tell Omar.
- The contract, plan and bank are on main. Branch from main.
- You may read ic/kit/, ic/contract.py, ic/inject.py, ic/systems.py, configs/
  and targets/bank/ (including checker.py) freely. Never read ic/agent/,
  ic/demo.py, ic/guard.py, ic/llm.py, tests/agent/ or any prompt: use them only through the interfaces in
  CONTRACT.md sections 3.6 and 9.
- ic/llm.py (Claude) already exists, ported from your 29 Oct scaffold: do not
  port src/llm.py. Reuse your scaffold's ideas where they help (the held-out
  guard, final-run audit, manifests, runs.csv, the result lock, the report),
  but do not copy files from it into the repository.
- Your clone: %USERPROFILE%\Documents\HUMAIN-IC-baseline (Omar made it). Never open
  %USERPROFILE%\Documents\HUMAIN-sealed\, the sealed paths
  (scenarios/heldout/ except SEALED.json, targets/bank/faults/heldout/) or
  Session A's clones until the final run ends (see the Sat 12:00 prompt).

5. WORKING RULES
- Windows first: PowerShell, a venv, Python 3.11+. No Linux-only tools, no Docker.
- In PowerShell, write %USERPROFILE% as $env:USERPROFILE (for example
  cd "$env:USERPROFILE\Documents\HUMAIN-final"); never write the Windows user name.
- Git identity, in every clone you commit from (never --global):
  git config user.name "Codex (Session B)" and git config user.email
  "325325232+Oahsins@users.noreply.github.com" (Omar's GitHub no-reply address).
  End every commit message with the line "Made by Codex (Session B)".
- COLLISION RULES (CONTRACT.md section 2): work only on branches named
  codex/<task> made from main; never push to main or to claude/* branches.
  Before a branch's first push: git fetch origin, git rebase origin/main, rerun
  your tests. After it has a pull request: git fetch origin, git merge
  origin/main, rerun your tests, git push. Never force-push. One task per pull
  request; Omar merges with "Create a merge commit"; Claude reviews.
- Green means the GitHub Actions tests workflow passes on ubuntu-latest and
  windows-latest. Tests run with python -m pytest -q from the repository root;
  every tests/ subfolder has an __init__.py; no shared conftest.py.
- Only edit the paths you own (CONTRACT.md section 2): baselines/, eval/,
  requirements-eval.txt, tests/eval/, tests/baselines/, and after freeze-1
  replays/demo-frozen.jsonl. A tiny Windows fix in
  Claude's files is allowed only in its own pull request that says exactly
  what changed and why.
- Contract changes: open a GitHub issue titled "contract: <change>" or ask Omar;
  Claude makes the change. Never edit DECISIONS.md: record the runbook's hash
  in baselines/FROZEN.json and Claude copies it across.
- If Claude's merged code and the contract disagree, tell Omar; once the
  contract is corrected you may use the corrected field.
- Ports: every copy you start uses port base 8400, 8500 or 8600, before and
  after freeze-1, including the demo (python run.py demo --port-base 8400) and
  development eval runs (--port-bases 8400,8500,8600). 8900, the default of
  run.py up and demo, is Session A's. Live bank tests use 8700, eval copies
  8100, 8200 and 8300, and a second system's eval copies 9100-9300.
- When main holds the agent, run the full test suite with --tb=line.
- Before every commit run git status --short and check that nothing under
  scenarios/heldout/ or scenarios/transfer/ except SEALED.json is staged.
- CLAIMS, in anything judges may read (the report, chart titles, results
  files): give every rate as n/N with its 95% Wilson interval, and say where the
  runbook ties or wins; never present pilot or practice results as exam
  results; never write "production-ready"; never name a Saudi bank; never claim
  SAMA or NCA compliance.
- Never commit or print secrets. Keys live only in environment variables.
- Never share the hackathon platform link or its content; Omar signed an NDA.
- No sign-ups, purchases or posts without Omar's say-so.
- Run your tests before saying something works, and say what you did not test.
- British English, short sentences.

6. INDEPENDENCE RULES (these protect the judging)
- Write the runbook from docs/CONTRACT.md plus the code of the system under
  test (ic/kit/, targets/bank/). Never read ic/agent/, ic/demo.py, ic/guard.py,
  ic/llm.py, tests/agent/ or prompts.
- Test eval/ with invented fixtures only. Never ask Session A or Omar for
  sealed scenarios, parameters or labels.

7. TASKS
Tonight: start C2, then C3 (contract 1.1 is on main). After each task, carry
on with the next without waiting for replies: push each finished task to its
codex/* branch and open a draft pull request with gh pr create --draft --base
main. If that fails, write the branch name and the push time in NIGHT-REPORT.md
and carry on. Stop after C3 and report. Write
what you built and what you did not test into NIGHT-REPORT.md in your clone
(untracked; it is in .gitignore) for Omar at 09:00.

C2  Scripted runbook baseline, no AI (overnight)
    - Your clone already exists: git switch main, git pull, set the git
      identity (section 5), make a venv (python -m venv .venv) and run
      .venv\Scripts\python.exe -m pip install -r requirements.txt.
    - baselines/runbook.py exposes run_incident(adapter, *, budget_s=90.0,
      max_steps=40, model=None, log=None, seed=0, mode="auto", confirm=None, **_)
      and returns the section 9 result with arm="runbook" and calls=[], with
      every action record as section 9 gives it (including sent). In advise
      mode, put the action your rule would take in proposed_actions without
      calling act().
    - A competent operator's runbook. It reads the topology from describe() and
      keys its rules on component kind and the observed signals (the standard
      fields and reserved extra keys in section 3.2), never on bank component
      names, so the frozen runbook can also run on another system. It may parse
      v1 log fields (section 3.3). One fixed if-then rule per practice fault
      signature (crash, bad_update, bad_setting, locked_ledger, stopped_worker,
      slow_screening), with the same six actions and step budget as the agent.
    - Loop: observe and probe; check every rule in a fixed order; apply the
      first rule that fires; wait the action's est_seconds; repeat. Never apply
      the same action to the same target twice in a row. Declare recovered when
      the probe passes 3 times in a row over at least 10 s. Escalate when no
      rule fires and the probe fails. Return no_incident when no rule fires and
      the probe passes. Stop at the step or time budget. Write a short template
      SBAR from what it saw. Make it genuinely good: the judges will ask whether
      the AI beats it.
    - tests/baselines/test_isolation.py applies the section 9 isolation rules to
      baselines/.
    - Done when: tests/baselines pass: on a fake adapter each of the 6 practice
      signatures leads to its one right action, a healthy fake to no action and
      outcome no_incident, an external outage to outcome escalated, and no test
      sees a refused action. Then run it once on each single-fault practice
      fault on a live copy of the bank (port base 8700) and fix field names
      and crashes.
    - It freezes with the agent at freeze-1 (both get the same tuning window).
      Until then you may improve it on practice scenarios dev-01 to dev-20 only.
    - Pull request: codex/runbook.

C3  Evaluation harness, statistics and charts (overnight, after C2)
    - eval/cli.py main(argv) implements the eval command line in CONTRACT.md
      section 12 (python run.py eval hands over to it). Scenario files:
      scenarios/dev/dev.jsonl, scenarios/heldout/heldout.jsonl,
      scenarios/heldout/robustness.jsonl and scenarios/transfer/dispatch.jsonl
      (--split transfer). --condition C overrides input.condition for every
      case. On --split heldout, a condition other than default runs only the
      robust20 ids in SEALED.json, in robust20 order: log_format_v2 and
      model_swap take those cases from heldout.jsonl; four_faults and
      extra_service take the robustness.jsonl lines with that input.condition
      (id: the robust20 id plus -ff or -xs; "source_id": the robust20 id).
      --report RUN --against final-1 pairs a robustness run with the main run
      by source_id (section 8).
    - Model: --model, else IC_MODEL, else configs/models.json "bulk". Under
      --condition model_swap the AI arms get configs/models.json "swap"
      instead, whatever --model and IC_MODEL say; refuse if swap is null or
      equals bulk. Refuse to start only when an AI arm is asked for and no
      model is set: noop, oracle and runbook need none.
    - Per case: systems.platform(system, port_base=...) -> start(warm-up) ->
      inject.apply(..., t0) -> wait the alert delay -> run the arm's
      run_incident on Guard(platform.adapter(), mode="auto", max_steps=40,
      audit_path=runs/audit/<run>-<case>-<arm>.jsonl, in a runs/audit/ you
      create first), stopping it at budget_s + 5 s -> keep the system running until H -> at H + 10 s call
      checker.verify(control, window_s=CHECK_WINDOW_S, lag_s=CHECK_LAG_S,
      since_t=<t of the first manifest entry>) -> copy the evidence files to
      results/<run>/cases/<case-id>/ -> stop. Timings in sections 13 and 6.
    - Arms: from ic.agent import load_arm for abcde, naive_verify, fifo and
      react; baselines.runbook.run_incident for runbook; implement noop and
      oracle in eval/ (section 9; the oracle applies each fix and then its
      then actions, with null params filled from the manifest, section 8). ic/agent/ reaches main only about 09:00
      Fri, when Omar merges Claude's agent pull request: import it only when
      an AI arm is asked for, so noop, oracle, runbook and your tests work
      tonight, and an AI arm before then stops with a one-line message.
    - Copies: --copies N runs cases in parallel on the first N of --port-bases
      (default 8100,8200,8300; 9100,9200,9300 for --split transfer).
      Development runs pass --port-bases 8400,8500,8600.
    - Run order: case-major in the scenario file's line order (heldout.jsonl's
      first 40 lines are core40, so --limit 40 runs core40; a robustness run
      follows robust20 order): case 1 under every arm, then case 2, with the
      arms in each case in an order shuffled with seed 0, so a partial run is
      still paired. Copies take cases round-robin.
    - Resumable: a rerun with the same --name skips finished (case, arm) pairs;
      the first complete result counts.
    - Per-case watchdog: after 300 s, kill the case's process tree with psutil
      and record outcome harness_timeout. A case whose result has outcome
      gave_up or budget_exhausted and whose last model call has status "failed"
      with error http_429, http_500, http_502, http_503, http_529, timeout or
      unavailable is scored api_error. api_error and harness_timeout cases are
      re-run once at the end, reported separately, and never counted as agent
      failures. Other errors stay in the denominator.
    - --final: check the files against the newest entry in SEALED.json
      "seals" and refuse on a hash mismatch or an unlisted file, ignoring
      SEALED.json, .gitkeep and __pycache__ (section 14); manifests record git
      rev-parse HEAD and run.py's hashes() (section 15). For --split transfer,
      see CONTRACT.md section 12.
    - Exit code: eval exits 0 only when every (case, arm) pair has a result.
    - Metrics, validity and statistics: CONTRACT.md sections 11 and 16 (Wilson
      95% intervals, exact McNemar, Holm, paired bootstrap, Wilcoxon), a
      Markdown results table, and charts (case success by arm with intervals;
      user-impact seconds by arm; tokens and cost).
    - requirements-eval.txt: matplotlib (pip install it too).
    - Done when: tests/eval pass: a fake platform and a fake arm run 4 cases on
      2 copies; a rerun with the same name skips them; --final refuses when a
      SEALED.json hash differs and accepts a matching seal while .gitkeep and
      SEALED.json are present; Wilson 95% for 8/10 is 0.49-0.94; exact McNemar
      with 1 and 7 discordant pairs gives p = 0.070; the report writes a
      Markdown table and 3 PNG charts. tests/eval/test_checker_audit.py builds
      small ledgers and customer logs, each with one planted defect (a
      duplicate, a ghost, a lost payment, a stale read, a wrongly quarantined
      item, a failure still in flight), and asserts that verify() flags exactly
      that defect.
    - Pull request: codex/eval.

C2b Runbook on the merged bank (Fri 11:00-12:00)
    - Run the runbook on each of the 6 practice faults alone and on 5 compound
      practice scenarios from dev-01 to dev-20, then fix its rules.

Friday, also yours (follow-up prompts give the times): the model-key check and
the harness end to end (10:00-11:00), the pilot (17:30), the prices check and a
resume test (18:30-20:00), the dry run and checker calibration (20:00-21:00),
baselines/FROZEN.json and a backup demo take (21:00-21:30). Saturday: the
results report and charts from the final run.

8. WHEN YOU REPORT BACK TO OMAR
Keep it short: what you built; the commands to run; test results; what you did
not test; anything that needs his decision.
```

## Follow-up prompts for Omar

Paste these into the named session when the time comes.

- **Fri 09:00-09:30 (Omar first):** read both NIGHT-REPORT.md files, review and merge the overnight pull requests and Claude's agent pull request once the tests workflow is green. If the morning is lost, do the same from 14:00.
- **Fri 09:30, Session A:** "Pull main and start C4 as a rehearsal: run the tests as C4 says, then GO/NO-GO 1 steps 1-4 in BUILD-PLAN.md section 7, and report each step's result."
- **Fri 10:00, Session B:** "Pull main. Run `python run.py demo --port-base 8400` once to check the model key (practice faults only). Then run the harness end to end on 3 practice scenarios with `--model anthropic:claude-opus-5-5`, first on 1 copy, then on 3 copies, with `--port-bases 8400,8500,8600`. At 11:00 start C2b."
- **Fri 12:00, Session A:** "Start C5: dry-run the sealed faults without the agent, then push seal 2. Report pass/fail per fault only."
- **Fri 14:30, Session A:** "C4 for real: GO/NO-GO 1 steps 1-4 on eval port bases 8100, 8200, 8300. Report each step's result."
- **Fri 16:30, Session B (after GO/NO-GO 1):** "Tune the runbook on dev-01 to dev-20 only; it freezes with the agent at freeze-1."
- **Fri 17:30, Session B:** "Run the pilot: `python run.py eval --split dev --ids dev-21,dev-22,dev-23,dev-24,dev-25,dev-26,dev-27,dev-28,dev-29,dev-30 --arms abcde,react,runbook --copies 3 --model anthropic:claude-opus-5-5 --name pilot-1` (to try another candidate model, run it again with that `--model` and its own name). Send me the results table; its numbers stay internal."
- **Fri 18:30, Session B:** "Check configs/prices.json against the provider's price page and send Claude any differences. Then test resume: stop a run and rerun it with the same name."
- **Fri 20:00, Session B:** "Pull main first. Dry run: `python run.py eval --split dev --limit 6 --arms abcde,runbook,react,naive_verify,fifo,noop,oracle --copies 3 --name dry-1`, plus 1 practice scenario under `log_format_v2` and `extra_service` with the runbook arm, and 1 under `model_swap` with the abcde arm (check that its calls name the swap model). Report the mean minutes per incident and how many copies ran without interference. Checker calibration: run noop on the healthy practice cases dev-09, dev-18 and dev-24, four times each across 3 copies (names `calib-1` to `calib-4`); tell Claude if more than 1 of the 12 is red."
- **Fri 21:00, Session B:** "Commit baselines/FROZEN.json (the runbook file's hash and the freeze time) and open its pull request. After the freeze tag, record one backup demo take on the frozen agent: `git fetch --tags; git switch -c codex/demo-replay freeze-1`, then `New-Item -ItemType Directory -Force replays | Out-Null; $env:IC_RECORD='replays\demo-frozen.jsonl'; python run.py demo --port-base 8400; Remove-Item Env:IC_RECORD`. Open a pull request from codex/demo-replay with only replays/demo-frozen.jsonl in it. Finish before the final run starts at 21:30."
- **Fri 21:00, Session A (after Omar merges every open pull request):** "Start C6: tag freeze-1 and push the tag, then clean-clone pass 1 into %USERPROFILE%\Documents\HUMAIN-final with the sealed files copied in."
- **Fri 21:30, Omar in a new PowerShell window (arms as set by GO/NO-GO 3; for the core40 cut add `--limit 40` and skip `robust-v2` and `robust-xs`):**

  ```powershell
  cd "$env:USERPROFILE\Documents\HUMAIN-final"
  New-Item -ItemType Directory -Force results | Out-Null
  $env:PYTHONUTF8 = '1'
  for ($i = 1; $i -le 5; $i++) {
    .\.venv\Scripts\python.exe run.py eval --split heldout --final --arms abcde,runbook,react,naive_verify,fifo,noop,oracle --copies 3 --name final-1 *>> results\final.log
    if ($LASTEXITCODE -eq 0) { break }
  }
  ```

  Then the robustness subset the same way: `--arms abcde,runbook,noop,oracle` with `--condition four_faults` and `extra_service` (names `robust-ff`, `robust-xs`), `--arms abcde,runbook --condition log_format_v2` (name `robust-v2`), and `--arms abcde --condition model_swap` (name `robust-ms`). Check progress with `Get-Content results\final.log -Tail 20`.
- **Sat 09:00, Session A:** "Start C7: write the dispatch faults and 20 sealed incidents from the dispatch adapter and control interfaces, seal them, push only scenarios/transfer/SEALED.json, and report."
- **Sat 11:00, Session A:** "If the main exam is incomplete, stop the robustness subset and report the completed paired cases as n of N."
- **Sat 12:00, Session B:** "The final run is over, so you may now open %USERPROFILE%\Documents\HUMAIN-final; change nothing there outside results/. In that folder run `python run.py eval --report final-1`, then `--report robust-ff --against final-1` (and the same for robust-v2, robust-xs and robust-ms), with n/N, intervals, and where the runbook ties or wins, and send Omar the tables for Claude." **Session A:** "Run the transfer test (C7), then open the codex/reveal pull request with the sealed files."
- **Sat 16:00, Session A:** "Scan the full git history for secrets and report. After Omar makes the repository public, clean-clone pass 2: `$env:GIT_TERMINAL_PROMPT=0; git -c credential.helper= clone https://github.com/Oahsins/HUMAIN-Incident-Commander ic-clean`, follow the README exactly, run `python run.py demo`, then run it again in the same window with the key unset (`Remove-Item Env:ANTHROPIC_API_KEY`, which affects only that window): it must print 'REPLAY of a recorded run (no API key found)' and replay replays/demo-frozen.jsonl. Report anything that fails." Repeat the check at 18:00.
