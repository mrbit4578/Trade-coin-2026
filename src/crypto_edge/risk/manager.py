"""
Risk controls:
- half-Kelly position sizing
- 2% max daily loss
- halt after N consecutive losses
- skip thin liquidity / conflicting signals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone


@dataclass
class RiskState:
    equity: float
    day: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    day_start_equity: float = 0.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    halted: bool = False
    halt_reason: str = ""

    def __post_init__(self) -> None:
        if self.day_start_equity <= 0:
            self.day_start_equity = self.equity


class RiskManager:
    def __init__(
        self,
        equity: float,
        half_kelly: bool = True,
        max_daily_loss_pct: float = 0.02,
        max_consecutive_losses: int = 5,
        max_position_pct: float = 0.05,
        min_liquidity_usd: float = 50_000.0,
        edge_threshold: float = 0.05,
    ) -> None:
        self.half_kelly = half_kelly
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_consecutive_losses = max_consecutive_losses
        self.max_position_pct = max_position_pct
        self.min_liquidity_usd = min_liquidity_usd
        self.edge_threshold = edge_threshold
        self.state = RiskState(equity=equity)

    def _roll_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.state.day:
            self.state.day = today
            self.state.day_start_equity = self.state.equity
            self.state.daily_pnl = 0.0
            if self.state.halted and "daily" in self.state.halt_reason:
                self.state.halted = False
                self.state.halt_reason = ""

    def can_trade(
        self,
        edge: float,
        liquidity_usd: float,
        conflict: bool = False,
    ) -> tuple[bool, str]:
        self._roll_day()
        if self.state.halted:
            return False, f"HALTED: {self.state.halt_reason}"
        if self.state.consecutive_losses >= self.max_consecutive_losses:
            self.state.halted = True
            self.state.halt_reason = f"{self.max_consecutive_losses} consecutive losses"
            return False, self.state.halt_reason
        if self.state.daily_pnl <= -self.max_daily_loss_pct * self.state.day_start_equity:
            self.state.halted = True
            self.state.halt_reason = "daily loss limit 2%"
            return False, self.state.halt_reason
        if abs(edge) < self.edge_threshold:
            return False, f"edge {edge:.3f} < threshold {self.edge_threshold}"
        if liquidity_usd < self.min_liquidity_usd:
            return False, f"thin liquidity ${liquidity_usd:,.0f}"
        if conflict:
            return False, "conflicting signals"
        return True, "ok"

    def position_size(
        self,
        edge: float,
        win_prob: float,
        odds_net: float = 1.0,
    ) -> float:
        """
        Half-Kelly for binary-ish payoff.
        f* = (bp - q) / b  where b=net odds, p=win_prob, q=1-p
        For Polymarket YES at price c, payout ~ (1-c)/c if win.
        """
        self._roll_day()
        p = min(0.95, max(0.05, win_prob))
        q = 1 - p
        b = max(0.05, odds_net)
        kelly = (b * p - q) / b
        if kelly <= 0:
            return 0.0
        frac = kelly * (0.5 if self.half_kelly else 1.0)
        frac = min(frac, self.max_position_pct)
        # scale mildly by edge magnitude
        frac *= min(1.5, 0.5 + abs(edge) * 5)
        frac = min(frac, self.max_position_pct)
        return float(self.state.equity * frac)

    def register_trade_result(self, pnl: float) -> None:
        self._roll_day()
        self.state.equity += pnl
        self.state.daily_pnl += pnl
        if pnl < 0:
            self.state.consecutive_losses += 1
        elif pnl > 0:
            self.state.consecutive_losses = 0
        if self.state.consecutive_losses >= self.max_consecutive_losses:
            self.state.halted = True
            self.state.halt_reason = f"{self.max_consecutive_losses} consecutive losses"
        if self.state.daily_pnl <= -self.max_daily_loss_pct * self.state.day_start_equity:
            self.state.halted = True
            self.state.halt_reason = "daily loss limit"
