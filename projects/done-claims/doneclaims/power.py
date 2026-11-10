"""Choose the number of extra attempts for phase 2b stage 2 by simulating it from stage-1 trials.

Usage, from projects/done-claims:
  uv run python -m doneclaims.power TRIALS_CSV [--odds-ratio 0.68] [--simulations 300] [--seed 20261108]
TRIALS_CSV is the trials.csv that doneclaims.harbor wrote for stage 1. Only completed trials count.

Stage 2 adds k attempts to every issue with at least one unverified stage-1 attempt. The primary estimate
is the within-issue Mantel-Haenszel odds ratio of unverified against ran_passing over those issues, both
stages pooled. Each simulation keeps the observed stage-1 rows and draws the k new attempts per issue:
- categories from the issue's Dirichlet posterior, with a Dirichlet-multinomial prior fitted to all issues;
- ran_passing outcomes from the issue's beta posterior, with a beta-binomial prior fitted to ran_failing
  and ran_passing trials of all issues;
- unverified outcomes from the same issue with its odds multiplied by --odds-ratio.
The chosen k is the smallest even k from 2 to 12 for which at least 90% of simulations give an interval
with upper/estimate at most 1.5; if none does, k is 12.
"""

import argparse
import csv
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .stats import Table, mantel_haenszel

CATEGORIES = ("unverified", "ran_failing", "ran_passing", "no_product_change")
K_VALUES = (2, 4, 6, 8, 10, 12)
TARGET_HALF_WIDTH = 1.5
TARGET_SHARE = 0.9


@dataclass
class Issue:
    counts: list[int]
    unverified: list[bool]
    passing: list[bool]
    ran_resolved: int
    ran_failed: int


def load(path: Path) -> dict[str, Issue]:
    issues: dict[str, Issue] = defaultdict(lambda: Issue([0] * len(CATEGORIES), [], [], 0, 0))
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["status"] != "completed" or row["category"] not in CATEGORIES:
                continue
            issue = issues[row["instance_id"]]
            resolved = row["target"] == "True"
            issue.counts[CATEGORIES.index(row["category"])] += 1
            if row["category"] == "unverified":
                issue.unverified.append(resolved)
            elif row["category"] == "ran_passing":
                issue.passing.append(resolved)
            if row["category"] in ("ran_failing", "ran_passing"):
                issue.ran_resolved += resolved
                issue.ran_failed += not resolved
    return dict(issues)


def _dirichlet_multinomial_loglik(issues: list[Issue], shares: list[float], concentration: float) -> float:
    alpha = [concentration * s for s in shares]
    total = 0.0
    for issue in issues:
        n = sum(issue.counts)
        total += math.lgamma(concentration) - math.lgamma(concentration + n)
        total += sum(math.lgamma(a + c) - math.lgamma(a) for a, c in zip(alpha, issue.counts, strict=True))
    return total


def fit_categories(issues: list[Issue]) -> list[float]:
    """Dirichlet prior over category shares: pooled shares, concentration by maximum likelihood on a grid."""
    totals = [sum(i.counts[c] for i in issues) for c in range(len(CATEGORIES))]
    shares = [max(t, 0.5) / (sum(totals) + 0.5 * len(totals)) for t in totals]
    grid = [0.25 * 1.15**j for j in range(60)]
    concentration = max(grid, key=lambda k: _dirichlet_multinomial_loglik(issues, shares, k))
    return [concentration * s for s in shares]


def _beta_binomial_loglik(issues: list[Issue], a: float, b: float) -> float:
    total = 0.0
    for issue in issues:
        s, f = issue.ran_resolved, issue.ran_failed
        total += math.lgamma(a + s) + math.lgamma(b + f) - math.lgamma(a + b + s + f)
        total -= math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    return total


def fit_resolution(issues: list[Issue]) -> tuple[float, float]:
    """Beta prior over each issue's resolution rate on ran_failing and ran_passing trials."""
    means = [0.02 * j for j in range(1, 50)]
    sizes = [0.1 * 1.2**j for j in range(40)]
    return max(
        ((m * n, (1 - m) * n) for m in means for n in sizes),
        key=lambda ab: _beta_binomial_loglik(issues, *ab),
    )


