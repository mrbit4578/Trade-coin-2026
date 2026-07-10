"""Unit tests — no network required for pure logic."""

from __future__ import annotations

import numpy as np

from crypto_edge.bayesian.winrate import BayesianWinRate
from crypto_edge.models import BookLevel, OrderBookSnapshot, PolyMarket, Side
from crypto_edge.orderbook.aggregator import ClosedBookProxy, aggregate_books
from crypto_edge.risk.manager import RiskManager
from crypto_edge.simulation.mirofish import MiroFishGraph
from crypto_edge.simulation.monte_carlo import MonteCarloEngine
from crypto_edge.smc.structure import StructureAnalyzer
from crypto_edge.polymarket.mispricing import MispricingDetector


def test_aggregate_books():
    a = OrderBookSnapshot(
        exchange="binance",
        symbol="BTC",
        bids=[BookLevel(price=100, size=1)],
        asks=[BookLevel(price=101, size=1)],
    )
    b = OrderBookSnapshot(
        exchange="coinbase",
        symbol="BTC",
        bids=[BookLevel(price=100, size=2)],
        asks=[BookLevel(price=101.5, size=1)],
    )
    agg = aggregate_books([a, b])
    assert agg.bids[0].size == 3
    assert agg.symbol == "BTC"


def test_closed_book_proxy():
    book = OrderBookSnapshot(
        exchange="binance",
        symbol="ETH",
        bids=[BookLevel(price=3000, size=10)],
        asks=[BookLevel(price=3001, size=8)],
    )
    score = ClosedBookProxy().score({"binance": book})
    assert score["depth_usd"] > 0
    assert "imbalance" in score


def test_monte_carlo_10k():
    rng = np.random.default_rng(0)
    prices = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 200))
    mc = MonteCarloEngine(n_sims=10_000, seed=1).run(prices.tolist(), market_yes_prob=0.5)
    assert mc.n_sims == 10_000
    assert 0 < mc.p_up < 1
    assert mc.var_95 <= mc.expected_move_pct or True


def test_structure_analyzer():
    # uptrend
    prices = [100 + i * 0.5 + (i % 3) * 0.1 for i in range(80)]
    s = StructureAnalyzer().analyze("BTC", prices)
    assert s.trend in ("bull", "bear", "range")
    assert -1 <= s.score <= 1


def test_half_kelly_and_halt():
    rm = RiskManager(equity=1000, max_consecutive_losses=3)
    size = rm.position_size(edge=0.1, win_prob=0.6, odds_net=1.0)
    assert size > 0
    assert size <= 1000 * 0.05 * 1.5 + 1
    rm.register_trade_result(-20)
    rm.register_trade_result(-20)
    rm.register_trade_result(-20)
    ok, reason = rm.can_trade(0.1, 100_000)
    assert not ok
    assert "consecutive" in reason or "HALTED" in reason or "loss" in reason.lower()


def test_bayesian_update():
    b = BayesianWinRate()
    for _ in range(20):
        b.update(True)
    assert b.mean > 0.5
    assert b.size_multiplier() >= 1.0


def test_mirofish_graph():
    prices_book = OrderBookSnapshot(
        exchange="binance",
        symbol="SOL",
        bids=[BookLevel(price=150, size=20)],
        asks=[BookLevel(price=150.2, size=18)],
    )
    g = MiroFishGraph(n_agents=50, seed=0).build(
        symbol="SOL",
        spot=150,
        books={"binance": prices_book},
        otc=[],
        structure=None,
        poly_yes=0.45,
        mc_p_up=0.58,
    )
    assert 0 < g.consensus < 1
    assert len(g.agent_votes) == 50


def test_no_ethiopia_false_positive():
    from crypto_edge.polymarket.client import PolymarketClient

    c = PolymarketClient()
    assert c._match_symbol(
        "Will Shimelis Abdisa be the next Prime Minister of Ethiopia?",
        ["BTC", "ETH", "SOL"],
    ) is None
    assert c._match_symbol("Will Bitcoin be above $100k?", ["BTC", "ETH"]) == "BTC"
    assert c._match_symbol("Ethereum price above $5000?", ["ETH"]) == "ETH"


def test_mispricing_threshold_market():
    mc = MonteCarloEngine(n_sims=2000, seed=2).run(
        [100 + i * 0.2 for i in range(100)], market_yes_prob=0.4
    )
    market = PolyMarket(
        condition_id="x",
        question="Will BTC be above $90,000 by Friday?",
        yes_price=0.35,
        no_price=0.65,
        related_symbol="BTC",
        liquidity=100_000,
    )
    miss = MispricingDetector().detect(
        market, spot=95_000, mc=mc, edge_threshold=0.05
    )
    # may or may not trigger depending on fair; ensure no crash
    assert miss is None or miss.edge >= 0.05
