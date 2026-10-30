"""`python run.py agent` and `python run.py demo`: the incident commander on a running copy, with a live timeline.

    agent   respond to whatever is wrong with the copy now
    demo    start a fresh copy, inject a two-fault incident, respond, then show the checker's verdict

The model is --model, else IC_MODEL, else configs/models.json "default". With
replay:<file> the demo replays recorded model answers and needs no key; with no
key set and no --model, `demo` replays replays/demo-frozen.jsonl. Record a run
with IC_RECORD=<file>.
"""

import json
import os
import time

from ic import contract, inject, systems
from ic.agent import load_arm
from ic.guard import Guard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_REPLAY = os.path.join("replays", "demo-frozen.jsonl")
KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
PHASE_STYLE = {"survey": "cyan", "triage": "magenta", "remediate": "yellow", "verify": "green", "hand_over": "blue"}


def model_name(flag):
    if flag:
        return flag
    if os.environ.get("IC_MODEL"):
        return os.environ["IC_MODEL"]
    try:
        with open(os.path.join(ROOT, "configs", "models.json"), encoding="utf-8") as handle:
            return json.load(handle).get("default")
    except (OSError, ValueError):
        return None


def usable_model(flag, demo):
    """The model to run, after checking its key. A demo with no key and no --model replays the recorded run."""
    model = model_name(flag)
    if not model:
        raise ValueError("no model: pass --model provider:model or set IC_MODEL")
    key = KEY_VARS.get(model.split(":", 1)[0])
    if key and not os.environ.get(key):
        if demo and not flag and os.path.exists(os.path.join(ROOT, DEMO_REPLAY)):
            print("REPLAY of a recorded run (no API key found)")
            return "replay:" + os.path.join(ROOT, DEMO_REPLAY)
        raise ValueError(f"{key} is not set. Set it, or pass --model replay:<file> to replay a recorded run")
    return model


def _console():
    try:
        from rich.console import Console
        return Console(highlight=False)
    except ImportError:
        return None


def _printer(console):
    def show(event):
        line = f"{event['t']:6.1f}s  {event['phase']:<10} {event['name']:<12} {event['summary']}"
        if console:
            console.print(f"[dim]{event['t']:6.1f}s[/dim]  [{PHASE_STYLE.get(event['phase'], 'white')}]"
                          f"{event['phase']:<10}[/] {event['name']:<12} {event['summary']}", markup=True)
        else:
            print(line)
    return show


def _confirm(record):
    answer = input(f"  Take {record['action']} on {record['target']} {record['params'] or ''}? "
                   f"Reason: {record['reason'][:120]} [y/N] ")
    return answer.strip().lower() in ("y", "yes")


def _report(result, console):
    out = console.print if console else print
    out("")
    out(f"Outcome: {result['outcome'].upper()}  ({len([a for a in result['actions'] if a['sent']])} action(s) sent, "
        f"{result.get('steps')} adapter calls, {result['t_declared'] - result['t_start']:.1f} s)")
    for cause in result["root_causes"]:
        out(f"  root cause: {cause['class']} on {cause['target']}")
    if result.get("escalation"):
        e = result["escalation"]
        out(f"  escalated ({e['urgency']}) to {e['to']}: {e['ask']}")
    for record in result.get("proposed_actions") or []:
        out(f"  proposed: {record['action']} on {record['target']} {record['params'] or ''}")
    cost = sum(c.get("estimated_cost_usd") or 0 for c in result["calls"])
    out(f"  model calls: {len(result['calls'])}, estimated cost ${cost:.4f}")
    out("")
    for part in ("situation", "background", "assessment", "recommendation"):
        out(f"{part.upper()}: {result['sbar'][part]}")


def _save(platform, result):
    path = os.path.join(platform.data_dir, f"agent-{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, default=str)
    return path


def respond(platform, args, console, model):
    arm = load_arm(args.arm)
    show = _printer(console)
    print(f"incident commander ({args.arm}, {model}, mode {args.mode}, budget {args.budget:.0f} s)")
    guard = Guard(platform.adapter(), mode=args.mode, confirm=_confirm if args.mode == "confirm" else None,
                  max_steps=contract.AGENT_MAX_STEPS, audit_path=os.path.join(platform.data_dir, "guard-audit.jsonl"))
    result = arm(guard, model=model, budget_s=args.budget, log=show)
    _report(result, console)
    print(f"\nfull result: {os.path.relpath(_save(platform, result), ROOT)}")
    return result


def main(args):
    from run import _target   # the copy the command line points at
    console = _console()
    system, port_base = _target(args)
    model = usable_model(args.model, demo=args.command == "demo")
    platform = systems.platform(system, port_base=port_base)
    if args.command == "agent":
        result = respond(platform, args, console, model)
        return 0 if result["outcome"] in ("recovered", "no_incident", "advised") else 1

    # demo: a fresh copy, a two-fault incident, the response, then the checker's verdict
    if platform.running():
        platform.stop()
    print(f"starting a fresh {system} on {port_base} ...")
    platform.start(warmup_s=contract.WARMUP_S)
    try:
        t_fault = time.time()
        faults = getattr(platform, "demo_faults", [])
        inject.apply(system, platform.control(), faults, seed=7)
        print(f"{len(faults)} fault(s) injected; the alert fires in {contract.ALERT_DELAY_S:.0f} s")
        time.sleep(contract.ALERT_DELAY_S)
        result = respond(platform, args, console, model)
        # The checker scores journeys that started after the last action and have all finished.
        last = max([a["t"] for a in result["actions"] if a.get("sent")] + [result["t_declared"]])
        wait_s = max(0.0, last + contract.CHECK_WINDOW_S + contract.CHECK_LAG_S + 1 - time.time())
        print(f"\nwaiting {wait_s:.0f} s for a clean checker window (every customer retry finished), then asking "
              f"the checker ...")
        time.sleep(wait_s)
        verdict = systems.checker(system).verify(platform.control(), window_s=contract.CHECK_WINDOW_S,
                                                 lag_s=contract.CHECK_LAG_S, since_t=t_fault)
        print("CHECKER: " + ("RECOVERED" if verdict["recovered"] else "NOT RECOVERED: " + "; ".join(verdict["reasons"])))
        return 0 if verdict["recovered"] else 1
    finally:
        platform.stop()
