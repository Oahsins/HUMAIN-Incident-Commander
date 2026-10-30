"""The ABCDE survey on the fake system: what counts as a fault, what is only information."""

import copy

from ic.agent import survey
from tests.agent.fake_system import PROFILE, FakeSystem


def _survey(fake):
    return survey.survey(PROFILE, fake.observe(8.0), fake.probe())


def _faults(found, component=None):
    return [f for f in survey.faults(found["findings"]) if component is None or f["component"] == component]


def test_healthy_system_has_no_faults():
    found = _survey(FakeSystem())
    assert _faults(found) == []
    assert found["components_checked"] == len(PROFILE["components"])
    assert not found["journey_down"]


def test_every_finding_has_an_id_and_a_letter():
    found = _survey(FakeSystem({"web_down", "db_locked", "partner_down"}))
    ids = [f["id"] for f in found["findings"]]
    assert len(ids) == len(set(ids))
    assert all(f["id"][0] == f["letter"] and f["letter"] in survey.LETTERS for f in found["findings"])


def test_down_component_is_a_capacity_fault():
    found = _survey(FakeSystem({"web_down"}))
    assert any(f["letter"] == "C" and f["text"].startswith("down") for f in _faults(found, "web"))
    assert found["journey_down"]


def test_external_outage_is_a_dependency_fault():
    found = _survey(FakeSystem({"partner_down"}))
    own = [f for f in _faults(found, "partner") if "journey fails" not in f["text"]]   # the probe's finding is A
    assert {f["letter"] for f in own} == {"D"}
    assert any(f["text"].startswith("down") for f in own)
    assert any("run by another organisation" in f["text"] for f in own)


def test_lock_is_a_bottleneck_fault():
    found = _survey(FakeSystem({"db_locked"}))
    assert any(f["letter"] == "B" and "lock held by session" in f["text"] for f in _faults(found, "db"))


def test_recent_config_change_is_an_event():
    found = _survey(FakeSystem({"web_bad_config"}))
    assert any(f["letter"] == "E" and "config by operator" in f["text"] for f in found["findings"])


def test_lost_traffic_counts_only_where_users_arrive():
    fake = FakeSystem()
    obs = fake.observe(8.0)
    obs["components"]["web"]["rps"] = 2.0       # the journey's entry
    obs["components"]["db"]["rps"] = 2.0        # further in: its callers send less
    obs["baseline"]["db"]["rps"] = 10.0
    found = survey.survey(PROFILE, obs, fake.probe())
    assert any("traffic" in f["text"] for f in _faults(found, "web"))
    assert not any("traffic" in f["text"] for f in _faults(found, "db"))
    assert any("traffic" in f["text"] and f["severity"] == "info" for f in found["findings"] if f["component"] == "db")


def test_entry_points_default_to_components_nothing_depends_on():
    profile = copy.deepcopy(PROFILE)
    profile["journeys"] = []
    fake = FakeSystem()
    obs = fake.observe(8.0)
    obs["components"]["web"]["rps"] = 2.0
    found = survey.survey(profile, obs, fake.probe())
    assert any("traffic" in f["text"] for f in _faults(found, "web"))


def test_containment_only_when_the_journey_cannot_start():
    fake = FakeSystem({"cache_slow"})
    obs, probe = fake.observe(8.0), fake.probe()
    found = survey.survey(PROFILE, obs, probe)
    assert survey.containment_candidate(PROFILE, obs, probe, found["findings"])[0] == "cache"
    fake.act("failover", "cache", {"to": "standby"})
    obs, probe = fake.observe(8.0), fake.probe()
    found = survey.survey(PROFILE, obs, probe)
    assert survey.containment_candidate(PROFILE, obs, probe, found["findings"]) is None
    assert _faults(found) == []     # the primary's lost traffic is expected once it has moved to its standby
    # a fault deeper in the journey is not a reason to contain
    fake = FakeSystem({"partner_down"})
    obs, probe = fake.observe(8.0), fake.probe()
    assert survey.containment_candidate(PROFILE, obs, probe, survey.survey(PROFILE, obs, probe)["findings"]) is None


def test_table_lists_every_letter():
    text = survey.table(_survey(FakeSystem({"db_locked"}))["findings"])
    for letter, name in survey.LETTER_NAMES.items():
        assert f"{letter} {name}:" in text
