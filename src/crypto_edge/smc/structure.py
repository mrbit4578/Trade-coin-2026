"""
Smart Money Concepts / market structure signals.

Synthesized from workspace blueprint (chuyen gia.txt):
- Market structure (BOS / CHoCH)
- Liquidity sweeps / stop hunts
- Premium / Discount zones
- Confluence scoring (never single-signal entries)
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from crypto_edge.models import StructureSignal


class StructureAnalyzer:
    def analyze(self, symbol: str, prices: Sequence[float]) -> StructureSignal:
        notes: list[str] = []
        if len(prices) < 20:
            return StructureSignal(symbol=symbol, notes=["insufficient history"])

        arr = np.asarray(prices, dtype=float)
        # Swing highs/lows (simple fractal window=3)
        highs_idx, lows_idx = self._swings(arr, w=3)
        trend = self._trend(arr, highs_idx, lows_idx)
        notes.append(f"trend={trend}")

        bos = self._bos(arr, highs_idx, lows_idx, trend)
        choch = self._choch(arr, highs_idx, lows_idx, trend)
        if bos:
            notes.append("BOS detected")
        if choch:
            notes.append("CHoCH detected")

        # Premium / discount relative to recent range
        window = arr[-50:] if len(arr) >= 50 else arr
        hi, lo = float(window.max()), float(window.min())
        mid = (hi + lo) / 2 if hi > lo else float(arr[-1])
        last = float(arr[-1])
        in_discount = last < mid
        in_premium = last > mid
        notes.append("discount" if in_discount else "premium")

        # Stop hunt: wick-like spike beyond swing then reclaim
        stop_hunt = self._stop_hunt(arr, highs_idx, lows_idx)
        if stop_hunt:
            notes.append("stop-hunt / liquidity sweep")

        # RSI-ish momentum confluence (simplified)
        mom = self._momentum_score(arr)
        notes.append(f"momentum={mom:+.2f}")

        score = 0.0
        if trend == "bull":
            score += 0.25
        elif trend == "bear":
            score -= 0.25
        if bos:
            score += 0.15 if trend == "bull" else -0.15
        if choch:
            score += 0.1 * (1 if trend != "range" else 0)
        if in_discount and trend == "bull":
            score += 0.2
            notes.append("bullish confluence: discount + uptrend")
        if in_premium and trend == "bear":
            score -= 0.2
            notes.append("bearish confluence: premium + downtrend")
        if stop_hunt:
            score += 0.1 if in_discount else -0.1
        score += mom * 0.15
        score = float(max(-1.0, min(1.0, score)))

        return StructureSignal(
            symbol=symbol,
            trend=trend,  # type: ignore[arg-type]
            bos=bos,
            choch=choch,
            in_discount=in_discount,
            in_premium=in_premium,
            stop_hunt=stop_hunt,
            score=score,
            notes=notes,
        )

    def _swings(self, arr: np.ndarray, w: int = 3) -> tuple[list[int], list[int]]:
        highs, lows = [], []
        for i in range(w, len(arr) - w):
            left = arr[i - w : i]
            right = arr[i + 1 : i + 1 + w]
            if arr[i] >= left.max() and arr[i] >= right.max():
                highs.append(i)
            if arr[i] <= left.min() and arr[i] <= right.min():
                lows.append(i)
        return highs, lows

    def _trend(
        self, arr: np.ndarray, highs: list[int], lows: list[int]
    ) -> str:
        if len(highs) >= 2 and len(lows) >= 2:
            hh = arr[highs[-1]] > arr[highs[-2]]
            hl = arr[lows[-1]] > arr[lows[-2]]
            lh = arr[highs[-1]] < arr[highs[-2]]
            ll = arr[lows[-1]] < arr[lows[-2]]
            if hh and hl:
                return "bull"
            if lh and ll:
                return "bear"
        # EMA fallback
        if len(arr) >= 30:
            ema_fast = self._ema(arr, 8)
            ema_slow = self._ema(arr, 21)
            if ema_fast[-1] > ema_slow[-1] * 1.001:
                return "bull"
            if ema_fast[-1] < ema_slow[-1] * 0.999:
                return "bear"
        return "range"

    def _bos(
        self, arr: np.ndarray, highs: list[int], lows: list[int], trend: str
    ) -> bool:
        if trend == "bull" and highs:
            return float(arr[-1]) > float(arr[highs[-1]])
        if trend == "bear" and lows:
            return float(arr[-1]) < float(arr[lows[-1]])
        return False

    def _choch(
        self, arr: np.ndarray, highs: list[int], lows: list[int], trend: str
    ) -> bool:
        # Change of character: break opposite structure
        if trend == "bull" and lows:
            return float(arr[-1]) < float(arr[lows[-1]])
        if trend == "bear" and highs:
            return float(arr[-1]) > float(arr[highs[-1]])
        return False

    def _stop_hunt(
        self, arr: np.ndarray, highs: list[int], lows: list[int]
    ) -> bool:
        if len(arr) < 10:
            return False
        recent = arr[-8:]
        prev_low = float(arr[lows[-1]]) if lows else float(arr[-10:].min())
        prev_high = float(arr[highs[-1]]) if highs else float(arr[-10:].max())
        # Spike below low then close back above
        if recent.min() < prev_low and recent[-1] > prev_low:
            return True
        if recent.max() > prev_high and recent[-1] < prev_high:
            return True
        return False

    def _momentum_score(self, arr: np.ndarray) -> float:
        if len(arr) < 15:
            return 0.0
        deltas = np.diff(arr[-15:])
        gains = deltas[deltas > 0].sum()
        losses = -deltas[deltas < 0].sum()
        if losses == 0:
            rsi = 100.0
        else:
            rs = gains / losses
            rsi = 100 - (100 / (1 + rs))
        # map RSI 30..70 → -1..+1-ish around 50
        return float(max(-1.0, min(1.0, (rsi - 50) / 25)))

    def _ema(self, arr: np.ndarray, span: int) -> np.ndarray:
        alpha = 2 / (span + 1)
        out = np.empty_like(arr)
        out[0] = arr[0]
        for i in range(1, len(arr)):
            out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
        return out
