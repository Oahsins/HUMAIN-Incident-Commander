"""The shared vocabulary in ic/contract.py, and the bank's use of it, agree."""

from ic import contract, inject
from targets.bank import spec
from targets.bank.platform import Platform


def test_the_bank_offers_exactly_the_six_actions():
    assert set(spec.ACTIONS) == set(contract.ACTIONS)


def test_every_bank_component_uses_the_shared_kinds_and_actions():
    for component in spec.COMPONENTS:
        assert component["kind"] in contract.COMPONENT_KINDS, component["name"]
        assert set(component["actions"]) <= set(contract.ACTIONS), component["name"]


def test_only_components_with_a_standby_can_fail_over():
    for component in spec.COMPONENTS:
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


def test_the_bank_refuses_conditions_it_does_not_implement():
    assert set(Platform.conditions) <= set(contract.CONDITIONS)
    try:
        Platform(port_base=8990, condition="extra_service").start()
    except ValueError:
        pass
    else:
        raise AssertionError("extra_service should be refused until the bank implements it")


def test_empty_result_has_the_documented_fields():
    result = contract.empty_result("abcde", mode="confirm")
    for key in ("arm", "mode", "outcome", "actions", "proposed_actions", "trace", "calls", "escalation"):
        assert key in result, key
    assert result["mode"] == "confirm"
