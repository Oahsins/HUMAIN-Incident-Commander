"""One command line for the whole project (CONTRACT.md section 12).

    python run.py up                          start a copy of the test bank and wait for its warm-up
    python run.py status                      what the agent would see: every component, and one probe
    python run.py inject crash target=payments
    python run.py inject --scenario scenarios/dev/dev.jsonl --id dev-07
    python run.py act restart payments        take one allowlisted action, as an operator would
    python run.py check                       the checker's verdict (has it really recovered?)
    python run.py down                        stop the copy
    python run.py hash [--json]               the content hashes recorded at the freeze
    python run.py agent | demo                run the incident commander (arrives with the agent)
    python run.py eval ... | preflight        hand over to eval/ and scripts/preflight.py (Codex)

Every command takes --system and --port-base. Without them, a command uses the
copy that `up` started last (runs/current.json), else the bank on 8900. (Evaluation copies use
8100, 8200 and 8300, so a copy started by hand never takes their ports.)

This file imports nothing outside the standard library at the top, so
`preflight` works before the requirements are installed.
"""

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(ROOT, "runs")
CURRENT = os.path.join(RUNS, "current.json")
DEFAULT_PORT_BASE = 8900   # eval copies use 8100, 8200, 8300; tests 8700; Codex's development copies 8400-8600

# What `hash` covers (CONTRACT.md section 15). Paths are relative to the repository root.
HASH_GROUPS = {
    "agent": ["ic/agent", "ic/guard.py", "ic/llm.py", "ic/contract.py"],
    "system": ["ic/kit", "ic/inject.py", "ic/systems.py", "targets/bank"],
    "baseline": ["baselines"],
    "scorer": ["eval"],
    "settings": ["configs", "run.py", "ic/demo.py"],
}
HASH_SKIP_DIRS = {"__pycache__", "heldout"}   # sealed fault plugins are hashed through SEALED.json
SEALED_FILES = ["scenarios/heldout/SEALED.json", "scenarios/transfer/SEALED.json"]

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ----- which copy -----

