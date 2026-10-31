"""Fast checks on the dispatch centre's definition, with no processes (docs/DISPATCH.md).

describe() keeps the contract; kinds, ports, settings, actions, contacts and the Release API are as DISPATCH.md
gives them; the code that runs inside the centre's processes, and every string describe() shows, avoid the
reserved words; no file uses the word the repo's vocabulary rule bans; no log line carries a caller's number,
words or location; and Session A's folder, targets/dispatch/faults, stays outside the content scans. Before
reveal git tracks none of its files; after reveal its tracked inventory and hashes match the latest transfer seal.
"""

import ast
import hashlib
import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from ic import contract
from ic.kit.conformance import check_profile
from targets.bank import spec as bank_spec
from targets.dispatch import spec, worker

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DISPATCH = os.path.join(ROOT, "targets", "dispatch")
SESSION_A = os.path.join(DISPATCH, "faults")   # Session A may keep its own files there: every scan skips it

# Whole words, case ignored, with "_" separating words too (so poison_message counts and "example" does not).
RESERVED = re.compile(r"(?<![a-z0-9])(fault|faults|inject|sealed|heldout|exam|poison|stale|chaos)(?![a-z0-9])",
                      re.I)
BANNED_WORD = re.compile("pat" + "ient", re.I)   # built in two parts, so this file does not use it
PRIVATE_FIELDS = {"ani", "narrative", "location", "x", "y"}
SIX_KINDS = {"service", "worker", "dependency", "external", "datastore", "job"}

# Inventory: port offset, kind, image, release, depends on, actions, standby, impact weight.
INVENTORY = {
    "call-handling": (0, "service", "call_handling", "5.2", ["call-network", "cad"],
                      ["restart", "rollback", "revert_config"], None, 1.0),
    "cad": (1, "service", "cad", "3.4", ["cad-db"], ["restart", "rollback", "revert_config"], None, 1.0),
    "dispatcher": (2, "worker", "dispatcher", "2.1", ["cad-db", "alerting"],
                   ["restart", "rollback", "revert_config"], None, 1.0),
    "alerting": (3, "dependency", "alerting", "1.6", [], ["restart", "failover"], "alerting-backup", 1.0),
    "alerting-backup": (4, "dependency", "alerting", "1.6", [], ["restart"], None, 0.0),
    "unit-sync": (5, "worker", "unit_sync", "4.0", ["cad-db"],
                  ["restart", "rollback", "revert_config", "quarantine"], None, 0.6),
    "call-network": (6, "external", "call_network", "1.0", [], [], None, 0.5),
    "cad-db": (None, "datastore", None, None, [], ["release_lock"], None, 1.0),
    "incident-archive": (None, "job", None, None, ["cad-db"], [], None, 0.0),
}
LINKS = {"dispatcher->alerting": 7, "call-handling->call-network": 8}
START_ORDER = ["call-network", "alerting", "alerting-backup", "cad", "unit-sync", "dispatcher", "call-handling"]

# Settings: each setting's default and its usable values, as the release's SETTINGS schema writes them.
SETTINGS = {
    "call-handling": {"positions": (14, ("int", 1, 64)), "rollover_s": (2.5, ("num", 0, 10)),
                      "ali_timeout_s": (0.5, ("num", 0, 5)), "cad_timeout_s": (1.0, ("num", 0, 5))},
    "cad": {"repeat_match": ("ani_open", ("enum", ("ani_open", "off"))),
            "write_timeout_ms": (1000, ("int", 1, 10000))},
    "dispatcher": {"poll_interval_s": (0.2, ("num", 0, 60)), "batch_size": (20, ("int", 1, 10000)),
                   "ack_timeout_s": (2.0, ("num", 0, 60)), "alert_timeout_s": (1.0, ("num", 0, 10)),
                   "recommend_by": ("closest", ("enum", ("closest", "station_order")))},
    "unit-sync": {"poll_interval_s": (0.2, ("num", 0, 60)), "batch_size": (200, ("int", 1, 10000)),
                  "max_message_age_s": (10.0, ("num", 0, 3600))},
    "alerting": {}, "alerting-backup": {}, "call-network": {},
}

