"""
Main agent loop:
feeds → orderbook/OTC → SMC → Monte Carlo (10k) → MiroFish graph
→ spot (Binance/MEXC) OR Polymarket mispricing
→ risk gates → Bayesian size → paper/live → Telegram
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from rich.console import Console
from rich.table import Table

from crypto_edge.ai.reasoner import AIReasoner
from crypto_edge.alerts.notify import MultiNotifier
from crypto_edge.bayesian.winrate import BayesianWinRate
from crypto_edge.config import Settings, get_settings
from crypto_edge.execution.router import ExecutionRouter
from crypto_edge.feeds.aggregator import MarketDataHub
from crypto_edge.models import Side, SignalAction, TradeSignal
from crypto_edge.orderbook.aggregator import ClosedBookProxy
from crypto_edge.otc.feed import OTCFeed
from crypto_edge.polymarket.client import PolymarketClient
from crypto_edge.polymarket.mispricing import MispricingDetector
from crypto_edge.risk.manager import RiskManager
from crypto_edge.simulation.mirofish import MiroFishGraph
from crypto_edge.simulation.monte_carlo import MonteCarloEngine
from crypto_edge.smc.structure import StructureAnalyzer

log = logging.getLogger(__name__)
console = Console()


class EdgeAgent:
    def __init__(self, settings: Optional[Settings] = None, use_ws: bool = True) -> None:
        self.settings = settings or get_settings()
        self.hub = MarketDataHub(self.settings.symbol_list, use_websockets=use_ws)
        self.otc = OTCFeed(
            self.settings.symbol_list,
            url=self.settings.otc_feed_url,
            api_key=self.settings.otc_feed_api_key,
            simulate=self.settings.otc_simulate,
        )
        self.book_proxy = ClosedBookProxy()
        self.smc = StructureAnalyzer()
        self.mc = MonteCarloEngine(n_sims=self.settings.mc_simulations)
        self.miro = MiroFishGraph(n_agents=self.settings.mirofish_agents)
        self.poly = PolymarketClient(
            gamma_url=self.settings.polymarket_gamma_url,
            clob_url=self.settings.polymarket_clob_url,
        )
        self.mispricing = MispricingDetector()
        self.risk = RiskManager(
            equity=self.settings.paper_capital_usd,
            half_kelly=self.settings.half_kelly,
            max_daily_loss_pct=self.settings.max_daily_loss_pct,
            max_consecutive_losses=self.settings.max_consecutive_losses,
            max_position_pct=self.settings.max_position_pct,
            min_liquidity_usd=self.settings.min_orderbook_liquidity_usd,
            edge_threshold=self.settings.edge_threshold,
        )
        self.bayes = BayesianWinRate()
        self.exec = ExecutionRouter(self.settings)
        self.ai = AIReasoner(self.settings)
        self.notify = MultiNotifier(self.settings)
        self._markets_cache = []
        self._cycles = 0

    @property
    def use_spot(self) -> bool:
        return self.settings.trade_venue in ("binance", "mexc", "paper")

    @property
    def use_polymarket(self) -> bool:
        return self.settings.trade_venue in ("polymarket",)

    async def start(self) -> None:
        await self.hub.start()
        if self.use_polymarket or self.settings.trade_venue == "paper":
            try:
                self._markets_cache = await self.poly.search_crypto_markets(
                    self.settings.symbol_list, limit=80
                )
            except Exception as e:
                log.warning("Polymarket fetch failed (offline?): %s", e)
                self._markets_cache = []

    async def stop(self) -> None:
        await self.hub.stop()

    async def scan_once(self) -> list[TradeSignal]:
        self._cycles += 1
        signals: list[TradeSignal] = []
        mids = self.hub.mid_prices()
        await self.otc.poll(mids)

        if self.use_polymarket and self._cycles % 20 == 1:
            try:
                self._markets_cache = await self.poly.search_crypto_markets(
                    self.settings.symbol_list, limit=80
                )
            except Exception as e:
                log.debug("poly refresh: %s", e)

        for sym in self.settings.symbol_list:
            spot = mids.get(sym) or 0.0
            if spot <= 0:
                continue
            books = self.hub.books.get(sym, {})
            otc_rows = self.otc.recent(sym, minutes=90)
            book_score = self.book_proxy.score(books, otc_rows)
            history = self.hub.history(sym)
            if len(history) < 30:
                history = history + [spot] * (30 - len(history))

            structure = self.smc.analyze(sym, history)
            mc = self.mc.run(
                history,
                market_yes_prob=0.5,
                imbalance=float(book_score.get("imbalance") or 0),
                otc_bias=self.otc.net_bias(sym),
                structure=structure,
            )
            if self.settings.mirofish_enabled:
                graph = self.miro.build(
                    symbol=sym,
                    spot=spot,
                    books=books,
                    otc=otc_rows,
                    structure=structure,
                    poly_yes=0.5,
                    mc_p_up=mc.p_up,
                )
                blended = self.miro.blend_with_mc(mc.p_up, graph)
                mc.p_up = blended
                mc.p_down = 1 - blended
                mc.p_win_yes = blended
                mc.p_win_no = 1 - blended

            if self.use_spot:
                sig = await self._spot_decision(sym, spot, mc, structure, book_score)
                if sig:
                    signals.append(sig)

            if self.use_polymarket:
                poly_sigs = await self._poly_decisions(
                    sym, spot, history, structure, books, otc_rows, book_score
                )
                signals.extend(poly_sigs)

            if self._cycles % 5 == 0 and not signals:
                log.info(
                    "%s spot=%.4f mc_p_up=%.3f struct=%s depth=$%.0f venue=%s",
                    sym,
                    spot,
                    mc.p_up,
                    structure.trend,
                    book_score.get("depth_usd") or 0,
                    self.settings.trade_venue,
                )

        return signals

    async def _spot_decision(
        self, sym, spot, mc, structure, book_score
    ) -> Optional[TradeSignal]:
        """Spot BUY/SELL from MC edge + SMC confluence (Binance/MEXC/paper)."""
        thr = self.settings.spot_edge_threshold
        edge_up = mc.p_up - 0.5
        edge_dn = mc.p_down - 0.5

        side: Optional[Side] = None
        edge = 0.0
        if edge_up >= thr and structure.score >= -0.15:
            side = Side.BUY
            edge = edge_up
            # prefer bullish structure
            if structure.trend == "bear" and structure.score < -0.25:
                return TradeSignal(
                    action=SignalAction.SKIP,
                    symbol=sym,
                    market_question=f"spot {sym}/USDT",
                    side=Side.BUY,
                    edge=edge,
                    fair_prob=mc.p_up,
                    market_prob=0.5,
                    skip_reason="conflict: MC up but structure bear",
                    mc=mc,
                    structure=structure,
                    bayesian_win_rate=self.bayes.mean,
                )
        elif edge_dn >= thr and self.settings.enable_spot_sells and structure.score <= 0.15:
            side = Side.SELL
            edge = edge_dn
            if structure.trend == "bull" and structure.score > 0.25:
                return TradeSignal(
                    action=SignalAction.SKIP,
                    symbol=sym,
                    market_question=f"spot {sym}/USDT",
                    side=Side.SELL,
                    edge=edge,
                    fair_prob=mc.p_down,
                    market_prob=0.5,
                    skip_reason="conflict: MC down but structure bull",
                    mc=mc,
                    structure=structure,
                    bayesian_win_rate=self.bayes.mean,
                )
        else:
            return None

        conflict = False
        liq = float(book_score.get("depth_usd") or 0)
        ok, reason = self.risk.can_trade(edge, liq, conflict=conflict)
        if not ok:
            return TradeSignal(
                action=SignalAction.SKIP,
                symbol=sym,
                market_question=f"spot {sym}/USDT",
                side=side,
                edge=edge,
                fair_prob=mc.p_up if side == Side.BUY else mc.p_down,
                market_prob=0.5,
                skip_reason=reason,
                mc=mc,
                structure=structure,
                bayesian_win_rate=self.bayes.mean,
            )

        win_p = mc.p_up if side == Side.BUY else mc.p_down
        win_p = 0.7 * win_p + 0.3 * self.bayes.mean
        # assume ~1:1 RR for spot short-horizon
        size = self.risk.position_size(edge, win_p, odds_net=1.0)
        size *= self.bayes.size_multiplier()
        size = min(size, self.risk.state.equity * self.settings.max_position_pct)
        if size < 5:
            return TradeSignal(
                action=SignalAction.SKIP,
                symbol=sym,
                market_question=f"spot {sym}/USDT",
                side=side,
                edge=edge,
                fair_prob=win_p,
                market_prob=0.5,
                skip_reason="size too small",
                mc=mc,
                structure=structure,
                bayesian_win_rate=self.bayes.mean,
            )

        ai = await self.ai.critique(
            {
                "venue": self.settings.trade_venue,
                "symbol": sym,
                "side": side.value,
                "edge": edge,
                "spot": spot,
                "mc": mc.model_dump(),
                "structure": structure.model_dump(),
                "book": {k: v for k, v in book_score.items() if k != "agg_book"},
            }
        )
        if not ai.get("approve", True):
            return TradeSignal(
                action=SignalAction.SKIP,
                symbol=sym,
                market_question=f"spot {sym}/USDT",
                side=side,
                edge=edge,
                fair_prob=win_p,
                market_prob=0.5,
                skip_reason=f"AI veto: {ai.get('rationale', '')[:120]}",
                mc=mc,
                structure=structure,
                bayesian_win_rate=self.bayes.mean,
            )

        sig = TradeSignal(
            action=SignalAction.ENTER,
            symbol=sym,
            market_question=f"spot {sym}/{self.settings.quote_asset}",
            side=side,
            edge=edge,
            fair_prob=win_p,
            market_prob=0.5,
            size_usd=round(size, 2),
            mc=mc,
            structure=structure,
            bayesian_win_rate=self.bayes.mean,
        )
        try:
            trade = await self.exec.execute(sig)
        except Exception as e:
            log.error("execute failed: %s", e)
            await self.notify.status_alert("Order failed", f"{sym}: {e}")
            sig.action = SignalAction.SKIP
            sig.skip_reason = f"exec error: {e}"
            return sig

        await self.notify.trade_alert(
            {
                "action": "ENTER",
                "symbol": sym,
                "side": sig.side.value,
                "edge": f"{sig.edge:.3f}",
                "size_usd": sig.size_usd,
                "mode": self.exec.mode,
                "question": sig.market_question,
            }
        )
        log.info(
            "ENTER spot %s %s edge=%.3f size=$%.2f id=%s mode=%s",
            sym,
            sig.side.value,
            sig.edge,
            sig.size_usd,
            trade.id,
            self.exec.mode,
        )
        return sig

    async def _poly_decisions(
        self, sym, spot, history, structure, books, otc_rows, book_score
    ) -> list[TradeSignal]:
        signals: list[TradeSignal] = []
        markets = [m for m in self._markets_cache if m.related_symbol == sym]
        for market in markets[:3]:
            mc = self.mc.run(
                history,
                market_yes_prob=market.yes_price,
                imbalance=float(book_score.get("imbalance") or 0),
                otc_bias=self.otc.net_bias(sym),
                structure=structure,
            )
            if self.settings.mirofish_enabled:
                graph = self.miro.build(
                    symbol=sym,
                    spot=spot,
                    books=books,
                    otc=otc_rows,
                    structure=structure,
                    poly_yes=market.yes_price,
                    mc_p_up=mc.p_up,
                )
                blended = self.miro.blend_with_mc(mc.p_up, graph)
                mc.p_up = blended
                mc.p_down = 1 - blended
                mc.p_win_yes = blended
                mc.p_win_no = 1 - blended
                mc.edge_vs_market = blended - market.yes_price

            miss = self.mispricing.detect(
                market=market,
                spot=spot,
                mc=mc,
                structure=structure,
                otc_bias=self.otc.net_bias(sym),
                edge_threshold=self.settings.edge_threshold,
            )
            if not miss:
                continue

            conflict = False
            if miss.direction.value == "YES" and structure.score < -0.45:
                conflict = True
            if miss.direction.value == "NO" and structure.score > 0.45:
                conflict = True

            liq = float(book_score.get("depth_usd") or 0) + float(market.liquidity or 0)
            ok, reason = self.risk.can_trade(miss.edge, liq, conflict=conflict)
            if not ok:
                signals.append(
                    TradeSignal(
                        action=SignalAction.SKIP,
                        symbol=sym,
                        market_question=market.question,
                        side=miss.direction,
                        edge=miss.edge,
                        fair_prob=miss.fair_prob,
                        market_prob=miss.market_prob,
                        skip_reason=reason,
                        mc=mc,
                        structure=structure,
                        bayesian_win_rate=self.bayes.mean,
                    )
                )
                continue

            entry = (
                miss.market_prob
                if miss.direction.value == "YES"
                else (1 - miss.market_prob)
            )
            entry = max(0.05, min(0.95, entry))
            b = (1 - entry) / entry
            win_p = miss.fair_prob if miss.direction.value == "YES" else (1 - miss.fair_prob)
            win_p = 0.7 * win_p + 0.3 * self.bayes.mean
            size = self.risk.position_size(miss.edge, win_p, odds_net=b)
            size *= self.bayes.size_multiplier()
            size = min(size, self.risk.state.equity * self.settings.max_position_pct)
            if size < 5:
                continue

            sig = TradeSignal(
                action=SignalAction.ENTER,
                symbol=sym,
                market_question=market.question,
                side=miss.direction,
                edge=miss.edge,
                fair_prob=miss.fair_prob,
                market_prob=miss.market_prob,
                size_usd=round(size, 2),
                mc=mc,
                structure=structure,
                bayesian_win_rate=self.bayes.mean,
            )
            trade = await self.exec.execute(sig)
            await self.notify.trade_alert(
                {
                    "action": "ENTER",
                    "symbol": sym,
                    "side": sig.side.value,
                    "edge": f"{sig.edge:.3f}",
                    "size_usd": sig.size_usd,
                    "mode": self.exec.mode,
                    "question": market.question,
                }
            )
            log.info(
                "ENTER poly %s %s edge=%.3f size=$%.2f id=%s",
                sym,
                sig.side.value,
                sig.edge,
                sig.size_usd,
                trade.id,
            )
            signals.append(sig)
        return signals

    async def run_forever(self, max_cycles: int | None = None) -> None:
        await self.start()
        console.print(
            f"[bold green]Crypto Edge Agent[/] mode={self.exec.mode} "
            f"venue={self.settings.trade_venue} "
            f"symbols={self.settings.symbol_list} mc={self.settings.mc_simulations}"
        )
        cycles = 0
        try:
            while max_cycles is None or cycles < max_cycles:
                cycles += 1
                try:
                    sigs = await self.scan_once()
                    self._print_cycle(sigs)
                except Exception as e:
                    log.exception("scan error: %s", e)
                    await self.notify.status_alert("Scan error", str(e)[:500])
                await asyncio.sleep(self.settings.scan_interval_sec)
        finally:
            await self.stop()

    def _print_cycle(self, signals: list[TradeSignal]) -> None:
        table = Table(
            title=(
                f"Scan #{self._cycles} | {self.exec.mode} | "
                f"equity=${self.risk.state.equity:,.2f}"
            )
        )
        table.add_column("Action")
        table.add_column("Sym")
        table.add_column("Side")
        table.add_column("Edge")
        table.add_column("Size")
        table.add_column("Note")
        if not signals:
            table.add_row("-", "-", "-", "-", "-", "no edge this cycle")
        for s in signals[:12]:
            table.add_row(
                s.action.value,
                s.symbol,
                s.side.value,
                f"{s.edge:.3f}",
                f"${s.size_usd:.2f}" if s.size_usd else "-",
                (s.skip_reason or s.market_question)[:40],
            )
        console.print(table)
