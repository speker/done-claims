"""Proportion intervals and stratified odds ratios, standard library only."""

import math
from collections.abc import Iterable
from dataclasses import dataclass

Z95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= successes <= n:
        raise ValueError("successes must be between 0 and n")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    low = 0.0 if successes == 0 else centre - half
    high = 1.0 if successes == n else centre + half
    return low, high


@dataclass(frozen=True)
class Table:
    """2x2 counts. a, b: exposed with and without the event. c, d: unexposed with and without it."""

    a: int
    b: int
    c: int
    d: int

    @property
    def n(self) -> int:
        return self.a + self.b + self.c + self.d


@dataclass(frozen=True)
class StratifiedOddsRatio:
    estimate: float
    low: float
    high: float
    informative_strata: int


def mantel_haenszel(tables: Iterable[Table], z: float = Z95) -> StratifiedOddsRatio:
    """Mantel-Haenszel odds ratio with the Robins-Breslow-Greenland variance of its log."""
    sum_r = sum_s = 0.0
    sum_pr = sum_ps_qr = sum_qs = 0.0
    informative = 0
    for t in tables:
        if t.n == 0:
            continue
        r = t.a * t.d / t.n
        s = t.b * t.c / t.n
        if r == 0 and s == 0:
            continue
        p = (t.a + t.d) / t.n
        q = (t.b + t.c) / t.n
        sum_r += r
        sum_s += s
        sum_pr += p * r
        sum_ps_qr += p * s + q * r
        sum_qs += q * s
        informative += 1
    if sum_r == 0 or sum_s == 0:
        raise ValueError("odds ratio is undefined: no discordant information across strata")
    estimate = sum_r / sum_s
    variance = sum_pr / (2 * sum_r**2) + sum_ps_qr / (2 * sum_r * sum_s) + sum_qs / (2 * sum_s**2)
    spread = z * math.sqrt(variance)
    log_or = math.log(estimate)
    return StratifiedOddsRatio(estimate, math.exp(log_or - spread), math.exp(log_or + spread), informative)
