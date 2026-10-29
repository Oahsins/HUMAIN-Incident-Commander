"""Small, reproducible statistical calculations for the registered analysis.

All intervals are 95%. Binary rates use Wilson intervals; paired differences
resample whole pairs. The signed-rank test uses the exact random-sign
distribution, including tied ranks, and drops zero differences.
"""

import math
import random
from collections import Counter

Z95 = 1.959963984540054


def wilson(n, total):
    """Return Wilson's lower and upper bounds, or (None, None) for no data."""
    if not isinstance(n, int) or not isinstance(total, int) or not 0 <= n <= total:
        raise ValueError("counts must be integers with 0 <= n <= total")
    if total == 0:
        return None, None
    share = n / total
    scale = 1 + Z95 ** 2 / total
    centre = (share + Z95 ** 2 / (2 * total)) / scale
    width = Z95 * math.sqrt(share * (1 - share) / total + Z95 ** 2 / (4 * total ** 2)) / scale
    return max(0.0, centre - width), min(1.0, centre + width)


def rate(n, total):
    """Keep the numerator and denominator beside every reported rate."""
    low, high = wilson(n, total)
    return {"n": n, "N": total, "rate": n / total if total else None,
            "low": low, "high": high}


def exact_mcnemar(b, c):
    """Two-sided binomial McNemar p: b favours the left arm, c the right."""
    if not isinstance(b, int) or not isinstance(c, int) or min(b, c) < 0:
        raise ValueError("discordant counts must be non-negative integers")
    discordant = b + c
    if not discordant:
        return 1.0
    return min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(b, c) + 1))
               / 2 ** discordant)


def holm(p_values):
    """Adjust one named family; unavailable tests still occupy their slots."""
    for value in p_values.values():
        if value is not None and not 0 <= value <= 1:
            raise ValueError("p values must be in [0, 1] or None")
    ordered = sorted(((name, p) for name, p in p_values.items() if p is not None),
                     key=lambda pair: pair[1])
    adjusted = {name: None for name in p_values}
    largest = 0.0
    for index, (name, p) in enumerate(ordered):
        largest = max(largest, (len(p_values) - index) * p)
        adjusted[name] = min(1.0, largest)
    return adjusted


def _numbers(values):
    values = [float(value) for value in values]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("observations must be finite")
    return values


def _quantile(sorted_values, fraction):
    position = (len(sorted_values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (position - lower) * (sorted_values[upper] - sorted_values[lower])


def bootstrap_mean(values, *, resamples=10000, seed=0):
    """Percentile interval for a mean; missing observations must be removed explicitly."""
    values = _numbers(values)
    if resamples < 1:
        raise ValueError("resamples must be positive")
    n = len(values)
    result = {"n": n, "mean": sum(values) / n if n else None,
              "low": None, "high": None, "resamples": resamples, "seed": seed}
    if not n:
        return result
    if min(values) == max(values):
        result.update(low=values[0], high=values[0])
        return result
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    result.update(low=_quantile(means, 0.025), high=_quantile(means, 0.975))
    return result


def paired_bootstrap(left, right, *, resamples=10000, seed=0):
    """Resample left-minus-right differences, preserving each original pair."""
    left, right = _numbers(left), _numbers(right)
    if len(left) != len(right):
        raise ValueError("paired observations must have equal lengths")
    result = bootstrap_mean([a - b for a, b in zip(left, right)], resamples=resamples, seed=seed)
    result["difference"] = result.pop("mean")
    return result


def paired_comparison(left, right):
    """Exact McNemar counts and the registered paired-bootstrap interval."""
    left, right = list(left), list(right)
    if len(left) != len(right) or any(value not in (True, False, 0, 1) for value in left + right):
        raise ValueError("paired binary outcomes are required")
    b = sum(bool(a) and not bool(c) for a, c in zip(left, right))
    c = sum(not bool(a) and bool(c) for a, c in zip(left, right))
    return {**paired_bootstrap(left, right), "b": b, "c": c,
            "p": exact_mcnemar(b, c) if left else None}


def wilcoxon(left, right):
    """Exact two-sided signed-rank test; ties use average ranks and zeros are dropped.

    Doubled ranks are integers. A short dynamic programme counts every possible
    random-sign sum without enumerating all 2**n sign assignments.
    """
    left, right = _numbers(left), _numbers(right)
    if len(left) != len(right):
        raise ValueError("paired observations must have equal lengths")
    differences = [a - b for a, b in zip(left, right) if a != b]
    result = {"n": len(left), "n_nonzero": len(differences), "statistic": 0.0,
              "p": 1.0 if left else None, "method": "exact sign permutation; zero differences dropped"}
    if not differences:
        return result
    ordered = sorted(enumerate(differences), key=lambda pair: abs(pair[1]))
    doubled = [0] * len(differences)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and abs(ordered[end][1]) == abs(ordered[index][1]):
            end += 1
        for original, _ in ordered[index:end]:
            doubled[original] = index + 1 + end
        index = end
    positive = sum(rank for rank, delta in zip(doubled, differences) if delta > 0)
    total = sum(doubled)
    counts = Counter({0: 1})
    for rank in doubled:
        next_counts = counts.copy()
        for value, frequency in counts.items():
            next_counts[value + rank] += frequency
        counts = next_counts
    tail = min(positive, total - positive)
    p = min(1.0, 2 * sum(frequency for value, frequency in counts.items() if value <= tail)
            / 2 ** len(differences))
    result.update(statistic=min(positive, total - positive) / 2, p=p)
    return result
