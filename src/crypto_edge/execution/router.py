"""Route orders to paper (default) or live Binance / MEXC / Polymarket."""

from __future__ import annotations

import logging
from typing import Any, Optional, Union

from crypto_edge.config import Settings
from crypto_edge.execution.paper import PaperBroker
from crypto_edge.models import TradeRecord, TradeSignal

log = logging.getLogger(__name__)


class ExecutionRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.paper = PaperBroker(
            capital=settings.paper_capital_usd,
            path=settings.data_path / "paper_trades" / "ledger.jsonl",
        )
        self.live_client: Any = None
        self.venue = settings.trade_venue
        if settings.is_live_allowed():
            log.warning(
                "LIVE MODE ENABLED venue=%s — real capital at risk", self.venue
            )
            try:
                self._init_live()
            except Exception as e:
                log.error("Live client init failed, staying paper: %s", e)
                self.live_client = None

    def _init_live(self) -> None:
        venue = self.settings.trade_venue
        if venue == "binance":
            from crypto_edge.execution.binance_spot import BinanceSpotClient

            self.live_client = BinanceSpotClient(
                api_key=self.settings.binance_api_key,
                api_secret=self.settings.binance_api_secret,
                testnet=self.settings.binance_testnet,
                quote=self.settings.quote_asset,
            )
            log.warning(
                "Binance client ready (testnet=%s)", self.settings.binance_testnet
            )
        elif venue == "mexc":
            from crypto_edge.execution.mexc_spot import MexcSpotClient

            self.live_client = MexcSpotClient(
                api_key=self.settings.mexc_api_key,
                api_secret=self.settings.mexc_api_secret,
                quote=self.settings.quote_asset,
            )
            log.warning("MEXC client ready")
        elif venue == "polymarket":
            log.warning(
                "Polymarket live: wire py-clob-client-v2 — still stub for safety"
            )
            self.live_client = None
        else:
            raise ValueError(f"Unknown trade venue: {venue}")

    @property
    def mode(self) -> str:
        if self.settings.is_live_allowed() and self.live_client is not None:
            return f"live-{self.venue}"
        return "paper"

    async def execute(self, signal: TradeSignal) -> TradeRecord:
        if self.mode.startswith("live") and self.live_client is not None:
            if hasattr(self.live_client, "execute_signal"):
                return await self.live_client.execute_signal(signal)
            raise NotImplementedError(f"Live venue {self.venue} not executable")
        return self.paper.execute(signal)

    def execute_sync(self, signal: TradeSignal) -> TradeRecord:
        """Paper path used when caller is sync."""
        return self.paper.execute(signal)
