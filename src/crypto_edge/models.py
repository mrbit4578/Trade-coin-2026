"""Shared domain models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    YES = "YES"
    NO = "NO"


class SignalAction(str, Enum):
    ENTER = "ENTER"
    SKIP = "SKIP"
    HALT = "HALT"


class Tick(BaseModel):
    exchange: str
    symbol: str
    price: float
    bid: float = 0.0
    ask: float = 0.0
    volume_24h: float = 0.0
    ts: datetime = Field(default_factory=utc_now)


class BookLevel(BaseModel):
    price: float
    size: float


class OrderBookSnapshot(BaseModel):
    exchange: str
    symbol: str
    bids: list[BookLevel] = Field(default_factory=list)
    asks: list[BookLevel] = Field(default_factory=list)
    ts: datetime = Field(default_factory=utc_now)

    @property
    def mid(self) -> float:
        if not self.bids or not self.asks:
            return 0.0
        return (self.bids[0].price + self.asks[0].price) / 2.0

    @property
    def spread_bps(self) -> float:
        if not self.bids or not self.asks or self.mid <= 0:
            return 9999.0
        return (self.asks[0].price - self.bids[0].price) / self.mid * 10_000

    def depth_usd(self, levels: int = 20) -> float:
        bid_d = sum(l.price * l.size for l in self.bids[:levels])
        ask_d = sum(l.price * l.size for l in self.asks[:levels])
        return bid_d + ask_d

    def imbalance(self, levels: int = 10) -> float:
        bid_v = sum(l.size for l in self.bids[:levels])
        ask_v = sum(l.size for l in self.asks[:levels])
        total = bid_v + ask_v
        if total <= 0:
            return 0.0
        return (bid_v - ask_v) / total


class OTCFlow(BaseModel):
    symbol: str
    side: Side
    notional_usd: float
    premium_bps: float = 0.0
    desk: str = "sim"
    ts: datetime = Field(default_factory=utc_now)


class PolyMarket(BaseModel):
    condition_id: str
    question: str
    slug: str = ""
    token_yes: str = ""
    token_no: str = ""
    yes_price: float = 0.5
    no_price: float = 0.5
    volume: float = 0.0
    liquidity: float = 0.0
    end_date: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    related_symbol: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Mispricing(BaseModel):
    market: PolyMarket
    symbol: str
    fair_prob: float
    market_prob: float
    edge: float
    direction: Side
    confidence: float
    reasons: list[str] = Field(default_factory=list)


class StructureSignal(BaseModel):
    symbol: str
    trend: Literal["bull", "bear", "range"] = "range"
    bos: bool = False
    choch: bool = False
    in_discount: bool = False
    in_premium: bool = False
    stop_hunt: bool = False
    score: float = 0.0
    notes: list[str] = Field(default_factory=list)


class MonteCarloResult(BaseModel):
    n_sims: int
    p_up: float
    p_down: float
    expected_move_pct: float
    var_95: float
    cvar_95: float
    p_win_yes: float
    p_win_no: float
    edge_vs_market: float


class TradeSignal(BaseModel):
    action: SignalAction
    symbol: str
    market_question: str = ""
    side: Side = Side.YES
    edge: float = 0.0
    fair_prob: float = 0.0
    market_prob: float = 0.5
    size_usd: float = 0.0
    mc: Optional[MonteCarloResult] = None
    structure: Optional[StructureSignal] = None
    skip_reason: str = ""
    bayesian_win_rate: float = 0.5
    ts: datetime = Field(default_factory=utc_now)


class TradeRecord(BaseModel):
    id: str
    mode: str
    symbol: str
    side: Side
    size_usd: float
    entry_prob: float
    fair_prob: float
    edge: float
    status: Literal["open", "won", "lost", "cancelled"] = "open"
    pnl_usd: float = 0.0
    market_question: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: Optional[datetime] = None
