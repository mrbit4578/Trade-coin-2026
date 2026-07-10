"""REST fallback when WebSockets are unavailable (e.g. firewall / offline tests)."""

from __future__ import annotations

from typing import Iterable

import httpx

from crypto_edge.models import BookLevel, OrderBookSnapshot, Tick, utc_now

BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_DEPTH = "https://api.binance.com/api/v3/depth"
COINBASE_TICKER = "https://api.exchange.coinbase.com/products/{product}/ticker"
BYBIT_TICKER = "https://api.bybit.com/v5/market/tickers"


def _binance_symbol(sym: str) -> str:
    return f"{sym.upper()}USDT"


def _coinbase_product(sym: str) -> str:
    return f"{sym.upper()}-USD"


async def fetch_binance_tickers(symbols: Iterable[str]) -> list[Tick]:
    wanted = {_binance_symbol(s) for s in symbols}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(BINANCE_TICKER)
        r.raise_for_status()
        data = r.json()
    out: list[Tick] = []
    for row in data:
        if row.get("symbol") not in wanted:
            continue
        base = row["symbol"].replace("USDT", "")
        out.append(
            Tick(
                exchange="binance",
                symbol=base,
                price=float(row["lastPrice"]),
                bid=float(row.get("bidPrice") or 0),
                ask=float(row.get("askPrice") or 0),
                volume_24h=float(row.get("quoteVolume") or 0),
                ts=utc_now(),
            )
        )
    return out


async def fetch_binance_depth(symbol: str, limit: int = 50) -> OrderBookSnapshot:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            BINANCE_DEPTH,
            params={"symbol": _binance_symbol(symbol), "limit": limit},
        )
        r.raise_for_status()
        data = r.json()
    return OrderBookSnapshot(
        exchange="binance",
        symbol=symbol.upper(),
        bids=[BookLevel(price=float(p), size=float(s)) for p, s in data.get("bids", [])],
        asks=[BookLevel(price=float(p), size=float(s)) for p, s in data.get("asks", [])],
        ts=utc_now(),
    )


async def fetch_coinbase_ticker(symbol: str) -> Tick | None:
    product = _coinbase_product(symbol)
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(COINBASE_TICKER.format(product=product))
        if r.status_code != 200:
            return None
        data = r.json()
    price = float(data.get("price") or 0)
    return Tick(
        exchange="coinbase",
        symbol=symbol.upper(),
        price=price,
        bid=float(data.get("bid") or 0),
        ask=float(data.get("ask") or 0),
        volume_24h=float(data.get("volume") or 0) * price,
        ts=utc_now(),
    )


async def fetch_bybit_ticker(symbol: str) -> Tick | None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            BYBIT_TICKER,
            params={"category": "spot", "symbol": _binance_symbol(symbol)},
        )
        if r.status_code != 200:
            return None
        data = r.json()
    rows = (data.get("result") or {}).get("list") or []
    if not rows:
        return None
    row = rows[0]
    return Tick(
        exchange="bybit",
        symbol=symbol.upper(),
        price=float(row.get("lastPrice") or 0),
        bid=float(row.get("bid1Price") or 0),
        ask=float(row.get("ask1Price") or 0),
        volume_24h=float(row.get("turnover24h") or 0),
        ts=utc_now(),
    )
