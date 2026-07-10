"""CLI: install-check | once | run | web | keys | balance | checklist | notify-test."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from crypto_edge.agent.engine import EdgeAgent
from crypto_edge.config import get_settings, reload_settings

app = typer.Typer(
    help="Trade-coin-2026 — paper-first crypto bot + web + Telegram/WhatsApp",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


@app.command("install-check")
def install_check() -> None:
    """Verify package import + deps."""
    import crypto_edge

    console.print(f"[green]OK[/] crypto_edge {crypto_edge.__version__}")
    console.print(f"  path: {crypto_edge.__file__}")
    for mod in (
        "httpx",
        "numpy",
        "pydantic",
        "websockets",
        "typer",
        "rich",
        "networkx",
        "fastapi",
        "uvicorn",
        "jinja2",
    ):
        __import__(mod)
        console.print(f"  [green]✓[/] {mod}")
    s = reload_settings()
    console.print(
        f"  mode={s.mode} venue={s.trade_venue} live_allowed={s.is_live_allowed()}"
    )


@app.command()
def run(
    cycles: int = typer.Option(0, help="Max cycles (0 = forever)"),
    no_ws: bool = typer.Option(False, help="REST only"),
) -> None:
    """Run bot loop in terminal (paper by default)."""
    settings = reload_settings()
    _setup_logging(settings.log_level)
    if settings.mode == "live" and not settings.is_live_allowed():
        console.print("[red]LIVE blocked[/]: MODE=live + LIVE_CONFIRM=true + API keys")
        raise typer.Exit(1)
    if settings.mode == "live" and settings.trade_venue == "binance" and not settings.binance_testnet:
        console.print("[bold red]⚠ MAINNET live — Ctrl+C trong 5s để hủy...[/]")
        import time

        time.sleep(5)
    agent = EdgeAgent(settings, use_ws=not no_ws)
    asyncio.run(agent.run_forever(max_cycles=cycles if cycles > 0 else None))


@app.command()
def once(no_ws: bool = typer.Option(True)) -> None:
    """Single scan then exit."""
    settings = reload_settings()
    _setup_logging(settings.log_level)

    async def _go() -> None:
        agent = EdgeAgent(settings, use_ws=not no_ws)
        await agent.start()
        try:
            sigs = await agent.scan_once()
            agent._print_cycle(sigs)
        finally:
            await agent.stop()

    asyncio.run(_go())


@app.command()
def web(
    host: str = typer.Option(None, help="Bind host"),
    port: int = typer.Option(None, help="Bind port"),
) -> None:
    """Start online web dashboard (FastAPI)."""
    import uvicorn

    settings = reload_settings()
    _setup_logging(settings.log_level)
    h = host or settings.web_host
    p = port or settings.web_port
    console.print(f"[bold green]Web dashboard[/] http://{h}:{p}  (local: http://127.0.0.1:{p})")
    uvicorn.run(
        "crypto_edge.web.app:app",
        host=h,
        port=p,
        reload=False,
        log_level=settings.log_level.lower(),
    )


@app.command()
def keys() -> None:
    """Test exchange API keys (no orders)."""
    settings = reload_settings()
    _setup_logging(settings.log_level)

    async def _go() -> None:
        venue = settings.trade_venue
        if venue == "binance":
            if not settings.binance_api_key:
                console.print("[red]Thiếu BINANCE_API_KEY[/]")
                raise typer.Exit(1)
            from crypto_edge.execution.binance_spot import BinanceSpotClient

            c = BinanceSpotClient(
                settings.binance_api_key,
                settings.binance_api_secret,
                testnet=settings.binance_testnet,
            )
            await c.ping()
            usdt = await c.free_balance("USDT")
            console.print(f"[green]Binance OK[/] testnet={settings.binance_testnet} USDT={usdt:.4f}")
        elif venue == "mexc":
            if not settings.mexc_api_key:
                console.print("[red]Thiếu MEXC_API_KEY[/]")
                raise typer.Exit(1)
            from crypto_edge.execution.mexc_spot import MexcSpotClient

            c = MexcSpotClient(settings.mexc_api_key, settings.mexc_api_secret)
            await c.ping()
            console.print(f"[green]MEXC OK[/] USDT={await c.free_balance('USDT'):.4f}")
        else:
            console.print("Set TRADE_VENUE=binance|mexc và điền API keys trong .env")

    asyncio.run(_go())


@app.command()
def balance() -> None:
    """Show free balances on exchange."""
    settings = reload_settings()

    async def _go() -> None:
        if settings.trade_venue == "binance" and settings.binance_api_key:
            from crypto_edge.execution.binance_spot import BinanceSpotClient

            c = BinanceSpotClient(
                settings.binance_api_key,
                settings.binance_api_secret,
                testnet=settings.binance_testnet,
            )
            acc = await c.account()
            for b in acc.get("balances", []):
                free = float(b.get("free") or 0)
                if free > 0:
                    console.print(f"  {b['asset']}: {free}")
        elif settings.trade_venue == "mexc" and settings.mexc_api_key:
            from crypto_edge.execution.mexc_spot import MexcSpotClient

            c = MexcSpotClient(settings.mexc_api_key, settings.mexc_api_secret)
            acc = await c.account()
            for b in acc.get("balances", []):
                free = float(b.get("free") or 0)
                if free > 0:
                    console.print(f"  {b['asset']}: {free}")
        else:
            console.print("Chưa cấu hình keys")

    asyncio.run(_go())


@app.command("notify-test")
def notify_test(
    text: str = typer.Option("Hello from Trade-coin-2026", help="Message body"),
) -> None:
    """Send test message to Telegram + WhatsApp."""
    from crypto_edge.alerts.notify import MultiNotifier

    settings = reload_settings()

    async def _go() -> None:
        r = await MultiNotifier(settings).broadcast(f"🧪 {text}")
        console.print(r)

    asyncio.run(_go())


@app.command()
def checklist() -> None:
    """Full setup checklist (VI)."""
    settings = reload_settings()
    text = f"""
[bold]Trade-coin-2026 — checklist[/]

1. pip install -e . && python -m crypto_edge.cli install-check
2. copy .env.example .env  (MODE=paper)
3. python -m crypto_edge.cli once
4. python -m crypto_edge.cli web   → http://127.0.0.1:8080
5. Cấu hình Telegram / WhatsApp → notify-test
6. API Binance testnet hoặc MEXC → keys / balance
7. Paper ≥ 7 ngày trước MODE=live LIVE_CONFIRM=true

[bold]Hiện tại[/]
mode={settings.mode} venue={settings.trade_venue}
live_allowed={settings.is_live_allowed()}
web={settings.web_host}:{settings.web_port}
tg={bool(settings.telegram_bot_token)} wa={settings.whatsapp_provider}

[yellow]Disclaimer[/]: Rủi ro mất vốn. Không phải lời khuyên tài chính.
"""
    console.print(Panel(text, title="Trade-coin-2026", border_style="cyan"))


@app.command()
def status() -> None:
    s = reload_settings()
    console.print(
        {
            "mode": s.mode,
            "trade_venue": s.trade_venue,
            "live_allowed": s.is_live_allowed(),
            "web": f"{s.web_host}:{s.web_port}",
            "symbols": s.symbol_list,
            "project_root": str(_ROOT),
        }
    )


if __name__ == "__main__":
    app()
