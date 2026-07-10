"""
OTC desk flow feed.

If OTC_FEED_URL is set, pulls JSON flows from a private endpoint.
Otherwise simulates institutional-style block prints from public
large-print heuristics (for paper research only).
"""

from __future__ import annotations

import logging
import random
from collections import deque
from datetime import datetime, timedelta, timezone

import httpx

from crypto_edge.models import OTCFlow, Side, Tick

log = logging.getLogger(__name__)


class OTCFeed:
    def __init__(
        self,
        symbols: list[str],
        url: str = "",
        api_key: str = "",
        simulate: bool = True,
        maxlen: int = 200,
    ) -> None:
        self.symbols = symbols
        self.url = url
        self.api_key = api_key
        self.simulate = simulate or not url
        self.flows: deque[OTCFlow] = deque(maxlen=maxlen)

    async def poll(self, ticks: dict[str, float] | None = None) -> list[OTCFlow]:
        if self.url and not self.simulate:
            try:
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(self.url, headers=headers)
                    r.raise_for_status()
                    rows = r.json()
                new = [OTCFlow.model_validate(row) for row in rows]
                for f in new:
                    self.flows.append(f)
                return new
            except Exception as e:
                log.warning("OTC feed error, falling back to sim: %s", e)

        return self._simulate_flows(ticks or {})

    def _simulate_flows(self, ticks: dict[str, float]) -> list[OTCFlow]:
        """Sparse synthetic block prints for paper mode research."""
        out: list[OTCFlow] = []
        if random.random() > 0.35:
            return out
        sym = random.choice(self.symbols)
        side = random.choice([Side.BUY, Side.SELL])
        notional = random.uniform(250_000, 5_000_000)
        premium = random.uniform(-8, 12) if side == Side.BUY else random.uniform(-12, 8)
        flow = OTCFlow(
            symbol=sym,
            side=side,
            notional_usd=notional,
            premium_bps=premium,
            desk="sim-desk",
        )
        self.flows.append(flow)
        out.append(flow)
        return out

    def recent(self, symbol: str | None = None, minutes: int = 60) -> list[OTCFlow]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        rows = [f for f in self.flows if f.ts >= cutoff]
        if symbol:
            rows = [f for f in rows if f.symbol.upper() == symbol.upper()]
        return rows

    def net_bias(self, symbol: str) -> float:
        rows = self.recent(symbol)
        if not rows:
            return 0.0
        buy = sum(f.notional_usd for f in rows if f.side == Side.BUY)
        sell = sum(f.notional_usd for f in rows if f.side == Side.SELL)
        total = buy + sell
        return (buy - sell) / total if total else 0.0