def _dirichlet(rng: random.Random, alpha: list[float]) -> list[float]:
    draws = [rng.gammavariate(a, 1.0) for a in alpha]
    total = sum(draws)
    return [d / total for d in draws]


def _with_odds(p: float, odds_ratio: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    odds = p / (1 - p) * odds_ratio
    return odds / (1 + odds)


def _table(unverified: list[bool], passing: list[bool]) -> Table:
    a = sum(unverified)
    c = sum(passing)
    return Table(a, len(unverified) - a, c, len(passing) - c)


def simulate(
    issues: dict[str, Issue], k: int, odds_ratio: float, simulations: int, seed: int
) -> list[tuple[float, float, float, int] | None]:
    """One (estimate, low, high, informative strata) per simulation; None when the estimate is undefined."""
    pool = list(issues.values())
    prior = fit_categories(pool)
    a, b = fit_resolution(pool)
    selected = [issues[name] for name in sorted(issues) if issues[name].counts[0] > 0]
    rng = random.Random(seed)
    results: list[tuple[float, float, float, int] | None] = []
    for _ in range(simulations):
        tables = []
        for issue in selected:
            shares = _dirichlet(rng, [p + c for p, c in zip(prior, issue.counts, strict=True)])
            p_pass = rng.betavariate(a + issue.ran_resolved, b + issue.ran_failed)
            p_unverified = _with_odds(p_pass, odds_ratio)
            unverified, passing = list(issue.unverified), list(issue.passing)
            for _ in range(k):
                category = rng.choices(CATEGORIES, weights=shares)[0]
                if category == "unverified":
                    unverified.append(rng.random() < p_unverified)
                elif category == "ran_passing":
                    passing.append(rng.random() < p_pass)
            tables.append(_table(unverified, passing))
        try:
            result = mantel_haenszel(tables)
        except ValueError:
            results.append(None)
            continue
        results.append((result.estimate, result.low, result.high, result.informative_strata))
    return results


def summarise(results: list[tuple[float, float, float, int] | None]) -> dict[str, float]:
    defined = [r for r in results if r is not None]
    n = len(results)
    half_widths = sorted(r[2] / r[0] for r in defined)
    strata = sorted(r[3] for r in defined)
    return {
        "within_target": sum(r[2] / r[0] <= TARGET_HALF_WIDTH for r in defined) / n,
        "upper_below_one": sum(r[2] < 1 for r in defined) / n,
        "median_half_width": half_widths[len(half_widths) // 2] if half_widths else math.inf,
        "median_strata": strata[len(strata) // 2] if strata else 0,
        "undefined": (n - len(defined)) / n,
    }


def choose_k(table: dict[int, dict[str, float]]) -> int:
    for k in K_VALUES:
        if table[k]["within_target"] >= TARGET_SHARE:
            return k
    return K_VALUES[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Choose k for phase 2b stage 2 by simulation")
    parser.add_argument("trials", type=Path)
    parser.add_argument("--odds-ratio", type=float, default=0.68)
    parser.add_argument("--simulations", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20261108)
    args = parser.parse_args()

    issues = load(args.trials)
    selected = sum(1 for i in issues.values() if i.counts[0] > 0)
    print(f"issues: {len(issues)}; with at least one unverified attempt: {selected}")
    table = {
        k: summarise(simulate(issues, k, args.odds_ratio, args.simulations, args.seed + k)) for k in K_VALUES
    }
    print(
        f"{'k':>3}{'trials':>8}{'P(upper/OR<=1.5)':>18}{'P(upper<1)':>12}{'median upper/OR':>17}{'strata':>8}"
    )
    for k, row in table.items():
        print(
            f"{k:>3}{k * selected:>8}{row['within_target']:>18.2f}{row['upper_below_one']:>12.2f}"
            f"{row['median_half_width']:>17.2f}{row['median_strata']:>8}"
        )
    print(f"chosen k: {choose_k(table)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
