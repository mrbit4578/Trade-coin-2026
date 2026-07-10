"""Paper trading ledger — default and safest path."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from crypto_edge.models import Side, TradeRecord, TradeSignal, utc_now


class PaperBroker:
    def __init__(self, capital: float, path: Path) -> None:
        self.capital = capital
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.open: list[TradeRecord] = []
        self.closed: list[TradeRecord] = []

    def execute(self, signal: TradeSignal) -> TradeRecord:
        rec = TradeRecord(
            id=str(uuid.uuid4())[:8],
            mode="paper",
            symbol=signal.symbol,
            side=signal.side,
            size_usd=signal.size_usd,
            entry_prob=signal.market_prob,
            fair_prob=signal.fair_prob,
            edge=signal.edge,
            status="open",
            market_question=signal.market_question,
            meta={
                "bayesian_win_rate": signal.bayesian_win_rate,
                "mc": signal.mc.model_dump() if signal.mc else None,
            },
        )
        self.open.append(rec)
        self._append(rec)
        return rec

    def resolve_random_for_demo(self, win_prob: float, rng=None) -> list[TradeRecord]:
        """Optional demo resolver — production should resolve on market settlement."""
        import random

        r = rng or random
        resolved: list[TradeRecord] = []
        still_open: list[TradeRecord] = []
        for t in self.open:
            # hold open for demo until caller decides — resolve half the book
            if r.random() > 0.5:
                still_open.append(t)
                continue
            won = r.random() < win_prob
            # PnL: buy YES at c → if win get 1, profit (1-c)/c * size roughly size*(1/c - 1) capped
            c = max(0.05, min(0.95, t.entry_prob))
            if t.side in (Side.YES, Side.BUY):
                pnl = t.size_usd * ((1 - c) / c) if won else -t.size_usd
            else:
                # NO side
                pnl = t.size_usd * (c / (1 - c)) if won else -t.size_usd
            t.pnl_usd = float(pnl)
            t.status = "won" if won else "lost"
            t.closed_at = utc_now()
            self.capital += t.pnl_usd
            self.closed.append(t)
            self._append(t)
            resolved.append(t)
        self.open = still_open
        return resolved

    def mark_result(self, trade_id: str, won: bool) -> Optional[TradeRecord]:
        for i, t in enumerate(self.open):
            if t.id != trade_id:
                continue
            c = max(0.05, min(0.95, t.entry_prob))
            if t.side in (Side.YES, Side.BUY):
                pnl = t.size_usd * ((1 - c) / c) if won else -t.size_usd
            else:
                pnl = t.size_usd * (c / (1 - c)) if won else -t.size_usd
            t.pnl_usd = float(pnl)
            t.status = "won" if won else "lost"
            t.closed_at = utc_now()
            self.capital += t.pnl_usd
            self.closed.append(t)
            self.open.pop(i)
            self._append(t)
            return t
        return None

    def _append(self, rec: TradeRecord) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.model_dump(mode="json")) + "\n")
