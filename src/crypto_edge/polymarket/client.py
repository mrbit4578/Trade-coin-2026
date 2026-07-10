"""Polymarket Gamma (discovery) + CLOB (book/prices) read client."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from crypto_edge.models import PolyMarket

log = logging.getLogger(__name__)

# Patterns must be regex; short tickers always use word boundaries.
# Avoid false positives (e.g. ETH ⊂ Ethiopia, SOL ⊂ "sold", NEAR ⊂ "nearly").
CRYPTO_KEYWORDS: dict[str, list[str]] = {
    "BTC": [r"\bbitcoin\b", r"\bbtc\b"],
    "ETH": [r"\bethereum\b", r"\beth\b(?!iopia)"],
    "SOL": [r"\bsolana\b", r"\bsol\b(?!\w)"],
    "BNB": [r"\bbinance coin\b", r"\bbnb\b", r"\bbnb chain\b"],
    "DOGE": [r"\bdogecoin\b", r"\bdoge\b"],
    "NEAR": [r"\bnear protocol\b", r"\bnear\b(?!\w)"],
}

# Require at least one crypto context term for short-ticker-only matches
CRYPTO_CONTEXT = re.compile(
    r"\b(crypto|cryptocurrency|bitcoin|ethereum|token|coin|blockchain|defi|altcoin|btc|eth|solana)\b",
    re.I,
)


class PolymarketClient:
    def __init__(
        self,
        gamma_url: str = "https://gamma-api.polymarket.com",
        clob_url: str = "https://clob.polymarket.com",
    ) -> None:
        self.gamma_url = gamma_url.rstrip("/")
        self.clob_url = clob_url.rstrip("/")

    async def search_crypto_markets(
        self, symbols: list[str], limit: int = 100
    ) -> list[PolyMarket]:
        rows: list[dict] = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 1) Top volume active markets
            r = await client.get(
                f"{self.gamma_url}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "order": "volume24hr",
                    "ascending": "false",
                },
            )
            r.raise_for_status()
            rows.extend(r.json() if isinstance(r.json(), list) else [])

            # 2) Keyword pulls so crypto markets not in top-80 volume still appear
            queries = ["bitcoin", "ethereum", "solana", "crypto", "btc", "eth"]
            for q in queries:
                try:
                    rr = await client.get(
                        f"{self.gamma_url}/public-search",
                        params={"q": q, "limit_per_type": 15},
                    )
                    if rr.status_code != 200:
                        rr = await client.get(
                            f"{self.gamma_url}/markets",
                            params={
                                "active": "true",
                                "closed": "false",
                                "limit": 25,
                                "tag_slug": q,
                            },
                        )
                    if rr.status_code != 200:
                        continue
                    data = rr.json()
                    if isinstance(data, list):
                        rows.extend(data)
                    elif isinstance(data, dict):
                        for key in ("markets", "events", "results"):
                            if isinstance(data.get(key), list):
                                for item in data[key]:
                                    if isinstance(item, dict) and (
                                        item.get("question") or item.get("title")
                                    ):
                                        rows.append(item)
                                    elif isinstance(item, dict) and "markets" in item:
                                        rows.extend(item.get("markets") or [])
                except Exception as e:
                    log.debug("poly search %s: %s", q, e)

        markets: list[PolyMarket] = []
        seen: set[str] = set()
        for row in rows:
            m = self._parse_market(row)
            if not m or not m.condition_id:
                continue
            if m.condition_id in seen:
                continue
            related = self._match_symbol(m.question, symbols)
            if related:
                m.related_symbol = related
                seen.add(m.condition_id)
                markets.append(m)
        log.info("Polymarket crypto-related markets: %d", len(markets))
        return markets

    def _parse_market(self, row: dict[str, Any]) -> PolyMarket | None:
        question = row.get("question") or row.get("title") or ""
        if not question:
            return None
        yes_p, no_p = 0.5, 0.5
        # outcomePrices can be JSON string
        prices = row.get("outcomePrices")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                prices = None
        if isinstance(prices, list) and len(prices) >= 2:
            yes_p = float(prices[0])
            no_p = float(prices[1])
        tokens = row.get("clobTokenIds")
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except Exception:
                tokens = []
        token_yes = tokens[0] if isinstance(tokens, list) and tokens else ""
        token_no = tokens[1] if isinstance(tokens, list) and len(tokens) > 1 else ""
        return PolyMarket(
            condition_id=str(row.get("conditionId") or row.get("id") or ""),
            question=question,
            slug=str(row.get("slug") or ""),
            token_yes=str(token_yes),
            token_no=str(token_no),
            yes_price=yes_p,
            no_price=no_p,
            volume=float(row.get("volume24hr") or row.get("volume") or 0),
            liquidity=float(row.get("liquidity") or row.get("liquidityNum") or 0),
            end_date=str(row.get("endDate") or row.get("end_date_iso") or "") or None,
            tags=[str(t) for t in (row.get("tags") or [])] if isinstance(row.get("tags"), list) else [],
            raw=row,
        )

    def _match_symbol(self, question: str, symbols: list[str]) -> str | None:
        q = question.lower()
        # Hard negatives: non-crypto topics that collide with tickers
        if re.search(r"\bethiopia\b|\bprime minister\b|\belection\b|\bsenat(e|or)\b", q):
            # still allow if explicit crypto words present
            if not CRYPTO_CONTEXT.search(q) and "bitcoin" not in q and "ethereum" not in q:
                return None

        for sym in symbols:
            patterns = CRYPTO_KEYWORDS.get(sym.upper(), [rf"\b{re.escape(sym.lower())}\b"])
            for p in patterns:
                if re.search(p, q, flags=re.IGNORECASE):
                    # Full names (bitcoin/ethereum/solana) are enough;
                    # bare tickers need crypto context if question is ambiguous
                    if p in (r"\bbitcoin\b", r"\bethereum\b", r"\bsolana\b", r"\bdogecoin\b", r"\bnear protocol\b"):
                        return sym.upper()
                    if CRYPTO_CONTEXT.search(q) or re.search(
                        r"\b(price|above|below|\$|usd|market cap)\b", q, re.I
                    ):
                        return sym.upper()
        return None

    async def get_midpoint(self, token_id: str) -> float | None:
        if not token_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{self.clob_url}/midpoint", params={"token_id": token_id}
                )
                if r.status_code != 200:
                    return None
                data = r.json()
                return float(data.get("mid") or data.get("midpoint") or 0) or None
        except Exception as e:
            log.debug("midpoint %s: %s", token_id[:8], e)
            return None
