"""MEXC Spot REST client — balance + market orders (HMAC-SHA256)."""

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


class MexcSpotClient:
    """
    MEXC Spot API v3 (compatible-style).
    Docs: https://mexcdevelop.github.io/apidocs/spot_v3_en/
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        quote: str = "USDT",
    ) -> None:
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.quote = quote.upper()
        self.base = "https://api.mexc.com"
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
        headers = {"X-MEXC-APIKEY": self.api_key, "Content-Type": "application/json"}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            params["signature"] = self._sign(params)
        url = f"{self.base}{path}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            if method.upper() == "POST" and signed:
                r = await client.post(url, params=params, headers=headers)
            else:
                r = await client.request(method, url, params=params, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"MEXC {r.status_code}: {r.text[:400]}")
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
        if isinstance(data, list):
            data = data[0]
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
        info = await self._request("GET", "/api/v3/exchangeInfo")
        out = {"stepSize": 0.00001, "minQty": 0.0, "minNotional": 1.0}
        for sym in info.get("symbols", []):
            if sym.get("symbol") != pair:
                continue
            # MEXC uses baseSizePrecision / quoteAmountPrecision
            prec = int(sym.get("baseAssetPrecision") or 6)
            out["stepSize"] = 10 ** (-prec)
            out["minQty"] = float(sym.get("baseSizePrecision") or 0) or out["stepSize"]
            for f in sym.get("filters") or []:
                if f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL"):
                    out["minNotional"] = float(
                        f.get("minNotional") or f.get("notional") or out["minNotional"]
                    )
            break
        self._filters[pair] = out
        return out

    @staticmethod
    def _round_step(qty: float, step: float) -> float:
        if step <= 0:
            return qty
        precision = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
        floored = (int(qty / step)) * step
        return float(f"{floored:.{precision}f}")

    async def market_order(self, symbol: str, side: str, quote_usd: float) -> dict:
        pair = self._pair(symbol)
        filters = await self.load_filters(symbol)
        px = await self.price(symbol)
        side = side.upper()
        qty = self._round_step(quote_usd / px, filters["stepSize"])
        if qty < filters["minQty"] or qty * px < filters["minNotional"]:
            raise RuntimeError(
                f"Order too small: qty={qty} notional=${qty*px:.2f} "
                f"(minNotional={filters['minNotional']})"
            )
        params = {
            "symbol": pair,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
        }
        log.warning(
            "MEXC LIVE ORDER %s %s qty=%s (~$%.2f)",
            side,
            pair,
            qty,
            qty * px,
        )
        return await self._request("POST", "/api/v3/order", params, signed=True)

    async def execute_signal(self, signal: TradeSignal) -> TradeRecord:
        side = "BUY" if signal.side in (Side.BUY, Side.YES) else "SELL"
        raw = await self.market_order(signal.symbol, side, signal.size_usd)
        return TradeRecord(
            id=str(raw.get("orderId") or uuid.uuid4())[:16],
            mode="live-mexc",
            symbol=signal.symbol,
            side=signal.side,
            size_usd=signal.size_usd,
            entry_prob=signal.market_prob,
            fair_prob=signal.fair_prob,
            edge=signal.edge,
            status="open",
            market_question=signal.market_question or f"spot {side}",
            meta={"exchange": "mexc", "raw": raw},
            opened_at=utc_now(),
        )
