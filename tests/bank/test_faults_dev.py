"""Every practice fault injects through Control only and labels itself correctly (no running bank needed)."""

import json
import os
import random

import pytest

from ic import contract, inject


class FakeControl:
    """Records Control calls; answers the way a healthy bank would."""

    def __init__(self, data_dir):
        self.data_dir = str(data_dir)
        self.calls = []

    def paths(self):
        return {"data_dir": self.data_dir}

    def spawn(self, name, argv):
        self.calls.append(("spawn", name, argv))
        if "--hold-lock" in argv:
            with open(os.path.join(self.data_dir, "ledger_locks.json"), "w", encoding="utf-8") as handle:
                json.dump({"holders": [{"pid": 4242, "session": name}]}, handle)
        return 4242

    def __getattr__(self, name):
        if name not in ("kill", "stop", "start", "deploy", "set_config", "link"):
            raise AttributeError(f"a fault plugin called Control.{name}, which the fake does not know")

        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return True
        return call


CASES = [
    ("crash", {"target": "payments"}),
    ("crash", {}),
    ("bad_update", {}),
    ("unrecorded_payments", {}),
    ("bad_setting", {"variant": "transfer_limit"}),
    ("bad_setting", {"variant": "screening_timeout"}),
    ("bad_setting", {"variant": "clearing_batch"}),
    ("bad_setting", {"target": "gateway", "key": "payments_timeout_s", "value": 0.01}),
    ("locked_ledger", {"hold_s": 30}),
    ("stopped_worker", {}),
    ("slow_screening", {}),
    ("noise", {}),
    ("network_outage", {}),
    ("benign", {}),
]


@pytest.mark.parametrize("fault_type,params", CASES)
def test_fault_injects_through_control_and_labels_itself(tmp_path, fault_type, params):
    control = FakeControl(tmp_path)
    module = inject.load("bank", fault_type)
    entry = module.inject(control, dict(params), random.Random(1))
    assert control.calls, "the fault changed nothing"
    assert entry["type"] == fault_type
    if module.CLASSES:
        assert entry["class"] in module.CLASSES
        assert entry["class"] in contract.ROOT_CAUSE_CLASSES
        assert entry["target"]
    else:
        assert entry["class"] is None and entry["target"] is None


def test_actors_come_from_the_pool(tmp_path):
    seen = set()
    for seed in range(20):
        control = FakeControl(tmp_path)
        inject.load("bank", "bad_setting").inject(control, {"variant": "transfer_limit"}, random.Random(seed))
        seen.add(control.calls[0][2]["actor"])
    assert seen <= {"pipeline", "operator", "ops-maintenance", "scheduler"}
    assert len(seen) > 1


def test_one_seed_gives_the_same_case(tmp_path):
    def run(seed):
        control = FakeControl(tmp_path)
        manifest = inject.apply("bank", control, [{"type": "benign", "at_s": 0, "params": {}},
                                                   {"type": "crash", "at_s": 0, "params": {}}], seed=seed)
        return [(e["type"], e["target"], json.dumps(e["detail"], sort_keys=True)) for e in manifest]
    assert run(3) == run(3)
