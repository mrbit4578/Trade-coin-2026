"""Detect Polymarket probability skew vs spot crypto fair value model."""

from __future__ import annotations

import math
import re
from typing import Optional

from crypto_edge.models import Mispricing, MonteCarloResult, PolyMarket, Side, StructureSignal


class MispricingDetector:
    """
    Map crypto spot + MC + structure into a fair YES probability for a
    Polymarket contract, then compute edge vs market price.
    """

    def detect(
        self,
        market: PolyMarket,
        spot: float,
        mc: MonteCarloResult,
        structure: Optional[StructureSignal] = None,
        otc_bias: float = 0.0,
        edge_threshold: float = 0.05,
    ) -> Optional[Mispricing]:
        if not market.related_symbol or spot <= 0:
            return None

        fair = self._fair_probability(market.question, spot, mc, structure, otc_bias)
        market_prob = market.yes_price if 0 < market.yes_price < 1 else 0.5
        edge_yes = fair - market_prob
        edge_no = (1 - fair) - market.no_price

        if abs(edge_yes) >= abs(edge_no) and abs(edge_yes) >= edge_threshold:
            direction = Side.YES if edge_yes > 0 else Side.NO
            edge = abs(edge_yes)
        elif abs(edge_no) >= edge_threshold:
            direction = Side.YES if edge_no < 0 else Side.NO
            # Prefer trading the cheaper side relative to fair
            if fair > market_prob + edge_threshold:
                direction = Side.YES
                edge = fair - market_prob
            else:
                direction = Side.NO
                edge = (1 - fair) - (1 - market_prob)
                edge = abs(edge)
        else:
            return None

        reasons = [
            f"fair={fair:.3f}",
            f"mkt_yes={market_prob:.3f}",
            f"mc_p_up={mc.p_up:.3f}",
            f"otc_bias={otc_bias:+.2f}",
        ]
        if structure:
            reasons.append(f"trend={structure.trend}")
            reasons.append(f"struct_score={structure.score:.2f}")

        conf = min(0.95, 0.4 + edge * 2 + abs(mc.p_up - 0.5))
        return Mispricing(
            market=market,
            symbol=market.related_symbol,
            fair_prob=fair,
            market_prob=market_prob,
            edge=edge,
            direction=direction,
            confidence=conf,
            reasons=reasons,
        )

    def _fair_probability(
        self,
        question: str,
        spot: float,
        mc: MonteCarloResult,
        structure: Optional[StructureSignal],
        otc_bias: float,
    ) -> float:
        q = question.lower()
        # Threshold markets: "Will BTC be above $X"
        m = re.search(
            r"(above|over|below|under|at least|reach)\s*\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)",
            q,
        )
        base = mc.p_up
        if m:
            direction_word = m.group(1)
            thr = float(m.group(2).replace(",", ""))
            # Use MC expected move + normal approx around spot
            exp = spot * (1 + mc.expected_move_pct)
            vol = max(1e-6, abs(mc.var_95) * spot)
            # P(S > thr) ~ using simple z from expected vs thr
            z = (exp - thr) / vol
            p_above = 0.5 * (1 + math.erf(z / math.sqrt(2)))
            if direction_word in ("above", "over", "at least", "reach"):
                base = p_above
            else:
                base = 1 - p_above
        else:
            # Directional / sentiment markets → lean on MC + structure
            base = mc.p_up

        # Structure adjustment (SMC confluence from chuyen gia blueprint)
        if structure:
            base += structure.score * 0.08
            if structure.trend == "bull":
                base += 0.03
            elif structure.trend == "bear":
                base -= 0.03
            if structure.stop_hunt and structure.choch:
                base += 0.02 if structure.trend == "bull" else -0.02

        base += otc_bias * 0.05
        return float(min(0.97, max(0.03, base)))
