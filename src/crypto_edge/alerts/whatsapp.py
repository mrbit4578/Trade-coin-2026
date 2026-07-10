"""
WhatsApp notifications — pluggable providers.

Supported:
1) callmebot  — free personal alerts (https://www.callmebot.com/blog/free-api-whatsapp-messages/)
2) twilio     — Twilio WhatsApp Business API
3) meta       — Meta Cloud API (WhatsApp Business) — optional
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)


class WhatsAppAlerter:
    def __init__(
        self,
        provider: str = "none",
        # CallMeBot
        phone: str = "",
        callmebot_apikey: str = "",
        # Twilio
        twilio_sid: str = "",
        twilio_token: str = "",
        twilio_from: str = "",
        twilio_to: str = "",
        # Meta Cloud
        meta_token: str = "",
        meta_phone_id: str = "",
        meta_to: str = "",
    ) -> None:
        self.provider = (provider or "none").lower()
        self.phone = phone
        self.callmebot_apikey = callmebot_apikey
        self.twilio_sid = twilio_sid
        self.twilio_token = twilio_token
        self.twilio_from = twilio_from
        self.twilio_to = twilio_to
        self.meta_token = meta_token
        self.meta_phone_id = meta_phone_id
        self.meta_to = meta_to

    @property
    def enabled(self) -> bool:
        if self.provider == "callmebot":
            return bool(self.phone and self.callmebot_apikey)
        if self.provider == "twilio":
            return bool(self.twilio_sid and self.twilio_token and self.twilio_from and self.twilio_to)
        if self.provider == "meta":
            return bool(self.meta_token and self.meta_phone_id and self.meta_to)
        return False

    async def send(self, text: str) -> dict[str, Any]:
        if not self.enabled:
            log.debug("WhatsApp disabled: %s", text[:100])
            return {"ok": False, "reason": "disabled"}
        text = text[:1500]
        try:
            if self.provider == "callmebot":
                return await self._callmebot(text)
            if self.provider == "twilio":
                return await self._twilio(text)
            if self.provider == "meta":
                return await self._meta(text)
        except Exception as e:
            log.warning("WhatsApp send failed: %s", e)
            return {"ok": False, "error": str(e)}
        return {"ok": False, "reason": "unknown provider"}

    async def _callmebot(self, text: str) -> dict[str, Any]:
        # phone like +8490...
        url = (
            "https://api.callmebot.com/whatsapp.php"
            f"?phone={quote(self.phone)}&text={quote(text)}&apikey={quote(self.callmebot_apikey)}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            return {"ok": r.status_code < 400, "status": r.status_code, "body": r.text[:200]}

    async def _twilio(self, text: str) -> dict[str, Any]:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
        data = {
            "From": f"whatsapp:{self.twilio_from}",
            "To": f"whatsapp:{self.twilio_to}",
            "Body": text,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url,
                data=data,
                auth=(self.twilio_sid, self.twilio_token),
            )
            return {"ok": r.status_code < 400, "status": r.status_code, "body": r.text[:300]}

    async def _meta(self, text: str) -> dict[str, Any]:
        url = f"https://graph.facebook.com/v19.0/{self.meta_phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.meta_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": self.meta_to.replace("+", "").replace(" ", ""),
            "type": "text",
            "text": {"body": text},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            return {"ok": r.status_code < 400, "status": r.status_code, "body": r.text[:300]}
