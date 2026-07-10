"""Runtime configuration — paper mode by default, never live without explicit flags."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: Literal["paper", "live"] = "paper"
    live_confirm: bool = False
    paper_capital_usd: float = 1000.0

    # paper | binance | mexc | polymarket
    trade_venue: Literal["paper", "binance", "mexc", "polymarket"] = "paper"
    quote_asset: str = "USDT"

    symbols: str = "BTC,ETH,SOL,BNB,DOGE,NEAR"

    half_kelly: bool = True
    max_daily_loss_pct: float = 0.02
    max_consecutive_losses: int = 5
    edge_threshold: float = 0.05
    min_orderbook_liquidity_usd: float = 50_000.0
    max_position_pct: float = 0.05

    # Spot strategy: min MC p_up/p_down distance from 0.5 to enter
    spot_edge_threshold: float = 0.05
    enable_spot_sells: bool = True

    mc_simulations: int = 10_000
    mirofish_agents: int = 200
    mirofish_enabled: bool = True

    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"
    polymarket_private_key: str = ""
    polymarket_funder: str = ""
    polymarket_chain_id: int = 137
    polymarket_signature_type: int = 0

    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True  # default SAFE — testnet until you flip false

    # MEXC
    mexc_api_key: str = ""
    mexc_api_secret: str = ""

    ai_provider: Literal["none", "anthropic", "openai"] = "none"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ai_model: str = "claude-sonnet-4-20250514"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # WhatsApp: none | callmebot | twilio | meta
    whatsapp_provider: str = "none"
    whatsapp_phone: str = ""
    whatsapp_callmebot_apikey: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    twilio_whatsapp_to: str = ""
    whatsapp_meta_token: str = ""
    whatsapp_meta_phone_id: str = ""
    whatsapp_meta_to: str = ""

    otc_feed_url: str = ""
    otc_feed_api_key: str = ""
    otc_simulate: bool = True

    scan_interval_sec: float = 15.0
    # Minimum seconds between ENTER on same symbol (web auto mode)
    trade_cooldown_sec: float = 300.0
    log_level: str = "INFO"
    data_dir: str = "data"

    # Web dashboard — auto-run bot when web starts (no PowerShell needed)
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    web_api_token: str = ""  # optional Bearer token for /api/*
    auto_start_bot: bool = True
    # Use websockets inside web bot (Binance+Bybit; Coinbase ticker-only)
    web_use_websockets: bool = True

    @field_validator("mode", "trade_venue", mode="before")
    @classmethod
    def normalize_str(cls, v: str) -> str:
        return str(v).strip().lower()

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        (p / "paper_trades").mkdir(exist_ok=True)
        (p / "logs").mkdir(exist_ok=True)
        return p

    def has_exchange_keys(self) -> bool:
        v = self.trade_venue
        if v == "binance":
            return bool(self.binance_api_key and self.binance_api_secret)
        if v == "mexc":
            return bool(self.mexc_api_key and self.mexc_api_secret)
        if v == "polymarket":
            return bool(self.polymarket_private_key)
        return False

    def is_live_allowed(self) -> bool:
        """Live only when MODE=live AND LIVE_CONFIRM=true AND venue keys present."""
        if self.mode != "live" or self.live_confirm is not True:
            return False
        if self.trade_venue in ("binance", "mexc", "polymarket"):
            return self.has_exchange_keys()
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
