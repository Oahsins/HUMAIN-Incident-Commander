"""The judges' web console: case list, run plans and the API's refusals. Starts no bank."""
import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("console_app", os.path.join(ROOT, "console", "app.py"))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def test_cases_match_the_practice_set():
    with open(app.CASES_FILE, encoding="utf-8") as handle:
        ids = [json.loads(line)["id"] for line in handle if line.strip()]
    cases = app.load_cases()
    assert [c["id"] for c in cases] == ids
    assert all(f["type"] != "benign" for c in cases for f in c["faults"])


def test_plans_only_call_run_py_commands():
    demo = app.plan("demo", "confirm", 27400)
    assert demo == [("run", ["demo", "--port-base", "27400", "--mode", "confirm"])]
    case = app.plan("dev-03", "auto", 27400)
    commands = [step[1][0] for step in case if step[0] in ("run", "quiet")]
    assert commands == ["down", "up", "inject", "agent", "check", "down"]
    assert ["--scenario", "scenarios/dev/dev.jsonl", "--id", "dev-03"] == case[2][1][3:]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.delenv(app.KEY_VAR, raising=False)
    srv = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    srv.app = {"cases": app.load_cases(), "job": None, "port_base": 27400}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", srv
    srv.shutdown()


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_page_and_info(server):
    base, _ = server
    with urllib.request.urlopen(base + "/") as resp:
        assert b"ABCDE Incident Commander" in resp.read()
    with urllib.request.urlopen(base + "/api/info") as resp:
        info = json.loads(resp.read())
    assert info["key_in_env"] is False and len(info["cases"]) == len(app.load_cases())


def test_refuses_what_cannot_run_without_a_key(server):
    base, srv = server
    assert _post(base + "/api/run", {"case": "dev-03", "mode": "auto"})[0] == 400
    assert _post(base + "/api/run", {"case": "demo", "mode": "advise"})[0] == 400
    assert _post(base + "/api/run", {"case": "dev-99", "mode": "auto"})[0] == 400
    assert _post(base + "/api/run", {"case": "demo", "mode": "yolo"})[0] == 400
    assert srv.app["job"] is None


def test_job_runs_notes_and_waits():
    job = app.Job([("say", "hello"), ("wait", 0.1, "short wait")], env=dict(os.environ), label="t", port_base=27400)
    for _ in range(50):
        if job.state != "running":
            break
        threading.Event().wait(0.05)
    assert job.state == "done"
    assert [line["text"] for line in job.lines] == ["hello", "short wait"]
    assert job.env is None   # the key is dropped when the run ends


def test_a_set_runs_each_case_on_a_fresh_bank():
    steps = app.plan_set(["dev-03", "dev-10"], "auto", 27400)
    markers = [step[1] for step in steps if step[0] == "case"]
    assert markers == ["dev-03 (1 of 2)", "dev-10 (2 of 2)"]
    commands = [step[1][0] for step in steps if step[0] in ("run", "quiet")]
    assert commands == ["down", "up", "inject", "agent", "check", "down"] * 2


def test_selftest_runs_pytest_only():
    steps = app.plan_selftest()
    assert [step for step in steps if step[0] == "py"] == [("py", ["-m", "pytest", "-q", "-p", "no:cacheprovider"])]
    assert all(step[0] in ("say", "py") for step in steps)


def test_refuses_sets_it_cannot_run(server, monkeypatch):
    base, srv = server
    assert _post(base + "/api/run", {"cases": ["dev-03"], "mode": "auto"})[0] == 400          # no key
    monkeypatch.setenv(app.KEY_VAR, "test-placeholder")
    assert _post(base + "/api/run", {"cases": ["dev-03"], "mode": "confirm"})[0] == 400       # one at a time
    assert _post(base + "/api/run", {"cases": [], "mode": "auto"})[0] == 400
    assert _post(base + "/api/run", {"cases": ["dev-03", "dev-03"], "mode": "auto"})[0] == 400
    assert _post(base + "/api/run", {"cases": ["dev-03", "demo"], "mode": "auto"})[0] == 400
    assert srv.app["job"] is None


def test_selftest_never_gets_a_model_key(server, monkeypatch):
    base, srv = server
    monkeypatch.setenv(app.KEY_VAR, "test-placeholder")
    monkeypatch.setattr(app, "plan_selftest", lambda: [("say", "stand-in for pytest")])
    assert _post(base + "/api/run", {"selftest": True, "key": "test-placeholder"})[0] == 200
    job = srv.app["job"]
    assert job.meta == {"kind": "selftest"}
    for _ in range(50):
        if job.state != "running":
            break
        threading.Event().wait(0.05)
    assert job.state == "done"


def test_selftest_env_has_no_key(server, monkeypatch):
    base, srv = server
    seen = {}
    monkeypatch.setenv(app.KEY_VAR, "test-placeholder")
    monkeypatch.setenv("IC_ANTHROPIC_API_KEY", "test-placeholder")
    real_job = app.Job

    def spy(steps, env, label, port_base, meta=None):
        seen.update(env)
        return real_job([("say", "stand-in")], env, label, port_base, meta)

    monkeypatch.setattr(app, "Job", spy)
    assert _post(base + "/api/run", {"selftest": True})[0] == 200
    assert app.KEY_VAR not in seen and "IC_ANTHROPIC_API_KEY" not in seen
