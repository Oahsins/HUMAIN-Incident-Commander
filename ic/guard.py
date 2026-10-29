"""The safety wrapper between the agent and a system's adapter (docs/CONTRACT.md).

Every arm talks to the system through a Guard, never through the adapter
directly. The guard, not the model, decides what may be sent:

- allowlist: only the six actions, and only on a component whose profile lists
  that action. Anything else is refused as not_allowlisted (the only refusal
  that counts as a harmful attempt).
- rate limits: at most GUARD_MAX_ACTIONS actions per incident, and the same
  action on the same component at most GUARD_MAX_REPEATS times.
- steps: every adapter call is one step; after max_steps, reads raise
  StepLimit and actions are refused as step_limit.
- modes: auto sends; confirm asks a person first (declined when they say no);
  advise never sends and keeps the action as a proposal. dry_run is advise
  mode for tests and rehearsals.
- audit: one line per decision, in memory and, when audit_path is given, in a
  JSON Lines file.
- redaction: log text the model will read has secrets and personal data
  masked first.

Nothing here knows which system it is guarding.
"""

import json
import re
import time

from ic.contract import ACTIONS, AGENT_MAX_STEPS, GUARD_MAX_ACTIONS, GUARD_MAX_REPEATS, MODES


class StepLimit(Exception):
    """The incident used every adapter call it was allowed."""


_REDACTIONS = [
    (re.compile(r"(?i)\b(bearer)\s+[a-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\b(\s*[=:]\s*)[^\s,;\"']+"), r"\1\2[redacted]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{10,}"), "[redacted key]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "[account]"),          # IBAN-shaped account numbers
    (re.compile(r"\b\d{13,19}\b"), "[number]"),                              # card-length digit runs
]


def redact(text):
    """Mask secrets and personal data in one string."""
    if not isinstance(text, str):
        return text
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value):
    """redact() applied to every string inside a JSON-like value."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    return value


class Guard:
    """Wraps an adapter for one incident. Same five methods, with the rules above."""

    def __init__(self, adapter, *, mode="auto", confirm=None, max_steps=AGENT_MAX_STEPS,
                 max_actions=GUARD_MAX_ACTIONS, max_repeats=GUARD_MAX_REPEATS, dry_run=False, audit_path=None,
                 on_step=None, clock=time.time):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        if mode == "confirm" and confirm is None:
            raise ValueError("confirm mode needs a confirm(record) -> bool callback")
        self.adapter = adapter
        self.mode = "advise" if dry_run else mode
        self.confirm = confirm
        self.max_steps = max_steps
        self.max_actions = max_actions
        self.max_repeats = max_repeats
        self.audit_path = audit_path
        self.on_step = on_step
        self.clock = clock
        self.steps = 0
        self.sent = 0
        self.repeats = {}
        self.audit = []
        self.profile = None
        self.allowed_actions = {}

    # ----- reads -----

    def _step(self, name):
        if self.steps >= self.max_steps:
            self._audit({"event": "step_limit", "call": name})
            raise StepLimit(f"used all {self.max_steps} adapter calls")
        self.steps += 1
        if self.on_step:
            self.on_step(name, self.steps)

    def describe(self):
        if self.profile is None:
            self._step("describe")
            self.profile = self.adapter.describe()
            self.allowed_actions = {c["name"]: set(c.get("actions") or []) & set(ACTIONS)
                                    for c in self.profile.get("components", [])}
        return self.profile

    def observe(self, window_s=10.0):
        self._step("observe")
        return self.adapter.observe(window_s)

    def logs(self, component, since_s=60.0, limit=200):
        self._step("logs")
        return redact_value(self.adapter.logs(component, since_s, limit))

    def probe(self, journey=None):
        self._step("probe")
        return self.adapter.probe(journey)

    # ----- actions -----

    def check(self, action, target):
        """None when the action may be sent now, else the refused_reason."""
        if self.profile is None:
            self.describe()
        if action not in ACTIONS or action not in self.allowed_actions.get(target, set()):
            return "not_allowlisted"
        if self.sent >= self.max_actions or self.repeats.get((action, target), 0) >= self.max_repeats:
            return "rate_limited"
        if self.steps >= self.max_steps:
            return "step_limit"
        return None

    def act(self, action, target, params=None, reason=""):
        """Send one action if the rules allow it. Returns the action record (CONTRACT.md section 9)."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        record = {"t": self.clock(), "action": action, "target": target, "params": params, "reason": reason,
                  "sent": False, "ok": None, "refused": False, "refused_reason": None, "declined": False,
                  "detail": ""}
        why = self.check(action, target)
        if why:
            record.update(ok=False, refused=True, refused_reason=why,
                          detail={"not_allowlisted": f"{action} is not allowed on {target}",
                                  "rate_limited": "action limit reached for this incident",
                                  "step_limit": "no adapter calls left in this incident"}[why])
        elif self.mode == "advise":
            record.update(refused_reason="advise_mode", detail="advise mode: proposed, not taken")
        elif self.mode == "confirm" and not self.confirm(dict(record)):
            record.update(declined=True, refused_reason="declined", detail="a person declined this action")
        else:
            self._step("act")
            self.sent += 1
            self.repeats[(action, target)] = self.repeats.get((action, target), 0) + 1
            record["t"] = self.clock()
            answer = self.adapter.act(action, target, params)
            record.update(sent=True, ok=bool(answer.get("ok")), refused=bool(answer.get("refused")),
                          detail=answer.get("detail", ""))
        self._audit({"event": "act", **record})
        return record

    def _audit(self, entry):
        entry = {"t": self.clock(), **entry} if "t" not in entry else entry
        self.audit.append(entry)
        if self.audit_path:
            with open(self.audit_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
