"""Optional LLM reasoning over full signal context (Claude / OpenAI)."""

from __future__ import annotations

import json
import logging
from typing import Any

from crypto_edge.config import Settings

log = logging.getLogger(__name__)


class AIReasoner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def critique(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Returns {approve: bool, confidence: float, rationale: str}.
        If AI_PROVIDER=none, returns heuristic approval.
        """
        if self.settings.ai_provider == "none":
            return self._heuristic(context)

        prompt = (
            "You are a risk-aware crypto prediction-market analyst. "
            "Given JSON context (orderbook, OTC, SMC, Monte Carlo, Polymarket), "
            "decide approve=true only if edge is robust and signals align. "
            "Reply JSON keys: approve, confidence, rationale.\n\n"
            f"{json.dumps(context, default=str)[:12000]}"
        )
        try:
            if self.settings.ai_provider == "anthropic" and self.settings.anthropic_api_key:
                return await self._anthropic(prompt)
            if self.settings.ai_provider == "openai" and self.settings.openai_api_key:
                return await self._openai(prompt)
        except Exception as e:
            log.warning("AI reasoner failed: %s", e)
        return self._heuristic(context)

    def _heuristic(self, context: dict[str, Any]) -> dict[str, Any]:
        edge = float(context.get("edge") or 0)
        conflict = bool(context.get("conflict"))
        approve = edge >= 0.05 and not conflict
        return {
            "approve": approve,
            "confidence": min(0.9, abs(edge) * 4),
            "rationale": "heuristic gate (no LLM configured)",
        }

    async def _anthropic(self, prompt: str) -> dict[str, Any]:
        import httpx

        headers = {
            "x-api-key": self.settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": self.settings.ai_model,
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages", headers=headers, json=body
            )
            r.raise_for_status()
            data = r.json()
        text = data["content"][0]["text"]
        return self._parse_json(text)

    async def _openai(self, prompt: str) -> dict[str, Any]:
        import httpx

        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "content-type": "application/json",
        }
        body = {
            "model": self.settings.ai_model
            if "gpt" in self.settings.ai_model
            else "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        text = data["choices"][0]["message"]["content"]
        return self._parse_json(text)

    def _parse_json(self, text: str) -> dict[str, Any]:
        import re

        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {"approve": False, "confidence": 0.0, "rationale": text[:300]}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {"approve": False, "confidence": 0.0, "rationale": text[:300]}
