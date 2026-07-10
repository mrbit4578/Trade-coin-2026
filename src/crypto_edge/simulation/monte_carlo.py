"""
10,000-path Monte Carlo engine per trade candidate.

Models short-horizon log-returns with:
- realized vol from price history
- orderbook imbalance drift
- OTC bias drift
- structure score drift
- fat tails (Student-t mix)
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from crypto_edge.models import MonteCarloResult, StructureSignal


class MonteCarloEngine:
    def __init__(self, n_sims: int = 10_000, seed: int | None = None) -> None:
        self.n_sims = n_sims
        self.rng = np.random.default_rng(seed)

    def run(
        self,
        prices: Sequence[float],
        market_yes_prob: float = 0.5,
        imbalance: float = 0.0,
        otc_bias: float = 0.0,
        structure: Optional[StructureSignal] = None,
        horizon_steps: int = 24,
    ) -> MonteCarloResult:
        arr = np.asarray(prices, dtype=float)
        if len(arr) < 5:
            # uninformative prior
            return MonteCarloResult(
                n_sims=self.n_sims,
                p_up=0.5,
                p_down=0.5,
                expected_move_pct=0.0,
                var_95=0.0,
                cvar_95=0.0,
                p_win_yes=market_yes_prob,
                p_win_no=1 - market_yes_prob,
                edge_vs_market=0.0,
            )

        rets = np.diff(np.log(arr[-min(len(arr), 200) :]))
        mu = float(np.mean(rets)) if len(rets) else 0.0
        sigma = float(np.std(rets)) if len(rets) else 0.01
        sigma = max(sigma, 1e-5)

        # Drift overlays
        drift = mu
        drift += imbalance * sigma * 0.35
        drift += otc_bias * sigma * 0.25
        if structure:
            drift += structure.score * sigma * 0.4

        # Fat-tail shocks: 85% normal + 15% student-t scaled
        n = self.n_sims
        steps = horizon_steps
        z_n = self.rng.normal(0, 1, size=(n, steps))
        z_t = self.rng.standard_t(df=5, size=(n, steps)) / np.sqrt(5 / 3)
        mix = self.rng.random((n, steps)) < 0.85
        shocks = np.where(mix, z_n, z_t)

        path_rets = drift + sigma * shocks
        terminal = path_rets.sum(axis=1)
        p_up = float((terminal > 0).mean())
        p_down = 1.0 - p_up
        exp_move = float(np.mean(np.exp(terminal) - 1))
        var_95 = float(np.quantile(np.exp(terminal) - 1, 0.05))
        tail = np.exp(terminal) - 1
        cvar = float(tail[tail <= var_95].mean()) if np.any(tail <= var_95) else var_95

        # For binary market: map p_up to YES fair when market is "price up" style
        p_win_yes = p_up
        edge = p_win_yes - market_yes_prob

        return MonteCarloResult(
            n_sims=self.n_sims,
            p_up=p_up,
            p_down=p_down,
            expected_move_pct=exp_move,
            var_95=var_95,
            cvar_95=cvar,
            p_win_yes=p_win_yes,
            p_win_no=1 - p_win_yes,
            edge_vs_market=edge,
        )
