"""Aggregate metrics and the statistics behind the comparisons."""

import math
import random
from collections import defaultdict


def bootstrap_ci(hits: list[bool], n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap over items."""
    n = len(hits)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    vals = [1.0 if h else 0.0 for h in hits]
    means = sorted(sum(rng.choices(vals, k=n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[min(n_boot - 1, int(0.975 * n_boot))]


def paired_bootstrap(
    a: list[bool], b: list[bool], n_boot: int = 2000, seed: int = 0
) -> tuple[float, float, float]:
    """(mean difference b - a, ci_low, ci_high), resampling the same items for both models."""
    if len(a) != len(b):
        raise ValueError("paired comparison needs the same items")
    n = len(a)
    diffs = [int(y) - int(x) for x, y in zip(a, b, strict=True)]
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(n_boot))
    return sum(diffs) / n, means[int(0.025 * n_boot)], means[min(n_boot - 1, int(0.975 * n_boot))]


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


def summarize(rows: list[dict]) -> dict:
    """rows are prediction records as written by eval.run; endpoint failures are counted apart."""
    scored = [r for r in rows if r["status"] != "endpoint_error"]
    hits = [r["ok"] for r in scored]
    n = len(scored)
    by_diff: dict[str, list[bool]] = defaultdict(list)
    for r in scored:
        by_diff[r["difficulty"]].append(r["ok"])
    errors = defaultdict(int)
    for r in scored:
        if not r["ok"]:
            errors[r["failure"]] += 1
    lat = [r["latency_s"] for r in scored]
    lo, hi = bootstrap_ci(hits)

    def rate(pred) -> float:
        return sum(1 for r in scored if pred(r)) / n if n else 0.0

    return {
        "n": n,
        "endpoint_errors": len(rows) - n,
        "ex": sum(hits) / n if n else 0.0,
        "ex_ci": [lo, hi],
        "ex_strict": rate(lambda r: r["ok_strict"]),
        "valid_sql_rate": rate(lambda r: r["executed"]),
        "dialect_error_rate": rate(lambda r: r["failure"] == "DIALECT"),
        "schema_link_error_rate": rate(lambda r: r["failure"] == "SCHEMA_LINK"),
        "by_difficulty": {
            k: {"n": len(v), "ex": sum(v) / len(v)} for k, v in sorted(by_diff.items())
        },
        "errors": dict(sorted(errors.items())),
        "latency_p50_s": percentile(lat, 0.5),
        "latency_p95_s": percentile(lat, 0.95),
        "mean_completion_tokens": sum(r["completion_tokens"] for r in scored) / n if n else 0.0,
    }