def _read_current():
    try:
        with open(CURRENT, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _target(args):
    """(system, port_base) from the flags, else the last `up`, else the bank on 8900."""
    current = _read_current()
    system = args.system or current.get("system") or "bank"
    port_base = (args.port_base or (current.get("port_base") if system == current.get("system") else None)
                 or DEFAULT_PORT_BASE)
    return system, int(port_base)


def _platform(system, port_base, **kwargs):
    from ic import systems
    return systems.platform(system, port_base=port_base, **kwargs)


def _injected_path(platform):
    return os.path.join(platform.data_dir, "injected.jsonl")


def _injected(platform):
    try:
        with open(_injected_path(platform), encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except OSError:
        return []


def _value(text):
    """key=value values: numbers, true/false/null and JSON stay typed; anything else is a string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _params(pairs):
    params = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        params[key] = _value(value)
    return params


def _print_json(value):
    print(json.dumps(value, indent=1, default=str))


# ----- commands -----

def cmd_up(args):
    system, port_base = _target(args)
    platform = _platform(system, port_base, seed=args.seed, condition=args.condition)
    print(f"starting {system} on ports {port_base}-{port_base + 9} (condition {args.condition}, seed {args.seed}); "
          f"warm-up {args.warmup:.0f} s ...")
    platform.start(warmup_s=args.warmup, detached=True)
    os.makedirs(RUNS, exist_ok=True)
    with open(CURRENT, "w", encoding="utf-8") as handle:
        json.dump({"system": system, "port_base": port_base, "data_dir": platform.data_dir,
                   "condition": args.condition, "seed": args.seed, "t_up": time.time()}, handle, indent=1)
    print(f"{system} is up. Data and logs: {os.path.relpath(platform.data_dir, ROOT)}")
    return 0


def _flags(entry):
    flags = []
    if entry.get("up") is False:
        flags.append("DOWN")
    for key, label in (("error_rate", "errors"), ("reject_rate", "refused")):
        if (entry.get(key) or 0) > 0.02:
            flags.append(f"{label} {entry[key]:.0%}")
    extra = entry.get("extra") or {}
    if extra.get("not_answering"):
        flags.append("not answering")
    if extra.get("exits_15m"):
        flags.append(f"exited {extra['exits_15m']}x in 15 min")
    if (extra.get("oldest_pending_s") or 0) > 5:
        flags.append(f"backlog {extra.get('queue_depth')} (oldest {extra['oldest_pending_s']:.0f} s)")
    if extra.get("lock_holders"):
        flags.append("lock held by " + ", ".join(h.get("session", "?") for h in extra["lock_holders"]))
    if extra.get("write_errors"):
        flags.append(f"{extra['write_errors']} failed writes")
    for name, count in (extra.get("integrity") or {}).items():
        if count:
            flags.append(f"{name.replace('_', ' ')}: {count}")
    if extra.get("active") == "standby":
        flags.append("on standby")
    if extra.get("running"):
        flags.append("job running")
    return ", ".join(flags)


def cmd_status(args):
    system, port_base = _target(args)
    adapter = _platform(system, port_base).adapter()
    obs = adapter.observe(args.window)
    print(f"{system} on {port_base}, last {args.window:.0f} s:")
    print(f"  {'component':<20}{'up':<7}{'p95 ms':>8}{'rps':>7}  notes")
    for name, entry in obs["components"].items():
        up = {True: "yes", False: "NO", None: "-"}[entry.get("up")]
        p95 = f"{entry['p95_ms']:.0f}" if isinstance(entry.get("p95_ms"), (int, float)) else "-"
        rps = f"{entry['rps']:.1f}" if isinstance(entry.get("rps"), (int, float)) else "-"
        print(f"  {name:<20}{up:<7}{p95:>8}{rps:>7}  {_flags(entry)}")
    for change in obs.get("changes", [])[-5:]:
        print(f"  change {time.time() - change['t']:.0f} s ago: {change['component']} {change['kind']} "
              f"by {change['actor']} {change.get('detail') or ''}")
    probe = adapter.probe()
    steps = " ".join(f"{s['step']}={'ok' if s['ok'] else 'FAIL'}" for s in probe.get("steps", []))
    print(f"  probe ({probe.get('journey')}): {steps}")
    failing = [s for s in probe.get("steps", []) if not s.get("ok")]
    if failing:
        print(f"    {failing[0]['step']}: {failing[0].get('detail', '')}")
    return 0


def _scenario_case(path, case_id):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                case = json.loads(line)
                if case.get("id") == case_id:
                    return case
    raise SystemExit(f"no case {case_id!r} in {path}")


def cmd_inject(args):
    from ic import inject
    system, port_base = _target(args)
    platform = _platform(system, port_base)
    seed = args.seed
    if args.scenario:
        if not args.id:
            raise SystemExit("--scenario needs --id")
        case = _scenario_case(args.scenario, args.id)
        faults = case["input"]["faults"]
        seed = case["input"].get("seed", seed)
        if case["input"].get("system", system) != system:
            raise SystemExit(f"{args.id} is a {case['input']['system']} case; this copy runs {system}")
    elif args.type:
        faults = [{"type": args.type, "at_s": 0, "params": _params(args.params)}]
    else:
        raise SystemExit("give a fault type (python run.py inject crash target=payments) or --scenario and --id")
    manifest = inject.apply(system, platform.control(), faults, seed=seed, allow_sealed=args.sealed,
                            on_inject=lambda e: print(f"injected {e.get('type')} at +{e.get('at_s', 0)} s"))
    with open(_injected_path(platform), "a", encoding="utf-8") as handle:
        for entry in manifest:
            handle.write(json.dumps(entry, default=str) + "\n")
    if not args.sealed:
        _print_json(manifest)
    return 0


def cmd_act(args):
    system, port_base = _target(args)
    adapter = _platform(system, port_base).adapter()
    answer = adapter.act(args.action, args.target, _params(args.params))
    _print_json(answer)
    return 0 if answer.get("ok") else 1


def cmd_check(args):
    from ic import contract, systems
    system, port_base = _target(args)
    platform = _platform(system, port_base)
    injected = _injected(platform)
    since_t = min((e["t"] for e in injected if e.get("t")), default=None)
    verdict = systems.checker(system).verify(platform.control(), window_s=args.window or contract.CHECK_WINDOW_S,
                                             lag_s=contract.CHECK_LAG_S if args.lag is None else args.lag,
                                             since_t=since_t)
    if args.json:
        _print_json(verdict)
    else:
        print("RECOVERED" if verdict.get("recovered") else "NOT RECOVERED")
        for reason in verdict.get("reasons", []):
            print(f"  - {reason}")
        if verdict.get("impact"):
            print(f"  impact since the first fault: {verdict['impact']}")
    return 0 if verdict.get("recovered") else 1


def cmd_down(args):
    system, port_base = _target(args)
    _platform(system, port_base).stop()
    print(f"{system} on {port_base} stopped")
    return 0


def file_hash(path):
    """SHA-256 of a file's bytes with every CRLF turned into LF (the same on Windows and Linux)."""
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read().replace(b"\r\n", b"\n")).hexdigest()


def _group_files(paths):
    for rel in paths:
        full = os.path.join(ROOT, rel)
        if os.path.isfile(full):
            yield rel
        elif os.path.isdir(full):
            for folder, dirs, files in os.walk(full):
                dirs[:] = sorted(d for d in dirs if d not in HASH_SKIP_DIRS)
                for name in files:
                    if not name.endswith(".pyc"):
                        yield os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, "/")


