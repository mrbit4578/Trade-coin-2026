"""
Live WebSocket feeds: Binance + Coinbase + Bybit.

Public order-book streams. Institutional "closed" books are not available
on public APIs — depth is aggregated from L2 public books (see orderbook/).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Iterable

import orjson
import websockets

from crypto_edge.models import BookLevel, OrderBookSnapshot, Tick, utc_now

log = logging.getLogger(__name__)

TickHandler = Callable[[Tick], Awaitable[None] | None]
BookHandler = Callable[[OrderBookSnapshot], Awaitable[None] | None]


async def _maybe_await(result) -> None:
    if asyncio.iscoroutine(result):
        await result


class BinanceWS:
    """Combined trade + depth stream for USDT pairs."""

    def __init__(
        self,
        symbols: Iterable[str],
        on_tick: TickHandler | None = None,
        on_book: BookHandler | None = None,
    ) -> None:
        self.symbols = [s.upper() for s in symbols]
        self.on_tick = on_tick
        self.on_book = on_book
        self._stop = asyncio.Event()

    def _url(self) -> str:
        streams = []
        for s in self.symbols:
            sym = f"{s.lower()}usdt"
            streams.append(f"{sym}@ticker")
            streams.append(f"{sym}@depth20@100ms")
        return "wss://stream.binance.com:9443/stream?streams=" + "/".join(streams)

    async def run(self) -> None:
        url = self._url()
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    log.info("Binance WS connected (%d symbols)", len(self.symbols))
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        msg = orjson.loads(raw)
                        data = msg.get("data") or msg
                        stream = msg.get("stream", "")
                        await self._handle(stream, data)
            except Exception as e:
                log.warning("Binance WS error: %s — reconnect in 3s", e)
                await asyncio.sleep(3)

    async def _handle(self, stream: str, data: dict) -> None:
        if "ticker" in stream or data.get("e") == "24hrTicker":
            sym = str(data.get("s", "")).replace("USDT", "")
            if not sym:
                return
            tick = Tick(
                exchange="binance",
                symbol=sym,
                price=float(data.get("c") or 0),
                bid=float(data.get("b") or 0),
                ask=float(data.get("a") or 0),
                volume_24h=float(data.get("q") or 0),
                ts=utc_now(),
            )
            if self.on_tick:
                await _maybe_await(self.on_tick(tick))
        elif "depth" in stream:
            # stream like btcusdt@depth20@100ms
            part = stream.split("@")[0]
            sym = part.replace("usdt", "").upper()
            bids = [BookLevel(price=float(p), size=float(s)) for p, s in data.get("bids", [])]
            asks = [BookLevel(price=float(p), size=float(s)) for p, s in data.get("asks", [])]
            book = OrderBookSnapshot(
                exchange="binance", symbol=sym, bids=bids, asks=asks, ts=utc_now()
            )
            if self.on_book:
                await _maybe_await(self.on_book(book))

    def stop(self) -> None:
        self._stop.set()


class CoinbaseWS:
    def __init__(
        self,
        symbols: Iterable[str],
        on_tick: TickHandler | None = None,
        on_book: BookHandler | None = None,
    ) -> None:
        self.products = [f"{s.upper()}-USD" for s in symbols]
        self.on_tick = on_tick
        self.on_book = on_book
        self._stop = asyncio.Event()
        self._books: dict[str, dict] = {}

    async def run(self) -> None:
        url = "wss://ws-feed.exchange.coinbase.com"
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    sub = {
                        "type": "subscribe",
                        "product_ids": self.products,
                        "channels": ["ticker", "level2_batch"],
                    }
                    await ws.send(orjson.dumps(sub).decode())
                    log.info("Coinbase WS connected")
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        data = orjson.loads(raw)
                        await self._handle(data)
            except Exception as e:
                log.warning("Coinbase WS error: %s — reconnect in 3s", e)
                await asyncio.sleep(3)

    async def _handle(self, data: dict) -> None:
        t = data.get("type")
        product = data.get("product_id", "")
        sym = product.split("-")[0] if product else ""
        if t == "ticker" and sym:
            tick = Tick(
                exchange="coinbase",
                symbol=sym,
                price=float(data.get("price") or 0),
                bid=float(data.get("best_bid") or 0),
                ask=float(data.get("best_ask") or 0),
                volume_24h=float(data.get("volume_24h") or 0)
                * float(data.get("price") or 0),
                ts=utc_now(),
            )
            if self.on_tick:
                await _maybe_await(self.on_tick(tick))
        elif t in ("l2update", "snapshot") and sym:
            # Minimal L2 tracking for top-of-book depth sample
            if t == "snapshot":
                self._books[sym] = {
                    "bids": {float(p): float(s) for p, s in data.get("bids", [])[:50]},
                    "asks": {float(p): float(s) for p, s in data.get("asks", [])[:50]},
                }
            else:
                book = self._books.setdefault(sym, {"bids": {}, "asks": {}})
                for side, price, size in data.get("changes", []):
                    p, s = float(price), float(size)
                    side_map = book["bids"] if side == "buy" else book["asks"]
                    if s == 0:
                        side_map.pop(p, None)
                    else:
                        side_map[p] = s
            book = self._books.get(sym)
            if book and self.on_book:
                bids = sorted(book["bids"].items(), key=lambda x: -x[0])[:20]
                asks = sorted(book["asks"].items(), key=lambda x: x[0])[:20]
                snap = OrderBookSnapshot(
                    exchange="coinbase",
                    symbol=sym,
                    bids=[BookLevel(price=p, size=s) for p, s in bids],
                    asks=[BookLevel(price=p, size=s) for p, s in asks],
                    ts=utc_now(),
                )
                await _maybe_await(self.on_book(snap))

    def stop(self) -> None:
        self._stop.set()


class BybitWS:
    def __init__(
        self,
        symbols: Iterable[str],
        on_tick: TickHandler | None = None,
        on_book: BookHandler | None = None,
    ) -> None:
        self.symbols = [f"{s.upper()}USDT" for s in symbols]
        self.on_tick = on_tick
        self.on_book = on_book
        self._stop = asyncio.Event()

    async def run(self) -> None:
        url = "wss://stream.bybit.com/v5/public/spot"
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    args = [f"tickers.{s}" for s in self.symbols] + [
                        f"orderbook.50.{s}" for s in self.symbols
                    ]
                    await ws.send(orjson.dumps({"op": "subscribe", "args": args}).decode())
                    log.info("Bybit WS connected")
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        data = orjson.loads(raw)
                        await self._handle(data)
            except Exception as e:
                log.warning("Bybit WS error: %s — reconnect in 3s", e)
                await asyncio.sleep(3)

    async def _handle(self, data: dict) -> None:
        topic = data.get("topic", "")
        payload = data.get("data")
        if not payload:
            return
        if topic.startswith("tickers."):
            row = payload if isinstance(payload, dict) else payload[0]
            sym = str(row.get("symbol", "")).replace("USDT", "")
            tick = Tick(
                exchange="bybit",
                symbol=sym,
                price=float(row.get("lastPrice") or 0),
                bid=float(row.get("bid1Price") or 0),
                ask=float(row.get("ask1Price") or 0),
                volume_24h=float(row.get("turnover24h") or 0),
                ts=utc_now(),
            )
            if self.on_tick:
                await _maybe_await(self.on_tick(tick))
        elif topic.startswith("orderbook."):
            row = payload if isinstance(payload, dict) else {}
            sym = str(row.get("s") or topic.split(".")[-1]).replace("USDT", "")
            bids = [BookLevel(price=float(p), size=float(s)) for p, s in row.get("b", [])]
            asks = [BookLevel(price=float(p), size=float(s)) for p, s in row.get("a", [])]
            if self.on_book and (bids or asks):
                await _maybe_await(
                    self.on_book(
                        OrderBookSnapshot(
                            exchange="bybit",
                            symbol=sym,
                            bids=bids,
                            asks=asks,
                            ts=utc_now(),
                        )
                    )
                )

    def stop(self) -> None:
        self._stop.set()
