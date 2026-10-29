"""The demo picks a model it can actually run: with no key it replays a recorded run, or says what to set."""

import pytest

from ic import demo


def test_needs_a_key_or_a_replay(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("IC_MODEL", raising=False)
    monkeypatch.setattr(demo, "ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        demo.usable_model("anthropic:claude-opus-5-5", demo=True)      # an explicit model is never swapped
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "models.json").write_text('{"default": "anthropic:claude-opus-5-5"}', encoding="utf-8")
    with pytest.raises(ValueError):
        demo.usable_model(None, demo=True)                              # no recorded run yet
    (tmp_path / "replays").mkdir()
    (tmp_path / "replays" / "demo-frozen.jsonl").write_text("", encoding="utf-8")
    assert demo.usable_model(None, demo=True).startswith("replay:")
    with pytest.raises(ValueError):
        demo.usable_model(None, demo=False)                             # `agent` never replays by itself
    assert demo.usable_model("mock:rules", demo=False) == "mock:rules"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    assert demo.usable_model(None, demo=True) == "anthropic:claude-opus-5-5"
