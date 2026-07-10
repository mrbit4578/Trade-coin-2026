"""
Background trade bot service — auto-runs with web dashboard.

Loads market data, runs EdgeAgent loop, caches prices for UI,
broadcasts Telegram/WhatsApp — no PowerShell required.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from crypto_edge.agent.engine import EdgeAgent
from crypto_edge.alerts.notify import MultiNotifier
from crypto_edge.config import reload_settings
from crypto_edge.models import SignalAction, TradeSignal

log = logging.getLogger(__name__)


class BotService:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._agent: Optional[EdgeAgent] = None
        self._running = False
        self._stop = asyncio.Event()
        self.last_signals: list[dict[str, Any]] = []
        self.last_error: str = ""
        self.started_at: Optional[str] = None
        self.cycles: int = 0
        self.history: list[dict[str, Any]] = []
        self.max_history = 200
        self.live_prices: dict[str, dict[str, Any]] = {}
        self.activity: deque[dict[str, Any]] = deque(maxlen=150)
        self.enter_count: int = 0
        self.skip_count: int = 0

    @property
    def running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def _log_activity(self, kind: str, message: str, **extra: Any) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "message": message,
            **extra,
        }
        self.activity.appendleft(row)

    def status(self) -> dict[str, Any]:
        settings = reload_settings()
        equity = settings.paper_capital_usd
        mode = "paper"
        mids: dict[str, float] = {}
        if self._agent:
            equity = self._agent.risk.state.equity
            mode = self._agent.exec.mode
            try:
                mids = self._agent.hub.mid_prices()
            except Exception:
                mids = {}
        return {
            "running": self.running,
            "started_at": self.started_at,
            "cycles": self.cycles,
            "mode": mode,
            "venue": settings.trade_venue,
            "config_mode": settings.mode,
            "live_allowed": settings.is_live_allowed(),
            "symbols": settings.symbol_list,
            "equity": equity,
            "last_error": self.last_error,
            "last_signals": self.last_signals[-20:],
            "live_prices": self.live_prices or {
                k: {"price": v, "source": "hub"} for k, v in mids.items() if v
            },
            "enter_count": self.enter_count,
            "skip_count": self.skip_count,
            "activity": list(self.activity)[:40],
            "auto_start_bot": settings.auto_start_bot,
            "scan_interval_sec": settings.scan_interval_sec,
            "trade_cooldown_sec": settings.trade_cooldown_sec,
            "telegram_enabled": bool(
                settings.telegram_bot_token and settings.telegram_chat_id
            ),
            "whatsapp_enabled": settings.whatsapp_provider != "none",
        }

    def _refresh_prices_from_agent(self) -> None:
        if not self._agent:
            return
        try:
            mids = self._agent.hub.mid_prices()
            for sym, px in mids.items():
                if px and px > 0:
                    self.live_prices[sym] = {
                        "price": px,
                        "source": "live-hub",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
        except Exception as e:
            log.debug("price cache: %s", e)

    async def start(self, use_ws: bool | None = None) -> dict[str, Any]:
        if self.running:
            return {"ok": True, "status": self.status(), "note": "already running"}
        settings = reload_settings()
        if settings.mode == "live" and not settings.is_live_allowed():
            return {
                "ok": False,
                "error": "LIVE blocked: need MODE=live + LIVE_CONFIRM=true + API keys",
            }
        if use_ws is None:
            use_ws = settings.web_use_websockets
        self._stop = asyncio.Event()
        self._running = True
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.last_error = ""
        self.cycles = 0
        self.enter_count = 0
        self.skip_count = 0
        self._task = asyncio.create_task(self._loop(use_ws), name="trade-bot")
        self._log_activity(
            "system",
            f"Bot STARTED venue={settings.trade_venue} mode={settings.mode}",
        )
        notifier = MultiNotifier(settings)
        try:
            await notifier.status_alert(
                "Bot STARTED",
                f"venue={settings.trade_venue} mode={settings.mode} "
                f"symbols={settings.symbol_list} (web auto)",
            )
        except Exception:
            pass
        return {"ok": True, "status": self.status()}

    async def stop(self) -> dict[str, Any]:
        self._stop.set()
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._agent:
            try:
                await self._agent.stop()
            except Exception:
                pass
            self._agent = None
        self._log_activity("system", f"Bot STOPPED cycles={self.cycles}")
        settings = reload_settings()
        try:
            await MultiNotifier(settings).status_alert(
                "Bot STOPPED", f"cycles={self.cycles}"
            )
        except Exception:
            pass
        return {"ok": True, "status": self.status()}

    async def run_once(self) -> dict[str, Any]:
        settings = reload_settings()
        agent = EdgeAgent(settings, use_ws=False)
        await agent.start()
        try:
            sigs = await agent.scan_once()
            payload = [self._sig_dict(s) for s in sigs]
            self.last_signals = payload
            self._push_history(payload)
            for s in sigs:
                if s.action == SignalAction.ENTER:
                    self.enter_count += 1
                elif s.action == SignalAction.SKIP:
                    self.skip_count += 1
            # cache prices
            for sym, px in agent.hub.mid_prices().items():
                if px > 0:
                    self.live_prices[sym] = {
                        "price": px,
                        "source": "scan-once",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
            self._log_activity("scan", f"once: {len(payload)} signals")
            return {
                "ok": True,
                "signals": payload,
                "equity": agent.risk.state.equity,
                "prices": self.live_prices,
            }
        finally:
            await agent.stop()

    async def _loop(self, use_ws: bool) -> None:
        settings = reload_settings()
        notifier = MultiNotifier(settings)
        agent = EdgeAgent(settings, use_ws=use_ws)
        self._agent = agent
        try:
            self._log_activity("system", "Loading market data (warm-start)…")
            await agent.start()
            self._refresh_prices_from_agent()
            self._log_activity(
                "system",
                f"Data ready: { {k: round(v, 4) for k, v in agent.hub.mid_prices().items() if v} }",
            )
            while not self._stop.is_set():
                self.cycles += 1
                try:
                    sigs = await agent.scan_once()
                    payload = [self._sig_dict(s) for s in sigs]
                    self.last_signals = payload
                    self._push_history(payload)
                    self._refresh_prices_from_agent()
                    for s in sigs:
                        if s.action == SignalAction.ENTER:
                            self.enter_count += 1
                            self._log_activity(
                                "enter",
                                f"{s.symbol} {s.side.value} edge={s.edge:.3f} "
                                f"${s.size_usd}",
                                symbol=s.symbol,
                            )
                            await notifier.trade_alert(
                                {
                                    "action": s.action.value,
                                    "symbol": s.symbol,
                                    "side": s.side.value,
                                    "edge": f"{s.edge:.3f}",
                                    "size_usd": s.size_usd,
                                    "mode": agent.exec.mode,
                                    "question": s.market_question,
                                }
                            )
                        elif s.action == SignalAction.SKIP:
                            self.skip_count += 1
                    if self.cycles % 3 == 0:
                        self._log_activity(
                            "cycle",
                            f"cycle#{self.cycles} signals={len(payload)} "
                            f"equity=${agent.risk.state.equity:.2f}",
                        )
                except Exception as e:
                    self.last_error = str(e)
                    log.exception("bot cycle error: %s", e)
                    self._log_activity("error", str(e)[:200])
                    await notifier.status_alert("Bot ERROR", str(e)[:500])
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=settings.scan_interval_sec
                    )
                    break
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.last_error = str(e)
            log.exception("bot loop fatal: %s", e)
            self._log_activity("error", f"fatal: {e}")
        finally:
            self._running = False
            try:
                await agent.stop()
            except Exception:
                pass

    def _sig_dict(self, s: TradeSignal) -> dict[str, Any]:
        return {
            "action": s.action.value,
            "symbol": s.symbol,
            "side": s.side.value,
            "edge": round(s.edge, 4),
            "size_usd": s.size_usd,
            "fair_prob": round(s.fair_prob, 4),
            "skip_reason": s.skip_reason,
            "question": s.market_question,
            "ts": s.ts.isoformat() if s.ts else None,
        }

    def _push_history(self, payload: list[dict[str, Any]]) -> None:
        self.history.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "cycle": self.cycles,
                "signals": payload,
            }
        )
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]


bot_service = BotService()
