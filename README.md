# HUMAIN Incident Commander

An AI incident commander for HUMAIN's Future AI Builders hackathon (Challenge 1: an AI agent that recovers a failing system).

It keeps a failing multi-service system running using the method emergency medicine uses for several injuries at once. It surveys every component in a fixed ABCDE order (Access, Bottlenecks, Capacity, Dependencies, Events) before fixing anything, triages the faults by customer impact against time to fix, remediates with six bounded, safe actions only, verifies recovery over a sustained window, and hands over with an SBAR, or escalates to a person when no safe action fixes the fault. A safety wrapper refuses any action outside the allowlist, and an independent checker decides whether the system really recovered, from evidence the agent never sees.

The agent is system-agnostic: it needs only a 5-function adapter (describe, observe, logs, probe, act). A test system also supplies a control layer for fault injection and a checker. The main test system is a small bank around a double-entry ledger. The transfer test runs the frozen agent on a second system built after the freeze.

> **Status (29 Oct 2026):** being built. The bank, the test kit and the planning documents are in place; the agent, the sealed exam and the results follow. Work started on 29 Oct, before the event, and is disclosed here. The commit history shows the dates.

## Quick start

Needs Python 3.11 or later, on Windows or Linux.

No install: [open it in GitHub Codespaces](https://codespaces.new/Oahsins/HUMAIN-Incident-Commander?quickstart=1) (a free GitHub account is enough). The browser terminal opens with the requirements installed, so `python run.py demo` works straight away.

```
pip install -r requirements.txt
python run.py preflight      # laptop checks (Codex adds them): Python, packages, model key, free ports, disk space
python run.py up             # starts the bank (port base 8900) and its test customers
python run.py status         # every component and its health
python run.py demo           # a 2-fault incident: inject, survey, triage, remediate, verify, hand over
python run.py check          # the independent checker's verdict
python run.py down           # stops everything
```

`python run.py demo` runs live when `ANTHROPIC_API_KEY` is set. Without a key it replays a recorded run of the frozen agent (`replays/demo-frozen.jsonl`) and says so first. The system and the checks run live; only the model's answers are replayed, so the handover quotes the recorded run's times. Keys are read only from environment variables, never from files.

## Documents

- [Build plan](docs/BUILD-PLAN.md): timetable, roles, go/no-go checks, cut lines, test design
- [Interface contract](docs/CONTRACT.md): how the agent, the test systems, the faults, the checker and the evaluation fit together
- [Codex handoff](docs/CODEX-HANDOFF.md): the tasks Codex owns on the Windows laptop
- [Adding a system](docs/ADDING-A-SYSTEM.md): how to connect the agent to a system that already runs, or build a new test system on `ic/kit`
- [Decision log](DECISIONS.md)

Once results exist, the README will add them. Results will be reported only from real runs, with n/N and intervals.
