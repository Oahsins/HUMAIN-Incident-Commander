"""Settings history and routing: undoing one setting must never undo another change, or a failover."""

import time

from ic.kit.store import CachedRouting, ConfigStore, Routing

AGENT = "incident-commander"


def test_revert_by_key_restores_only_that_key(tmp_path):
    store = ConfigStore(tmp_path, "payments")
    store.init({"limit": 100, "timeout": 1.0})
    store.set("limit", 5, "operator")
    store.set("timeout", 2.0, "pipeline")
    undone = store.revert(AGENT, key="limit")
    assert undone == {"key": "limit", "from": 5, "to": 100, "changed_by": "operator"}
    assert store.load()["values"] == {"limit": 100, "timeout": 2.0}


def test_revert_without_key_skips_the_agents_own_changes(tmp_path):
    store = ConfigStore(tmp_path, "payments")
    store.init({"limit": 100, "timeout": 1.0})
    store.set("limit", 5, "operator")
    store.set("timeout", 3.0, AGENT)
    undone = store.revert(AGENT, skip_actor=AGENT)
    assert undone["key"] == "limit"
    assert store.load()["values"] == {"limit": 100, "timeout": 3.0}


def test_a_revert_is_never_itself_reverted(tmp_path):
    store = ConfigStore(tmp_path, "payments")
    store.init({"limit": 100})
    store.set("limit", 5, "operator")
    assert store.revert(AGENT, skip_actor=AGENT) is not None
    assert store.revert(AGENT, skip_actor=AGENT) is None
    assert store.load()["values"] == {"limit": 100}


def test_every_change_bumps_the_version_and_keeps_history(tmp_path):
    store = ConfigStore(tmp_path, "clearing")
    store.init({"batch_size": 50})
    store.set("batch_size", 0, "operator")
    store.revert(AGENT, key="batch_size")
    doc = store.load()
    assert doc["version"] == 3
    assert [h.get("revert", False) for h in doc["history"]] == [False, True]
    assert doc["history"][0]["undone"] is True


def test_routing_is_separate_from_settings(tmp_path):
    store = ConfigStore(tmp_path, "payments")
    store.init({"limit": 100})
    routing = Routing(tmp_path)
    assert routing.active("screening") == "primary"
    routing.set("screening", "standby")
    store.set("limit", 5, "operator")
    store.revert(AGENT, skip_actor=AGENT)
    assert routing.active("screening") == "standby"


def test_cached_routing_sees_a_failover_within_a_fraction_of_a_second(tmp_path):
    cached = CachedRouting(tmp_path)
    assert cached.active("screening") == "primary"
    Routing(tmp_path).set("screening", "standby")
    time.sleep(0.25)
    assert cached.active("screening") == "standby"
