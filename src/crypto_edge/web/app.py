"""
FastAPI web app — full auto mode.

Opening the dashboard:
  - auto-starts bot (AUTO_START_BOT=true default)
  - loads market data in background
  - streams status/prices/activity to browser
  - no PowerShell needed after `python -m crypto_edge.cli web`
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from crypto_edge import __version__
from crypto_edge.alerts.notify import MultiNotifier
from crypto_edge.bot.service import bot_service
from crypto_edge.config import PROJECT_ROOT, reload_settings
from crypto_edge.feeds.rest_fallback import fetch_binance_tickers

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


async def _auth(authorization: Optional[str] = Header(default=None)) -> None:
    settings = reload_settings()
    token = settings.web_api_token
    if not token:
        return
    if not authorization or authorization.replace("Bearer ", "").strip() != token:
        raise HTTPException(status_code=401, detail="Unauthorized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = reload_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    log.info(
        "Trade-coin-2026 web v%s | auto_start=%s | port=%s",
        __version__,
        settings.auto_start_bot,
        settings.web_port,
    )
    # Always warm REST prices for dashboard even before bot starts
    try:
        ticks = await fetch_binance_tickers(settings.symbol_list)
        for t in ticks:
            bot_service.live_prices[t.symbol] = {
                "price": t.price,
                "bid": t.bid,
                "ask": t.ask,
                "source": "boot-rest",
            }
        log.info("Boot prices: %s", {t.symbol: t.price for t in ticks})
    except Exception as e:
        log.warning("Boot price warm-up failed: %s", e)

    if settings.auto_start_bot:
        result = await bot_service.start(use_ws=settings.web_use_websockets)
        log.info("Auto-start bot: %s", result.get("ok"))
    yield
    if bot_service.running:
        await bot_service.stop()


app = FastAPI(
    title="Trade-coin-2026",
    description="Crypto edge agent — web auto bot, Telegram & WhatsApp",
    version=__version__,
    lifespan=lifespan,
)

static_dir = WEB_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    s = reload_settings()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "version": __version__,
            "status": bot_service.status(),
            "venue": s.trade_venue,
            "mode": s.mode,
            "auto_start": s.auto_start_bot,
        },
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": __version__,
        "running": bot_service.running,
        "cycles": bot_service.cycles,
    }


@app.get("/api/status")
async def api_status(_: None = Depends(_auth)):
    return bot_service.status()


@app.post("/api/bot/start")
async def api_bot_start(_: None = Depends(_auth)):
    s = reload_settings()
    return await bot_service.start(use_ws=s.web_use_websockets)


@app.post("/api/bot/stop")
async def api_bot_stop(_: None = Depends(_auth)):
    return await bot_service.stop()


@app.post("/api/bot/once")
async def api_bot_once(_: None = Depends(_auth)):
    return await bot_service.run_once()


@app.get("/api/prices")
async def api_prices(_: None = Depends(_auth)):
    """Prefer live hub cache from running bot; fallback REST."""
    cached = bot_service.live_prices
    if cached:
        return {"ok": True, "source": "cache", "prices": cached}
    s = reload_settings()
    try:
        ticks = await fetch_binance_tickers(s.symbol_list)
        prices = {
            t.symbol: {
                "price": t.price,
                "bid": t.bid,
                "ask": t.ask,
                "volume_24h": t.volume_24h,
                "exchange": t.exchange,
            }
            for t in ticks
        }
        bot_service.live_prices.update(prices)
        return {"ok": True, "source": "rest", "prices": prices}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)


@app.get("/api/activity")
async def api_activity(_: None = Depends(_auth)):
    return {"ok": True, "activity": list(bot_service.activity)[:80]}


@app.get("/api/history")
async def api_history(_: None = Depends(_auth)):
    return {"ok": True, "history": bot_service.history[-50:]}


@app.get("/api/trades")
async def api_trades(_: None = Depends(_auth)):
    s = reload_settings()
    path = s.data_path / "paper_trades" / "ledger.jsonl"
    rows = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[-100:]:
            try:
                import json

                rows.append(json.loads(line))
            except Exception:
                pass
    return {"ok": True, "trades": rows}


class NotifyBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    channels: list[str] = Field(default_factory=lambda: ["telegram", "whatsapp"])


@app.post("/api/notify/test")
async def api_notify_test(body: NotifyBody, _: None = Depends(_auth)):
    s = reload_settings()
    n = MultiNotifier(s)
    result = await n.broadcast(f"🧪 Test Trade-coin-2026\n{body.text}", body.channels)
    return {"ok": True, "result": result}


@app.get("/api/config")
async def api_config(_: None = Depends(_auth)):
    s = reload_settings()
    return {
        "mode": s.mode,
        "trade_venue": s.trade_venue,
        "symbols": s.symbol_list,
        "mc_simulations": s.mc_simulations,
        "edge_threshold": s.edge_threshold,
        "spot_edge_threshold": s.spot_edge_threshold,
        "max_daily_loss_pct": s.max_daily_loss_pct,
        "max_consecutive_losses": s.max_consecutive_losses,
        "max_position_pct": s.max_position_pct,
        "binance_testnet": s.binance_testnet,
        "live_allowed": s.is_live_allowed(),
        "scan_interval_sec": s.scan_interval_sec,
        "trade_cooldown_sec": s.trade_cooldown_sec,
        "auto_start_bot": s.auto_start_bot,
        "telegram_configured": bool(s.telegram_bot_token and s.telegram_chat_id),
        "whatsapp_provider": s.whatsapp_provider,
        "whatsapp_configured": s.whatsapp_provider != "none",
        "paper_capital_usd": s.paper_capital_usd,
        "project_root": str(PROJECT_ROOT),
    }


def create_app() -> FastAPI:
    return app
