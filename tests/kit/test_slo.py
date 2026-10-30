from ic.kit.slo import time_to_mitigate


def test_no_missed_bucket_means_nothing_to_mitigate():
    assert time_to_mitigate({}, 110) == (0.0, False)
    assert time_to_mitigate({0: True, 1: True}, 110) == (0.0, False)


def test_mitigation_starts_after_the_last_missed_bucket():
    met = {i: True for i in range(22)}
    met.update({0: False, 1: False, 4: False})
    assert time_to_mitigate(met, 110) == (25.0, False)


def test_a_missed_last_bucket_is_censored_at_the_whole_span():
    met = {i: i < 20 for i in range(24)}
    assert time_to_mitigate(met, 117.43) == (117.4, True)
    # the short last bucket of a span that is not a multiple of 5 counts like any other
    assert time_to_mitigate({**{i: True for i in range(23)}, 23: False}, 117.43) == (117.4, True)
    assert time_to_mitigate({**{i: True for i in range(23)}, 22: False, 23: True}, 117.43) == (115.0, False)


def test_a_quiet_bucket_keeps_the_state_before_it():
    assert time_to_mitigate({0: False, 2: True}, 15) == (10.0, False)
    assert time_to_mitigate({0: False}, 15) == (15.0, True)      # quiet ever after: never shown to be mitigated
    assert time_to_mitigate({1: False, 2: True}, 15) == (10.0, False)   # quiet before any journey counts as met


def test_an_empty_span_has_nothing_to_mitigate():
    assert time_to_mitigate({}, 0) == (0.0, False)
    assert time_to_mitigate({}, -3) == (0.0, False)
