"""The shared vocabulary in ic/contract.py, and the bank's use of it, agree."""

from ic import contract, inject
from targets.bank import spec
from targets.bank.platform import Platform


def test_the_bank_offers_exactly_the_six_actions():
    assert set(spec.ACTIONS) == set(contract.ACTIONS)


def test_every_bank_component_uses_the_shared_kinds_and_actions():
    for component in spec.EXTRA_SERVICE_COMPONENTS:   # every component, notifications included
        assert component["kind"] in contract.COMPONENT_KINDS, component["name"]
        assert set(component["actions"]) <= set(contract.ACTIONS), component["name"]


def test_only_components_with_a_standby_can_fail_over():
    for component in spec.EXTRA_SERVICE_COMPONENTS:
        assert ("failover" in component["actions"]) == bool(component.get("standby")), component["name"]


def test_practice_fault_classes_are_in_the_vocabulary():
    for name in inject.available("bank"):
        module = inject.load("bank", name)
        assert module.TYPE == name
        assert set(module.CLASSES) <= set(contract.ROOT_CAUSE_CLASSES), name


def test_sealed_fault_types_need_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(inject, "fault_path", lambda system, fault_type, folder: str(tmp_path / folder / f"{fault_type}.py"))
    (tmp_path / "heldout").mkdir()
    (tmp_path / "heldout" / "secret.py").write_text("TYPE = 'secret'\n")
    try:
        inject.load("bank", "secret")
    except PermissionError:
        pass
    else:
        raise AssertionError("a sealed fault type loaded without allow_sealed")
    assert inject.load("bank", "secret", allow_sealed=True).TYPE == "secret"


def test_the_bank_implements_every_condition_and_refuses_others():
    assert set(Platform.conditions) == set(contract.CONDITIONS)
    try:
        Platform(port_base=8990, condition="no_such_condition").start()
    except ValueError:
        pass
    else:
        raise AssertionError("a condition the bank does not implement must be refused before anything starts")


def test_empty_result_has_the_documented_fields():
    result = contract.empty_result("abcde", mode="confirm")
    for key in ("arm", "mode", "outcome", "actions", "proposed_actions", "trace", "calls", "escalation"):
        assert key in result, key
    assert result["mode"] == "confirm"


def test_recording_creates_its_folder(tmp_path, monkeypatch):
    from ic import llm
    llm.register_mock("ok", lambda system, messages, schema, purpose: "OK")
    path = tmp_path / "replays" / "demo.jsonl"   # a fresh clone has no replays/ folder
    monkeypatch.setenv("IC_RECORD", str(path))
    assert llm.complete([{"role": "user", "content": "Reply with the single word OK."}], model="mock:ok")["text"] == "OK"
    assert path.exists() and len(path.read_text(encoding="utf-8").splitlines()) == 1
