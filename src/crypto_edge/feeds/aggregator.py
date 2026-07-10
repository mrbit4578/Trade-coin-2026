"""Multi-exchange market data hub with REST warm-start + optional WS live."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque

from crypto_edge.feeds.rest_fallback import (
    fetch_binance_depth,
    fetch_binance_tickers,
    fetch_bybit_ticker,
    fetch_coinbase_ticker,
)
from crypto_edge.feeds.ws_feeds import BinanceWS, BybitWS, CoinbaseWS
from crypto_edge.models import OrderBookSnapshot, Tick

log = logging.getLogger(__name__)


@dataclass
class MarketDataHub:
    symbols: list[str]
    use_websockets: bool = True
    history_len: int = 500
    ticks: dict[str, dict[str, Tick]] = field(default_factory=lambda: defaultdict(dict))
    books: dict[str, dict[str, OrderBookSnapshot]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    price_history: dict[str, Deque[float]] = field(default_factory=dict)
    _tasks: list[asyncio.Task] = field(default_factory=list)
    _ws: list = field(default_factory=list)

    def __post_init__(self) -> None:
        for s in self.symbols:
            self.price_history[s] = deque(maxlen=self.history_len)

    async def on_tick(self, tick: Tick) -> None:
        self.ticks[tick.symbol][tick.exchange] = tick
        if tick.price > 0:
            self.price_history[tick.symbol].append(tick.price)

    async def on_book(self, book: OrderBookSnapshot) -> None:
        self.books[book.symbol][book.exchange] = book

    async def warm_start(self) -> None:
        """Pull REST snapshots so agent can decide before WS fills in."""
        try:
            for t in await fetch_binance_tickers(self.symbols):
                await self.on_tick(t)
        except Exception as e:
            log.warning("Binance REST ticker failed: %s", e)

        for sym in self.symbols:
            try:
                book = await fetch_binance_depth(sym)
                await self.on_book(book)
            except Exception as e:
                log.debug("depth %s: %s", sym, e)
            try:
                cb = await fetch_coinbase_ticker(sym)
                if cb:
                    await self.on_tick(cb)
            except Exception:
                pass
            try:
                bb = await fetch_bybit_ticker(sym)
                if bb:
                    await self.on_tick(bb)
            except Exception:
                pass
        log.info(
            "Warm-start complete: %s",
            {s: self.consensus_price(s) for s in self.symbols},
        )

    async def start(self) -> None:
        await self.warm_start()
        if not self.use_websockets:
            return
        bn = BinanceWS(self.symbols, on_tick=self.on_tick, on_book=self.on_book)
        cb = CoinbaseWS(self.symbols, on_tick=self.on_tick, on_book=self.on_book)
        bb = BybitWS(self.symbols, on_tick=self.on_tick, on_book=self.on_book)
        self._ws = [bn, cb, bb]
        self._tasks = [
            asyncio.create_task(bn.run(), name="ws-binance"),
            asyncio.create_task(cb.run(), name="ws-coinbase"),
            asyncio.create_task(bb.run(), name="ws-bybit"),
        ]

    async def stop(self) -> None:
        for w in self._ws:
            w.stop()
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

    def consensus_price(self, symbol: str) -> float:
        ex = self.ticks.get(symbol.upper(), {})
        prices = [t.price for t in ex.values() if t.price > 0]
        if not prices:
            return 0.0
        return sum(prices) / len(prices)

    def mid_prices(self) -> dict[str, float]:
        return {s: self.consensus_price(s) for s in self.symbols}

    def history(self, symbol: str) -> list[float]:
        return list(self.price_history.get(symbol.upper(), []))
