"""Exercise failed setup, provider selection and the one-call check without an API."""

import importlib.metadata
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import preflight


@pytest.fixture
def laptop(tmp_path, monkeypatch):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "models.json").write_text(json.dumps({
        "default": "anthropic:test", "bulk": None, "swap": "anthropic:other",
    }), encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("psutil==7.2.2\n", encoding="utf-8")
    monkeypatch.setattr(preflight, "ROOT", tmp_path)
    monkeypatch.setattr(preflight.importlib.metadata, "version", lambda name: "1.0")
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda path: SimpleNamespace(free=3 * 1024 ** 3))
    monkeypatch.setattr(preflight, "_busy_ports", lambda ports: [])
    monkeypatch.setattr(preflight, "_lmstudio", lambda: False)
    monkeypatch.delenv("IC_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-test-value")
    return tmp_path


def test_unset_bulk_warns_and_checks_anthropic(laptop, capsys):
    assert preflight.main([]) == 0
    output = capsys.readouterr().out
    assert "bulk is null" in output
    assert "ANTHROPIC_API_KEY is set" in output
    assert "private-test-value" not in output
    assert "LM Studio" in output and "WARN" in output


def test_missing_key_fails_and_skips_live(laptop, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(preflight, "_live", lambda model: pytest.fail("must not call without a key"))
    assert preflight.main(["--live"]) == 1
    output = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY is missing" in output
    assert "no model call made" in output


@pytest.mark.parametrize("override,bulk,key", [
    ("openai:override", "anthropic:bulk", "OPENAI_API_KEY"),
    (None, "openai:bulk", "OPENAI_API_KEY"),
])
def test_eval_provider_priority(laptop, monkeypatch, override, bulk, key):
    (laptop / "configs" / "models.json").write_text(json.dumps({"default": "anthropic:test", "bulk": bulk}), encoding="utf-8")
    if override:
        monkeypatch.setenv("IC_MODEL", override)
    model, rows = preflight._model(laptop)
    assert model == (override or bulk)
    assert any(status == "FAIL" and key in detail for status, _, detail in rows)


@pytest.mark.parametrize("provider", ["mock", "replay", "lmstudio"])
def test_local_providers_need_no_api_key(laptop, monkeypatch, provider):
    monkeypatch.setenv("IC_MODEL", provider + ":test")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert preflight.main([]) == 0


def test_missing_eval_package_is_detected(laptop, monkeypatch, capsys):
    (laptop / "requirements-eval.txt").write_text("matplotlib\n", encoding="utf-8")

    def installed(name):
        if name == "matplotlib":
            raise importlib.metadata.PackageNotFoundError(name)
        return "1.0"

    monkeypatch.setattr(preflight.importlib.metadata, "version", installed)
    assert preflight.main([]) == 1
    assert "matplotlib" in capsys.readouterr().out


def test_all_eval_ports_are_checked(laptop, monkeypatch, capsys):
    checked = []

    def occupied(ports):
        checked.extend(ports)
        return [8309]

    monkeypatch.setattr(preflight, "_busy_ports", occupied)
    assert preflight.main([]) == 1
    assert checked == [base + offset for base in (8100, 8200, 8300) for offset in range(10)]
    assert "Unavailable: 8309" in capsys.readouterr().out


def test_real_listener_is_detected():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert preflight._busy_ports([port]) == [port]
    assert preflight._busy_ports([port]) == []


@pytest.mark.parametrize("free,expected", [(2 * 1024 ** 3 - 1, 1), (2 * 1024 ** 3, 0)])
def test_disk_limit(laptop, monkeypatch, free, expected):
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda path: SimpleNamespace(free=free))
    assert preflight.main([]) == expected


def test_old_python_fails(laptop, monkeypatch):
    monkeypatch.setattr(preflight.sys, "version_info", (3, 10, 9))
    assert preflight.main([]) == 1


def test_live_makes_exactly_one_bounded_call(laptop, monkeypatch, capsys):
    calls = []

    def complete(messages, **kwargs):
        calls.append((messages, kwargs))
        return {"text": "OK\n"}

    monkeypatch.setattr(preflight.importlib, "import_module", lambda name: SimpleNamespace(complete=complete))
    assert preflight.main(["--live"]) == 0
    assert calls == [([{"role": "user", "content": "Reply with the single word OK."}], {
        "model": "anthropic:test", "max_tokens": 1000, "purpose": "preflight", "retries": 0,
    })]
    assert "One call returned OK" in capsys.readouterr().out


def test_live_error_never_prints_provider_body(laptop, monkeypatch, capsys):
    def complete(*args, **kwargs):
        raise RuntimeError("private-test-value provider body")

    monkeypatch.setattr(preflight.importlib, "import_module", lambda name: SimpleNamespace(complete=complete))
    assert preflight.main(["--live"]) == 1
    output = capsys.readouterr().out
    assert "One call failed" in output
    assert "private-test-value" not in output and "provider body" not in output


def test_wrong_live_answer_fails(laptop, monkeypatch):
    monkeypatch.setattr(preflight.importlib, "import_module", lambda name: SimpleNamespace(complete=lambda *args, **kwargs: {"text": "Not OK"}))
    assert preflight.main(["--live"]) == 1


def test_plain_check_does_not_import_model_code(laptop, monkeypatch):
    monkeypatch.setattr(preflight.importlib, "import_module", lambda name: pytest.fail("plain check imported model code"))
    assert preflight.main([]) == 0


def test_runner_works_without_site_packages():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-S", "run.py", "preflight"], cwd=root,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert "Package psutil" in result.stdout and "Missing" in result.stdout
    assert "Traceback" not in result.stderr
