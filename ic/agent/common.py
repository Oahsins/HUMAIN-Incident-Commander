"""What every arm shares: the clock and budget, the trace, guarded adapter calls and model calls.

Nothing here knows which system it is looking at. Everything system-specific
arrives through the adapter's describe() profile, and every adapter call goes
through the safety wrapper in ic/guard.py.
"""

import time

from ic import llm
from ic.contract import empty_result
from ic.guard import Guard, StepLimit

AGENT_ACTOR = "incident-commander"
SLEEP = time.sleep   # tests replace this to run an incident without waiting


class OutOfTime(Exception):
    """The budget (seconds or adapter calls) cannot cover the next step."""


class Incident:
    """One incident response: the guarded adapter, the budget, the trace and the result being built."""

    def __init__(self, adapter, arm, *, budget_s, max_steps, model, log=None, mode="auto", confirm=None, seed=0,
                 audit_path=None):
        self.arm = arm
        self.model = model
        self.budget_s = budget_s
        self.log = log
        self.seed = seed
        self.t0 = time.time()
        # The harness hands every arm the same Guard, so it sees (and audits) every attempt, refused ones
        # included. Given a bare adapter (tests, a quick script), the incident makes its own.
        if isinstance(adapter, Guard):
            self.guard = adapter
        else:
            self.guard = Guard(adapter, mode=mode, confirm=confirm, max_steps=max_steps, audit_path=audit_path)
        self.mode = self.guard.mode
        self.result = empty_result(arm, mode=self.mode)
        self.result["t_start"] = self.t0
        self.profile = None
        self.components = {}

    # ----- clock -----

    def elapsed(self):
        return time.time() - self.t0

    def remaining(self):
        return self.budget_s - self.elapsed()

    def need(self, seconds):
        """Stop cleanly when the budget cannot cover the next step."""
        if self.remaining() < seconds:
            raise OutOfTime()

    def wait(self, seconds, keep_s=0.0):
        """Sleep, but never into the last keep_s seconds of the budget."""
        seconds = min(seconds, self.remaining() - keep_s)
        if seconds > 0:
            SLEEP(seconds)

    # ----- trace -----

    def note(self, phase, kind, name, summary, **data):
        event = {"t": round(self.elapsed(), 2), "phase": phase, "kind": kind, "name": name, "summary": summary}
        if data:
            event["data"] = data
        self.result["trace"].append(event)
        if self.log:
            try:
                self.log(event)
            except Exception:
                pass
        return event

    # ----- the adapter, through the guard -----

    def tool(self, phase, name, *args, **kwargs):
        started = time.perf_counter()
        try:
            value = getattr(self.guard, name)(*args, **kwargs)
        except StepLimit:
            self.note(phase, "note", "step_limit", f"no adapter calls left ({self.guard.max_steps} used)")
            raise OutOfTime() from None
        self.note(phase, "tool", name, summarize_tool(name, args, kwargs, value),
                  ms=round((time.perf_counter() - started) * 1000, 1))
        return value

    def describe(self):
        if self.profile is None:
            self.profile = self.tool("survey", "describe")
            self.components = {c["name"]: c for c in self.profile.get("components", [])}
        return self.profile

    def allowed(self, action, target):
        return action in (self.components.get(target) or {}).get("actions", [])

    def act(self, phase, action, target, params=None, reason="", name=None):
        """One action through the guard. Advise-mode proposals go to proposed_actions, everything else to actions."""
        record = self.guard.act(action, target, params, reason)
        if record["sent"] and self.result["t_first_action"] is None:
            self.result["t_first_action"] = record["t"]
        if record["refused_reason"] == "advise_mode":
            record = {"order": len(self.result["proposed_actions"]) + 1, **record}
            self.result["proposed_actions"].append(record)
            summary = f"proposed {action} on {target}"
        elif record["sent"]:
            summary = f"{action} {target}: {'done' if record['ok'] else 'failed'} ({record['detail']})"
        else:
            summary = f"did not send {action} on {target}: {record['refused_reason']}"
        if record["refused_reason"] != "advise_mode":
            self.result["actions"].append(record)
        self.note(phase, "action", name or action, summary, target=target, params=record["params"],
                  sent=record["sent"], ok=record["ok"], refused_reason=record["refused_reason"])
        return record

    # ----- the model -----

    def ask(self, phase, purpose, system, messages, schema, effort=None, max_tokens=16000, keep_s=0.0):
        """One model call, with its telemetry kept. Returns the parsed JSON, or None if the call failed."""
        self.need(4.0 + keep_s)
        try:
            answer = llm.complete(messages, system=system, model=self.model, schema=schema, effort=effort,
                                  max_tokens=max_tokens,
                                  timeout=max(4.0, min(60.0, self.remaining() - keep_s - 1.0)), purpose=purpose)
        except llm.ModelError as exc:
            if exc.call:
                self.result["calls"].append(exc.call)
            self.note(phase, "model", purpose, f"model call failed: {exc}")
            return None
        self.result["calls"].append(answer["call"])
        self.note(phase, "model", purpose, f"{answer['call']['model']} answered in {answer['call']['latency_s']} s")
        return answer["json"]

    def declare(self, outcome):
        self.result["outcome"] = outcome
        self.result["t_declared"] = time.time()
        self.note("hand_over", "note", "outcome", outcome)


def summarize_tool(name, args, kwargs, value):
    """One line for the trace."""
    try:
        if name == "observe":
            comps = value.get("components", {})
            down = [n for n, c in comps.items() if c.get("up") is False]
            return f"{len(comps)} components" + (f"; down: {', '.join(down)}" if down else "")
        if name == "probe":
            failing = [s["step"] for s in value.get("steps", []) if not s.get("ok")]
            return f"{value.get('journey')} journey {'ok' if value.get('ok') else 'failed at ' + ', '.join(failing)}"
        if name == "logs":
            return f"{len(value)} log records from {args[0] if args else kwargs.get('component')}"
        if name == "describe":
            return f"{value.get('system')}: {len(value.get('components', []))} components"
    except (AttributeError, IndexError, TypeError):
        pass
    return name
