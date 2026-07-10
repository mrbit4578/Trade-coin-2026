"""Binance Spot REST client — balance + market/limit orders (HMAC-SHA256)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from crypto_edge.models import Side, TradeRecord, TradeSignal, utc_now

log = logging.getLogger(__name__)


class BinanceSpotClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        quote: str = "USDT",
    ) -> None:
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.quote = quote.upper()
        self.base = (
            "https://testnet.binance.vision"
            if testnet
            else "https://api.binance.com"
        )
        self.testnet = testnet
        self._filters: dict[str, dict[str, float]] = {}

    def _sign(self, params: dict[str, Any]) -> str:
        query = urlencode(params)
        return hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        signed: bool = False,
    ) -> Any:
        params = dict(params or {})
        headers = {"X-MBX-APIKEY": self.api_key}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            params["signature"] = self._sign(params)
        url = f"{self.base}{path}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.request(method, url, params=params, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"Binance {r.status_code}: {r.text[:400]}")
            return r.json()

    async def ping(self) -> bool:
        await self._request("GET", "/api/v3/ping")
        return True

    async def account(self) -> dict:
        return await self._request("GET", "/api/v3/account", signed=True)

    async def free_balance(self, asset: str) -> float:
        acc = await self.account()
        asset = asset.upper()
        for b in acc.get("balances", []):
            if b.get("asset") == asset:
                return float(b.get("free") or 0)
        return 0.0

    async def price(self, symbol: str) -> float:
        pair = self._pair(symbol)
        data = await self._request("GET", "/api/v3/ticker/price", {"symbol": pair})
        return float(data["price"])

    def _pair(self, symbol: str) -> str:
        s = symbol.upper().replace("/", "").replace("-", "")
        if s.endswith(self.quote):
            return s
        return f"{s}{self.quote}"

    async def load_filters(self, symbol: str) -> dict[str, float]:
        pair = self._pair(symbol)
        if pair in self._filters:
            return self._filters[pair]
        info = await self._request("GET", "/api/v3/exchangeInfo", {"symbol": pair})
        sym = (info.get("symbols") or [{}])[0]
        out = {"stepSize": 0.00001, "minQty": 0.0, "minNotional": 5.0, "tickSize": 0.01}
        for f in sym.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                out["stepSize"] = float(f.get("stepSize") or out["stepSize"])
                out["minQty"] = float(f.get("minQty") or 0)
            elif f.get("filterType") in ("NOTIONAL", "MIN_NOTIONAL"):
                out["minNotional"] = float(
                    f.get("minNotional") or f.get("notional") or out["minNotional"]
                )
            elif f.get("filterType") == "PRICE_FILTER":
                out["tickSize"] = float(f.get("tickSize") or out["tickSize"])
        self._filters[pair] = out
        return out

    @staticmethod
    def _round_step(qty: float, step: float) -> float:
        if step <= 0:
            return qty
        precision = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
        floored = (int(qty / step)) * step
        return float(f"{floored:.{precision}f}")

    async def market_order(
        self, symbol: str, side: str, quote_usd: float
    ) -> dict:
        """
        Market order sized in quote (USDT) for BUY, or base qty for SELL via quote estimate.
        side: BUY | SELL
        """
        pair = self._pair(symbol)
        filters = await self.load_filters(symbol)
        px = await self.price(symbol)
        side = side.upper()
        if side == "BUY":
            qty = self._round_step(quote_usd / px, filters["stepSize"])
        else:
            # sell base amount worth ~quote_usd
            qty = self._round_step(quote_usd / px, filters["stepSize"])
        if qty < filters["minQty"] or qty * px < filters["minNotional"]:
            raise RuntimeError(
                f"Order too small: qty={qty} notional=${qty*px:.2f} "
                f"(minQty={filters['minQty']}, minNotional={filters['minNotional']})"
            )
        params = {
            "symbol": pair,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": f"cea{uuid.uuid4().hex[:16]}",
        }
        log.warning(
            "BINANCE LIVE ORDER %s %s qty=%s (~$%.2f) testnet=%s",
            side,
            pair,
            qty,
            qty * px,
            self.testnet,
        )
        return await self._request("POST", "/api/v3/order", params, signed=True)

    async def execute_signal(self, signal: TradeSignal) -> TradeRecord:
        side = "BUY" if signal.side in (Side.BUY, Side.YES) else "SELL"
        raw = await self.market_order(signal.symbol, side, signal.size_usd)
        filled_quote = float(raw.get("cummulativeQuoteQty") or signal.size_usd)
        return TradeRecord(
            id=str(raw.get("orderId") or uuid.uuid4())[:16],
            mode="live-binance",
            symbol=signal.symbol,
            side=signal.side,
            size_usd=filled_quote,
            entry_prob=signal.market_prob,
            fair_prob=signal.fair_prob,
            edge=signal.edge,
            status="open",
            market_question=signal.market_question or f"spot {side}",
            meta={"exchange": "binance", "raw": raw, "testnet": self.testnet},
            opened_at=utc_now(),
        )
