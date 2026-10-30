"""The mitigation mean must keep its censoring evidence beside the value."""

from eval.presentation import results_tables, strata_section


def test_mitigation_mean_has_censored_counts_and_wilson_interval_beside_it():
    arm = {"name": "runbook", "means": {
        "time_to_mitigate_s": {"n": 10, "mean": 35, "low": 20, "high": 50}},
        "rates": {"mitigation_censored": {
            "n": 2, "N": 10, "estimate": .2, "low": .057, "high": .51}}}
    lines = results_tables([arm], lambda item: item, "Cases with a value")
    row = next(line for line in lines if line.startswith("| Time to mitigate"))
    assert "35.0 s; censored 2/10 (20%; Wilson 95% 6%–51%)" in row
    assert "20.0 s–50.0 s" in row


def test_missing_mitigation_censor_status_is_not_printed_as_zero():
    arm = {"name": "runbook", "means": {
        "time_to_mitigate_s": {"n": 1, "mean": 35, "low": 35, "high": 35}}}
    row = next(line for line in results_tables([arm], lambda item: item, "Cases")
               if line.startswith("| Time to mitigate"))
    assert "censored not reported" in row
    assert "censored 0/" not in row


def test_single_stratum_label_includes_healthy_cases():
    text = "\n".join(strata_section([{"name": "runbook", "strata": {"single": {"n": 1}}}]))
    assert "Single-fault and healthy cases" in text
