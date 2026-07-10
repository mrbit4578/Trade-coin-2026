"""Bayesian win-rate tracker for dynamic position scaling."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BayesianWinRate:
    """Beta-Binomial posterior for win probability."""

    alpha: float = 8.0  # prior ~ as if 7 wins
    beta: float = 8.0  # prior ~ as if 7 losses (mean 0.5)

    def update(self, won: bool) -> None:
        if won:
            self.alpha += 1
        else:
            self.beta += 1

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def n_obs(self) -> float:
        return self.alpha + self.beta - 16  # subtract prior pseudo-counts roughly

    def credible_interval(self, z: float = 1.96) -> tuple[float, float]:
        # Normal approx on Beta
        import math

        a, b = self.alpha, self.beta
        mean = a / (a + b)
        var = a * b / ((a + b) ** 2 * (a + b + 1))
        sd = math.sqrt(max(var, 1e-12))
        return max(0.01, mean - z * sd), min(0.99, mean + z * sd)

    def size_multiplier(self) -> float:
        """Scale size up when posterior win rate is high and confident."""
        lo, hi = self.credible_interval()
        width = hi - lo
        conf = max(0.0, 1.0 - width / 0.5)
        # mean 0.5 → 1.0x; 0.75 → ~1.4x; 0.35 → ~0.6x
        mult = 0.5 + self.mean
        return float(max(0.25, min(1.5, mult * (0.6 + 0.4 * conf))))
