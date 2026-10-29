"""The checker's own rules, independent of any running bank."""

import json

from targets.bank import checker

GOOD = {"payment_id": "p-1", "end_to_end_id": "e-1", "amount_minor": 1500, "currency": "SAR",
        "beneficiary_bank": "BANK2", "beneficiary_acct": "SA0000000000000000000001"}


def test_a_well_formed_item_is_not_poison():
    assert not checker.is_poison(json.dumps(GOOD))


def test_malformed_items_are_poison():
    assert checker.is_poison("{not json")
    for key in ("payment_id", "end_to_end_id", "beneficiary_bank", "beneficiary_acct", "amount_minor", "currency"):
        broken = dict(GOOD)
        del broken[key]
        assert checker.is_poison(json.dumps(broken)), key
    for amount in (0, -5, 12.5, True, "100"):
        assert checker.is_poison(json.dumps({**GOOD, "amount_minor": amount})), amount
    assert checker.is_poison(json.dumps({**GOOD, "currency": "XXX"}))


def test_allowed_p95_follows_the_baseline_within_the_slo():
    assert checker.p95_allowed({"p95_ms": 20}) == 270.0
    assert checker.p95_allowed({"p95_ms": 400}) == 800.0
    assert checker.p95_allowed({"p95_ms": 900}) == 1000.0
