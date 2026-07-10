"""Telegram live alerts."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self, token: str = "", chat_id: str = "") -> None:
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send(self, text: str) -> None:
        if not self.enabled:
            log.debug("Telegram disabled: %s", text[:120])
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": text[:4000],
                        "disable_web_page_preview": True,
                    },
                )
                if r.status_code != 200:
                    log.warning("Telegram error: %s", r.text[:200])
        except Exception as e:
            log.warning("Telegram send failed: %s", e)

    async def signal(self, payload: dict[str, Any]) -> None:
        lines = [
            "📡 Crypto Edge Agent",
            f"action: {payload.get('action')}",
            f"symbol: {payload.get('symbol')}",
            f"side: {payload.get('side')}",
            f"edge: {payload.get('edge')}",
            f"size: ${payload.get('size_usd')}",
            f"mode: {payload.get('mode')}",
        ]
        if payload.get("skip_reason"):
            lines.append(f"skip: {payload['skip_reason']}")
        if payload.get("question"):
            lines.append(f"q: {payload['question'][:200]}")
        await self.send("\n".join(lines))