# What describe() shows beyond the inventory.
CAPABILITIES = {"probe": True, "act": True, "changes": True, "baseline": "warmup", "max_mode": "auto",
                "min_window_s": 2}
SLO = {"success_rate": 0.99, "p95_ms": 1000}
FORBIDDEN = ["close or cancel an incident", "change a call's priority",
             "stand down or reassign a unit committed to an incident", "contact a caller"]
CONTACTS = [{"role": "shift supervisor", "for": ["call-handling", "dispatcher"]},
            {"role": "CAD administrator", "for": ["cad", "cad-db", "unit-sync", "incident-archive"]},
            {"role": "radio and alerting technician", "for": ["alerting", "alerting-backup"]},
            {"role": "call network provider", "for": ["call-network"]}]
ADAPTED = {   # the two action descriptions written for dispatch; everything else is the bank's
    "restart": "restart the component's process; work in progress is dropped: on call-handling, calls being "
               "answered are cut off and the callers must redial",
    "quarantine": "set one queued field report aside so unit-sync skips it; the unit's next report repeats "
                  "its state",
}

# Releases: every release in the repository, each with the release it is a build label of.
RELEASES = {"call_handling": {"5.2": None, "5.2.1": "5.2"}, "cad": {"3.4": None, "3.4.1": "3.4"},
            "dispatcher": {"2.1": None, "2.1.1": "2.1"}, "unit_sync": {"4.0": None, "4.0.1": "4.0"},
            "alerting": {"1.6": None, "1.6.1": "1.6"}, "call_network": {"1.0": None}}
ALL_RELEASES = [(image, release, base) for image, releases in RELEASES.items()
                for release, base in releases.items()]
# The Release API, frozen: a rename needs a new row in docs/DISPATCH.md.
RELEASE_API = {
    "call_handling": "routes() dial(request) take_position(call) lookup_location(ani) report(request) "
                     "enter_incident(call, body) release_position(call) background() extra_metrics(window_s)",
    "cad": "routes() validate_call(body) find_call(conn, call_id) find_open_incident(conn, ani, test) "
           "create_incident(conn, call) link_call(conn, incident_id, call) create_call(request) mdt(request) "
           "extra_metrics(window_s)",
    "dispatcher": "cycle(conn, settings) retry_alerts(conn, settings) expire_unacknowledged(conn, settings) "
                  "pending_batch(conn, settings) free_units(conn, incident) recommend(incident, units, settings) "
                  "assign(conn, incident, unit) send_alert(conn, assignment, settings)",
    "unit_sync": "cycle(conn, settings) take_batch(conn, settings) parse(item) in_order(msg) "
                 "apply(conn, item, msg, settings, latest) apply_unit(conn, msg) apply_assignment(conn, msg)",
    "alerting": "routes() alert(request) deliver(alert)",
    "call_network": "routes() ali(request) locate(ani)",
}
WORKER_API = "background() run_loop() wait(seconds) db() write_error() extra_metrics(window_s)"


def profile(tmp_path):
    """describe() as the agent gets it; it needs only the condition from the supervisor."""
    return spec.Spec().describe(SimpleNamespace(condition="default", data_dir=str(tmp_path)))


def module(image, release):
    return importlib.import_module(f"targets.dispatch.releases.{image}.v{release.replace('.', '_')}")


def release_path(image, release):
    return os.path.join(DISPATCH, "releases", image, f"v{release.replace('.', '_')}.py")


def methods(api):
    """[(name, [parameter, ...])] from "name(a, b) other()"."""
    return [(name, [p.strip() for p in params.split(",") if p.strip()])
            for name, params in re.findall(r"(\w+)\(([^)]*)\)", api)]


def parameters(function):
    return list(inspect.signature(function).parameters)[1:]   # without self


def normal(rule):
    """A settings rule with its named choices in a fixed order, to compare."""
    if rule is None:
        return None
    return ("enum", tuple(sorted(rule[1]))) if rule[0] == "enum" else tuple(rule)


def files_under(folder):
    """Every file under folder, leaving out __pycache__ and never entering targets/dispatch/faults."""
    skipped = os.path.normcase(SESSION_A)
    for top, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs
                         if d != "__pycache__" and os.path.normcase(os.path.join(top, d)) != skipped)
        yield from (os.path.join(top, name) for name in sorted(names))


