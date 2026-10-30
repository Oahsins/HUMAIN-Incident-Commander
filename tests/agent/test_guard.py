"""The safety wrapper decides what reaches the system, whatever the model asks for."""

import json

import pytest

from ic.guard import Guard, StepLimit, redact
from ic.kit.net import CallError
from tests.agent.fake_system import FakeSystem


def test_only_listed_actions_on_listed_components():
    fake = FakeSystem()
    guard = Guard(fake)
    for action, target in (("restart", "partner"), ("delete_everything", "web"), ("restart", "nowhere")):
        record = guard.act(action, target)
        assert not record["sent"] and record["refused_reason"] == "not_allowlisted"
    assert fake.acts == []


def test_rate_limits():
    fake = FakeSystem()
    guard = Guard(fake, max_repeats=2, max_actions=3)
    assert guard.act("restart", "web")["sent"]
    assert guard.act("restart", "web")["sent"]
    assert guard.act("restart", "web")["refused_reason"] == "rate_limited"   # same action, same target, third time
    assert guard.act("rollback", "web")["sent"]
    assert guard.act("release_lock", "db")["refused_reason"] == "rate_limited"   # 3 actions per incident
    assert len(fake.acts) == 3


def test_step_limit():
    guard = Guard(FakeSystem(), max_steps=2)
    guard.describe()
    guard.observe(5.0)
    with pytest.raises(StepLimit):
        guard.probe()
    assert guard.act("restart", "web")["refused_reason"] == "step_limit"


def test_advise_and_dry_run_never_send():
    for guard in (Guard(FakeSystem(), mode="advise"), Guard(FakeSystem(), dry_run=True)):
        record = guard.act("restart", "web")
        assert record["refused_reason"] == "advise_mode" and not record["sent"]
        assert guard.adapter.acts == []


def test_confirm_mode():
    with pytest.raises(ValueError):
        Guard(FakeSystem(), mode="confirm")
    asked = []
    guard = Guard(FakeSystem(), mode="confirm", confirm=lambda record: asked.append(record) or record["target"] == "db")
    declined = guard.act("restart", "web")
    assert declined["declined"] and declined["refused_reason"] == "declined" and not declined["sent"]
    assert guard.act("release_lock", "db")["sent"]
    assert [r["target"] for r in asked] == ["web", "db"]


def test_redaction():
    text = ("Authorization: Bearer abcdef1234567890 api_key=sk-live-1234567890abcdef user ali@example.com "
            "account SA4420000001234567891234 card 4111111111111111")
    masked = redact(text)
    for secret in ("abcdef1234567890", "sk-live", "ali@example.com", "SA4420000001234567891234", "4111111111111111"):
        assert secret not in masked


def test_logs_are_redacted():
    class Leaky(FakeSystem):
        def logs(self, component, since_s=60.0, limit=200):
            return [{"t": 1.0, "level": "ERROR", "component": component, "msg": "retry with token=hunter2secret"}]
    assert "hunter2secret" not in json.dumps(Guard(Leaky()).logs("web"))


def test_audit_file(tmp_path):
    path = tmp_path / "runs" / "audit" / "run-case-arm.jsonl"   # the folder does not exist yet
    guard = Guard(FakeSystem(), audit_path=str(path))
    guard.act("restart", "web")
    guard.act("restart", "partner")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(e["action"], e["sent"]) for e in lines] == [("restart", True), ("restart", False)]
    assert lines == guard.audit


def test_a_read_that_cannot_reach_the_system_is_audited_then_raised(tmp_path):
    class Unreachable(FakeSystem):
        def observe(self, window_s=10.0):
            raise CallError("timeout", detail="no answer within 10.0s")
    path = tmp_path / "audit.jsonl"
    guard = Guard(Unreachable(), audit_path=str(path))
    guard.describe()
    with pytest.raises(CallError):
        guard.observe(5.0)
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert (line["event"], line["call"], line["kind"]) == ("read_error", "observe", "timeout")
    assert "no answer" in line["detail"] and guard.steps == 2   # the failed read still used its step
