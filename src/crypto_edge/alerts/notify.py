"""Unified multi-channel notifier: Telegram + WhatsApp + console log."""

from __future__ import annotations

import logging
from typing import Any

from crypto_edge.alerts.telegram import TelegramAlerter
from crypto_edge.alerts.whatsapp import WhatsAppAlerter
from crypto_edge.config import Settings

log = logging.getLogger(__name__)


class MultiNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.telegram = TelegramAlerter(
            settings.telegram_bot_token, settings.telegram_chat_id
        )
        self.whatsapp = WhatsAppAlerter(
            provider=settings.whatsapp_provider,
            phone=settings.whatsapp_phone,
            callmebot_apikey=settings.whatsapp_callmebot_apikey,
            twilio_sid=settings.twilio_account_sid,
            twilio_token=settings.twilio_auth_token,
            twilio_from=settings.twilio_whatsapp_from,
            twilio_to=settings.twilio_whatsapp_to,
            meta_token=settings.whatsapp_meta_token,
            meta_phone_id=settings.whatsapp_meta_phone_id,
            meta_to=settings.whatsapp_meta_to,
        )

    async def broadcast(self, text: str, channels: list[str] | None = None) -> dict[str, Any]:
        channels = channels or ["telegram", "whatsapp"]
        result: dict[str, Any] = {}
        if "telegram" in channels:
            try:
                await self.telegram.send(text)
                result["telegram"] = {"ok": self.telegram.enabled}
            except Exception as e:
                result["telegram"] = {"ok": False, "error": str(e)}
        if "whatsapp" in channels:
            result["whatsapp"] = await self.whatsapp.send(text)
        log.info("notify: %s", text[:120].replace("\n", " | "))
        return result

    async def trade_alert(self, payload: dict[str, Any]) -> dict[str, Any]:
        lines = [
            "🤖 Trade-coin-2026",
            f"• action: {payload.get('action')}",
            f"• symbol: {payload.get('symbol')}",
            f"• side: {payload.get('side')}",
            f"• edge: {payload.get('edge')}",
            f"• size: ${payload.get('size_usd')}",
            f"• mode: {payload.get('mode')}",
        ]
        if payload.get("skip_reason"):
            lines.append(f"• skip: {payload['skip_reason']}")
        if payload.get("question"):
            lines.append(f"• note: {str(payload['question'])[:160]}")
        return await self.broadcast("\n".join(lines))

    async def status_alert(self, title: str, body: str) -> dict[str, Any]:
        return await self.broadcast(f"📡 {title}\n{body}")
