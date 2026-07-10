"""
Aggregated multi-venue L2 depth.

Note: True institutional "closed" / dark order books are not public.
This module builds a *proxy* by stitching Binance + Coinbase + Bybit L2
and scoring hidden liquidity via spread, imbalance, and OTC overlays.
"""

from __future__ import annotations

from crypto_edge.models import BookLevel, OrderBookSnapshot, OTCFlow


def aggregate_books(books: list[OrderBookSnapshot]) -> OrderBookSnapshot:
    if not books:
        return OrderBookSnapshot(exchange="agg", symbol="?")
    symbol = books[0].symbol
    bid_map: dict[float, float] = {}
    ask_map: dict[float, float] = {}
    for b in books:
        for lvl in b.bids:
            bid_map[lvl.price] = bid_map.get(lvl.price, 0.0) + lvl.size
        for lvl in b.asks:
            ask_map[lvl.price] = ask_map.get(lvl.price, 0.0) + lvl.size
    bids = [BookLevel(price=p, size=s) for p, s in sorted(bid_map.items(), key=lambda x: -x[0])[:50]]
    asks = [BookLevel(price=p, size=s) for p, s in sorted(ask_map.items(), key=lambda x: x[0])[:50]]
    return OrderBookSnapshot(exchange="agg", symbol=symbol, bids=bids, asks=asks)


class ClosedBookProxy:
    """
    Proxy for closed-book signals used by the simulation stack.

    Features:
    - multi-venue aggregated depth
    - effective liquidity (visible * venue_weight)
    - toxicity / imbalance score
    - OTC flow overlay adjustment
    """

    VENUE_WEIGHT = {"binance": 1.0, "coinbase": 0.85, "bybit": 0.75, "agg": 1.0}

    def score(
        self,
        books_by_exchange: dict[str, OrderBookSnapshot],
        otc_flows: list[OTCFlow] | None = None,
    ) -> dict:
        if not books_by_exchange:
            return {
                "depth_usd": 0.0,
                "imbalance": 0.0,
                "spread_bps": 9999.0,
                "toxicity": 1.0,
                "hidden_liq_score": 0.0,
                "thin": True,
            }

        weighted: list[OrderBookSnapshot] = []
        for ex, book in books_by_exchange.items():
            w = self.VENUE_WEIGHT.get(ex, 0.5)
            # Scale sizes by venue weight to approximate relative reliability
            weighted.append(
                OrderBookSnapshot(
                    exchange=ex,
                    symbol=book.symbol,
                    bids=[BookLevel(price=l.price, size=l.size * w) for l in book.bids],
                    asks=[BookLevel(price=l.price, size=l.size * w) for l in book.asks],
                    ts=book.ts,
                )
            )
        agg = aggregate_books(weighted)
        depth = agg.depth_usd(20)
        imb = agg.imbalance(10)
        spread = agg.spread_bps

        otc_bias = 0.0
        if otc_flows:
            buy = sum(f.notional_usd for f in otc_flows if f.side.value in ("BUY", "YES"))
            sell = sum(f.notional_usd for f in otc_flows if f.side.value in ("SELL", "NO"))
            total = buy + sell
            if total > 0:
                otc_bias = (buy - sell) / total

        # Higher toxicity when spread wide or one-sided
        toxicity = min(1.0, abs(imb) * 0.5 + min(spread, 50) / 50 * 0.5)
        hidden = max(0.0, 1.0 - toxicity) * min(1.0, depth / 500_000)

        return {
            "depth_usd": depth,
            "imbalance": imb,
            "spread_bps": spread,
            "toxicity": toxicity,
            "hidden_liq_score": hidden,
            "otc_bias": otc_bias,
            "mid": agg.mid,
            "thin": depth < 50_000 or spread > 25,
            "agg_book": agg,
        }