def hashes():
    """{group: sha256} for the five freeze groups, plus every SEALED.json that exists. Empty groups are null."""
    out = {}
    for group, paths in HASH_GROUPS.items():
        lines = [f"{rel} {file_hash(os.path.join(ROOT, rel))}\n" for rel in sorted(set(_group_files(paths)))]
        out[group] = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest() if lines else None
    for rel in SEALED_FILES:
        full = os.path.join(ROOT, rel)
        if os.path.exists(full):
            out[rel] = file_hash(full)
    return out


def cmd_hash(args):
    values = hashes()
    if args.json:
        _print_json(values)
    else:
        for name, value in values.items():
            print(f"{name:<34}{value or '(nothing yet)'}")
    return 0


def cmd_agent(args):
    try:
        from ic.agent import load_arm  # noqa: F401
    except ImportError:
        print("The incident commander arrives with the agent's pull request; this checkout does not have it yet.")
        return 2
    from ic import demo
    return demo.main(args)


def _hand_over(path, module_name, argv):
    """Call main(argv) in a module Codex owns: scripts/preflight.py (standard library only) or eval/cli.py."""
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        print(f"{path} is Codex's and is not in this checkout yet.")
        return 2
    if module_name:
        module = importlib.import_module(module_name)
    else:
        spec = importlib.util.spec_from_file_location("_ic_preflight", full)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.main(argv)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # eval and preflight take their own flags: hand everything after the command over unparsed.
    if argv and argv[0] == "preflight":
        return _hand_over("scripts/preflight.py", None, argv[1:])
    if argv and argv[0] == "eval":
        return _hand_over("eval/cli.py", "eval.cli", argv[1:])

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--system", help="the test system (default: the last `up`, else bank)")
    common.add_argument("--port-base", type=int, help="first of the copy's 10 ports (default: the last `up`, else 8900)")
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("up", parents=[common], help="start a copy and wait for its warm-up")
    p.add_argument("--condition", default="default")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--warmup", type=float, default=10.0)
    p.set_defaults(fn=cmd_up)

    p = sub.add_parser("status", parents=[common], help="every component as the agent sees it, and one probe")
    p.add_argument("--window", type=float, default=10.0)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("inject", parents=[common], help="inject a fault, or a scenario case's faults")
    p.add_argument("type", nargs="?")
    p.add_argument("params", nargs="*", help="key=value")
    p.add_argument("--scenario")
    p.add_argument("--id")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--sealed", action="store_true", help="allow the sealed exam's fault types (Codex only)")
    p.set_defaults(fn=cmd_inject)

    p = sub.add_parser("act", parents=[common], help="take one allowlisted action through the adapter")
    p.add_argument("action")
    p.add_argument("target")
    p.add_argument("params", nargs="*", help="key=value, e.g. to=standby")
    p.set_defaults(fn=cmd_act)

    p = sub.add_parser("check", parents=[common], help="the checker's verdict")
    p.add_argument("--window", type=float)
    p.add_argument("--lag", type=float)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("down", parents=[common], help="stop the copy")
    p.set_defaults(fn=cmd_down)

    p = sub.add_parser("hash", parents=[common], help="content hashes of the freeze groups")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_hash)

    for name in ("agent", "demo"):
        p = sub.add_parser(name, parents=[common], help="run the incident commander")
        p.add_argument("--arm", default="abcde")
        p.add_argument("--model")
        p.add_argument("--mode", default="auto", choices=("auto", "confirm", "advise"))
        p.add_argument("--budget", type=float, default=90.0)
        p.set_defaults(fn=cmd_agent)

    sub.add_parser("eval", help="the evaluation harness (Codex): python run.py eval --help")
    sub.add_parser("preflight", help="laptop checks (Codex): python run.py preflight --help")

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, RuntimeError, KeyError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        if type(exc).__name__ != "CallError":
            raise
        print(f"error: the system did not answer ({exc}). Is it up? Try: python run.py up", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