def read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def relative(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings_in(key)
            yield from strings_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings_in(item)


# ----- the profile, kinds and ports -----

def test_describe_keeps_the_contract(tmp_path):
    found = profile(tmp_path)
    assert check_profile(found) == []
    json.dumps(found)   # plain JSON data
    assert (found["system"], found["contract_version"]) == ("dispatch", contract.CONTRACT_VERSION)
    assert (found["capabilities"], found["slo"]) == (CAPABILITIES, SLO)
    assert [(j["name"], j["default"], j["entry"], j["slo"]) for j in found["journeys"]] == \
        [("emergency_call", True, "call-handling", SLO)]
    assert [c["name"] for c in found["components"]] == list(INVENTORY)
    for c in found["components"]:
        assert set(c) == {"name", "kind", "depends_on", "impact_weight", "actions", "description", "standby"}
        assert isinstance(c["description"], str) and c["description"], c["name"]


def test_every_kind_is_a_contract_kind_and_all_six_are_used():
    kinds = {c["kind"] for c in spec.COMPONENTS}
    assert kinds <= set(contract.COMPONENT_KINDS)
    assert kinds == SIX_KINDS


def test_process_and_relay_offsets_are_unique_and_within_0_to_8():
    processes = {c["name"]: c["port_offset"] for c in spec.COMPONENTS if c["port_offset"] is not None}
    offsets = [*processes.values(), *(link["listen_offset"] for link in spec.LINKS.values())]
    assert all(type(offset) is int and 0 <= offset <= 8 for offset in offsets), offsets
    assert len(set(offsets)) == len(offsets), offsets
    for route, link in spec.LINKS.items():
        caller, upstream = route.split("->")
        assert caller in processes and upstream == link["upstream"] and upstream in processes, route
    assert sorted(spec.START_ORDER) == sorted(processes)


def test_the_inventory_is_as_specified():
    found = {c["name"]: (c["port_offset"], c["kind"], c.get("image"), c["version"], c["depends_on"], c["actions"],
                         c.get("standby"), c["impact_weight"]) for c in spec.COMPONENTS}
    assert found == INVENTORY
    assert {route: link["listen_offset"] for route, link in spec.LINKS.items()} == LINKS
    assert spec.START_ORDER == START_ORDER and spec.Spec().start_order("default") == START_ORDER


# ----- settings -----

def test_every_setting_is_a_number_or_a_named_choice():
    """Never true or false. The datastore and the job have no settings at all."""
    for c in spec.COMPONENTS:
        if c["kind"] in ("datastore", "job"):
            assert c["config"] is None, c["name"]
            continue
        for key, value in c["config"].items():
            assert isinstance(value, (int, float, str)) and not isinstance(value, bool), f"{c['name']} {key}"


def test_every_default_is_usable_under_its_release_schema():
    for c in spec.COMPONENTS:
        if c["config"] is None:
            continue
        schema = getattr(module(c["image"], c["version"]).Release, "SETTINGS", {})
        assert set(schema) == set(c["config"]), c["name"]
        assert worker.check_settings(c["config"], schema)[1] is None, c["name"]
        for key, rule in schema.items():
            assert rule[0] in ("num", "int", "enum"), f"{c['name']} {key}"
            assert (rule[0] == "enum") == isinstance(c["config"][key], str), f"{c['name']} {key}"
            assert worker.check_settings({**c["config"], key: True}, schema) == (None, key), f"{c['name']} {key}"


def test_settings_and_their_usable_values_are_as_specified():
    assert {c["name"] for c in spec.COMPONENTS if c["config"] is not None} == set(SETTINGS)
    for c in spec.COMPONENTS:
        if c["config"] is None:
            continue
        schema = getattr(module(c["image"], c["version"]).Release, "SETTINGS", {})
        assert {key: (value, normal(schema.get(key))) for key, value in c["config"].items()} == \
            {key: (default, normal(rule)) for key, (default, rule) in SETTINGS[c["name"]].items()}, c["name"]


# ----- actions, contacts and the lines the agent must not cross -----

def test_actions_stay_within_the_six_and_where_they_belong(tmp_path):
    names = {c["name"] for c in spec.COMPONENTS}
    for c in spec.COMPONENTS:
        assert set(c["actions"]) <= set(contract.ACTIONS), c["name"]
        if "failover" in c["actions"]:
            assert c.get("standby") in names, c["name"]
    assert [c["name"] for c in spec.COMPONENTS if "quarantine" in c["actions"]] == ["unit-sync"]
    offered = profile(tmp_path)["actions"]
    assert set(offered) == set(contract.ACTIONS)
    for action, entry in offered.items():   # the bank's dict, with two descriptions written for dispatch
        bank = bank_spec.ACTIONS[action]
        assert {**entry, "description": None} == {**bank, "description": None}, action
        assert entry["description"] == ADAPTED.get(action, bank["description"]), action


def test_each_component_has_one_contact_and_the_forbidden_lines_are_the_four(tmp_path):
    found = profile(tmp_path)
    covered = [name for contact in found["escalation_contacts"] for name in contact["for"]]
    assert sorted(covered) == sorted(c["name"] for c in spec.COMPONENTS)   # each exactly once
    assert found["escalation_contacts"] == CONTACTS
    assert found["forbidden"] == FORBIDDEN


# ----- releases and the Release API -----

@pytest.mark.parametrize("image,release,base", ALL_RELEASES, ids=[f"{i}-{r}" for i, r, _ in ALL_RELEASES])
def test_every_release_file_and_release_api_method_exists(image, release, base):
    assert os.path.isfile(release_path(image, release)), relative(release_path(image, release))
    cls = module(image, release).Release
    for name, params in methods(RELEASE_API[image]):
        assert callable(getattr(cls, name, None)), f"{image} {release}: no {name}()"
        assert parameters(getattr(cls, name)) == params, f"{image} {release}: {name}() takes other parameters"
    if base is not None:   # a build label: its base under a new number, with nothing changed
        assert cls.__bases__ == (module(image, base).Release,) and cls.__doc__ == "build label"
        assert [key for key in vars(cls) if not key.startswith("__")] == []


def test_the_shared_worker_loop_keeps_its_api():
    for name, params in methods(WORKER_API):
        assert parameters(getattr(worker.Worker, name)) == params, name
    for image in ("dispatcher", "unit_sync"):
        for release in RELEASES[image]:
            assert issubclass(module(image, release).Release, worker.Worker), (image, release)


def test_the_repository_holds_only_the_specified_releases():
    """No other release under releases/: a ready-made release that turns on a checker count would be a
    practice fault, and the repository holds none."""
    assert os.path.isfile(os.path.join(DISPATCH, "releases", "__init__.py"))
    for image in RELEASES:
        assert os.path.isfile(os.path.join(DISPATCH, "releases", image, "__init__.py")), image
    known = {os.path.normcase(release_path(image, release)) for image, release, _ in ALL_RELEASES}
    other = [relative(path) for path in files_under(os.path.join(DISPATCH, "releases"))
             if re.fullmatch(r"v\d+(_\d+)+\.py", os.path.basename(path)) and os.path.normcase(path) not in known]
    assert other == []


# ----- words -----

def component_code():
    """The files whose lines and paths can show in a crash traceback: every release, the job, and the shared
    modules they import. platform.py, checker.py, control.py, people.py and surge.py never show to the agent."""
    named = [os.path.join(DISPATCH, name) for name in ("worker.py", "cadstore.py", "fieldmsg.py", "area.py")]
    assert [relative(path) for path in named if not os.path.isfile(path)] == []
    return [*named, *files_under(os.path.join(DISPATCH, "releases")), *files_under(os.path.join(DISPATCH, "jobs"))]


def test_no_reserved_word_in_code_that_runs_inside_the_centre():
    found = []
    for path in component_code():
        if RESERVED.search(relative(path)):
            found.append(f"{relative(path)}: in the file's path")
        found += [f"{relative(path)}:{number}: {line.strip()}"
                  for number, line in enumerate(read(path).splitlines(), 1) if RESERVED.search(line)]
    assert found == [], "\n".join(found)


def test_no_reserved_word_in_the_code_whose_text_the_agent_reads():
    """spec.py writes what observe, probe and act return, and adapter.py serves them."""
    found = [f"{relative(path)}:{number}: {line.strip()}"
             for path in (os.path.join(DISPATCH, "spec.py"), os.path.join(DISPATCH, "adapter.py"))
             for number, line in enumerate(read(path).splitlines(), 1) if RESERVED.search(line)]
    assert found == [], "\n".join(found)


def test_no_reserved_word_in_what_describe_shows(tmp_path):
    assert [text for text in strings_in(profile(tmp_path)) if RESERVED.search(text)] == []


def test_no_file_uses_the_word_the_vocabulary_rule_bans():
    """People on a call are callers."""
    paths = [*files_under(DISPATCH), *files_under(os.path.join(ROOT, "tests", "dispatch"))]
    if os.path.isfile(os.path.join(ROOT, "docs", "DISPATCH.md")):
        paths.append(os.path.join(ROOT, "docs", "DISPATCH.md"))
    found = [relative(path) for path in paths if BANNED_WORD.search(relative(path))]
    found += [f"{relative(path)}:{number}" for path in paths
              for number, line in enumerate(read(path).splitlines(), 1) if BANNED_WORD.search(line)]
    assert found == [], "\n".join(found)


# ----- logs -----

def log_calls(tree):
    """Calls that write a log line: self.log_every(...), self.crash(...), print(...), and info, warn, warning,
    error or write on a log (self.log.info(...))."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in ("print", "log_every"):
                yield node
        elif isinstance(func, ast.Attribute):
            owner = func.value.id if isinstance(func.value, ast.Name) else getattr(func.value, "attr", None)
            if func.attr in ("log_every", "crash") or (
                    func.attr in ("info", "warn", "warning", "error", "write") and owner in ("log", "logger")):
                yield node


def read_by(node):
    """The name a value is read by: ani, call.ani, call["ani"] or call.get("ani")."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value
    if (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "get" and node.args
            and isinstance(node.args[0], ast.Constant)):
        return node.args[0].value
    return None


def private_fields(call):
    """The private fields a log call passes: as keywords, in a **{...} or **dict(...), or inside f-string text."""
    names = set()
    for keyword in call.keywords:
        if keyword.arg is not None:
            names.add(keyword.arg)
        elif isinstance(keyword.value, ast.Dict):
            names |= {key.value for key in keyword.value.keys if isinstance(key, ast.Constant)}
        elif isinstance(keyword.value, ast.Call) and getattr(keyword.value.func, "id", None) == "dict":
            names |= {k.arg for k in keyword.value.keywords}
    for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
        for part in ast.walk(argument):
            if isinstance(part, ast.FormattedValue):
                names |= {read_by(node) for node in ast.walk(part.value)}
    return PRIVATE_FIELDS & names


def test_no_log_line_carries_a_callers_number_words_or_location():
    found, calls = [], 0
    for path in files_under(DISPATCH):
        if path.endswith(".py"):
            for call in log_calls(ast.parse(read(path), filename=path)):
                calls += 1
                fields = private_fields(call)
                if fields:
                    found.append(f"{relative(path)}:{call.lineno}: {sorted(fields)}")
    assert calls > 20 and found == [], "\n".join(found)


# ----- Session A's folder -----

def test_git_tracked_faults_match_the_latest_transfer_seal():
    """Before reveal nothing is tracked; afterwards only the latest sealed files and bytes are allowed."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    try:
        done = subprocess.run([git, "ls-files", "-z", "--", "targets/dispatch/faults"], cwd=ROOT, capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git could not run")
    if done.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = set(filter(None, done.stdout.split("\0")))
    if not tracked:
        return
    with open(os.path.join(ROOT, "scenarios", "transfer", "SEALED.json"), encoding="utf-8") as handle:
        files = json.load(handle)["seals"][-1]["files"]
    expected = {path: digest for path, digest in files.items() if path.startswith("targets/dispatch/faults/")}
    assert tracked == set(expected)
    for path in sorted(tracked):
        with open(os.path.join(ROOT, path), "rb") as handle:
            data = handle.read()
        actual = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
        assert actual == expected[path], path
