"""
Background trade bot service — start/stop from web UI or CLI.

Runs EdgeAgent loop, stores last signals, broadcasts Telegram/WhatsApp.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from crypto_edge.agent.engine import EdgeAgent
from crypto_edge.alerts.notify import MultiNotifier
from crypto_edge.config import Settings, reload_settings
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

    @property
    def running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def status(self) -> dict[str, Any]:
        settings = reload_settings()
        equity = None
        mode = "paper"
        if self._agent:
            equity = self._agent.risk.state.equity
            mode = self._agent.exec.mode
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
            "telegram_enabled": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "whatsapp_enabled": settings.whatsapp_provider != "none",
        }

    async def start(self, use_ws: bool = True) -> dict[str, Any]:
        if self.running:
            return {"ok": False, "error": "already running"}
        settings = reload_settings()
        if settings.mode == "live" and not settings.is_live_allowed():
            return {
                "ok": False,
                "error": "LIVE blocked: need MODE=live + LIVE_CONFIRM=true + API keys",
            }
        self._stop = asyncio.Event()
        self._running = True
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.last_error = ""
        self.cycles = 0
        self._task = asyncio.create_task(self._loop(use_ws), name="trade-bot")
        notifier = MultiNotifier(settings)
        await notifier.status_alert(
            "Bot STARTED",
            f"venue={settings.trade_venue} mode={settings.mode} symbols={settings.symbol_list}",
        )
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
        settings = reload_settings()
        await MultiNotifier(settings).status_alert("Bot STOPPED", f"cycles={self.cycles}")
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
            return {"ok": True, "signals": payload, "equity": agent.risk.state.equity}
        finally:
            await agent.stop()

    async def _loop(self, use_ws: bool) -> None:
        settings = reload_settings()
        notifier = MultiNotifier(settings)
        agent = EdgeAgent(settings, use_ws=use_ws)
        self._agent = agent
        try:
            await agent.start()
            while not self._stop.is_set():
                self.cycles += 1
                try:
                    sigs = await agent.scan_once()
                    payload = [self._sig_dict(s) for s in sigs]
                    self.last_signals = payload
                    self._push_history(payload)
                    for s in sigs:
                        if s.action == SignalAction.ENTER:
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
                except Exception as e:
                    self.last_error = str(e)
                    log.exception("bot cycle error: %s", e)
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


# Singleton for web + CLI
bot_service = BotService()
