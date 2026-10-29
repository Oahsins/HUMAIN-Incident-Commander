"""Numerical fixtures for the pre-registered statistics; no scenario files."""

import itertools

import pytest

from eval.stats import (bootstrap_mean, exact_mcnemar, holm, paired_bootstrap,
                        paired_comparison, rate, wilcoxon, wilson)


def test_wilson_eight_of_ten_and_empty():
    low, high = wilson(8, 10)
    assert low == pytest.approx(0.490162, abs=1e-6)
    assert high == pytest.approx(0.943318, abs=1e-6)
    assert rate(0, 0) == {"n": 0, "N": 0, "rate": None, "low": None, "high": None}
    assert wilson(0, 10)[0] == pytest.approx(0)
    assert wilson(10, 10)[1] == pytest.approx(1)


@pytest.mark.parametrize("counts", [(-1, 10), (11, 10), (1.0, 10), (0, -1)])
def test_wilson_rejects_invalid_counts(counts):
    with pytest.raises(ValueError):
        wilson(*counts)


def test_exact_mcnemar_registered_example_and_symmetry():
    assert exact_mcnemar(1, 7) == 0.0703125
    assert exact_mcnemar(7, 1) == 0.0703125
    assert exact_mcnemar(0, 0) == 1
    assert exact_mcnemar(0, 6) == 0.03125


def test_holm_one_family_and_unavailable_comparison():
    assert holm({"a": 0.01, "b": 0.03, "c": 0.04, "d": 0.2}) == {
        "a": 0.04, "b": 0.09, "c": 0.09, "d": 0.2}
    assert holm({"a": 0.01, "b": None}) == {"a": 0.02, "b": None}


def test_bootstrap_preserves_pairs_and_is_reproducible():
    paired = paired_bootstrap([2, 3, 7], [1, 2, 6])
    assert paired["difference"] == paired["low"] == paired["high"] == 1
    first = bootstrap_mean([1, 2, 8, 9])
    assert first == bootstrap_mean([1, 2, 8, 9])
    assert first["resamples"] == 10000 and first["seed"] == 0
    assert first["low"] <= first["mean"] <= first["high"]


def test_paired_comparison_retains_ties_in_denominator():
    result = paired_comparison([1, 1, 0, 0], [1, 0, 1, 0])
    assert (result["n"], result["b"], result["c"], result["p"]) == (4, 1, 1, 1)
    assert result["difference"] == 0


def test_wilcoxon_exact_known_examples():
    result = wilcoxon([1, 2, 3, 4, 5], [0] * 5)
    assert result["p"] == 0.0625
    assert result["statistic"] == 0
    assert wilcoxon([2, 2], [2, 2])["p"] == 1
    assert wilcoxon([], [])["p"] is None


def test_wilcoxon_ties_matches_enumeration_and_drops_zero():
    # Absolute differences 1, 1, 2 have doubled average ranks 3, 3, 6.
    result = wilcoxon([1, -1, 2, 0], [0, 0, 0, 0])
    sums = [sum(rank for rank, sign in zip((3, 3, 6), signs) if sign)
            for signs in itertools.product((False, True), repeat=3)]
    expected = 2 * sum(value <= 3 for value in sums) / len(sums)
    assert result["p"] == min(1, expected)
    assert result["n"] == 4 and result["n_nonzero"] == 3


def test_paired_length_and_nonfinite_values_rejected():
    with pytest.raises(ValueError):
        paired_bootstrap([1], [])
    with pytest.raises(ValueError):
        wilcoxon([1], [])
    with pytest.raises(ValueError):
        bootstrap_mean([float("nan")])
