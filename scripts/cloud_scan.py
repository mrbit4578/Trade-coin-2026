#!/usr/bin/env python3
"""
Lightweight cloud scan for GitHub Actions / any free CI.
Writes data/public/latest.json — consumed by static GitHub Pages web.

No WebSockets, reduced Monte Carlo, paper-only signals.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crypto_edge.agent.engine import EdgeAgent  # noqa: E402
from crypto_edge.config import Settings  # noqa: E402


async def main() -> None:
    import asyncio

    out_dir = ROOT / "data" / "public"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"

    # Cloud-friendly settings (light CPU for free Actions runners)
    s = Settings(
        mode="paper",
        live_confirm=False,
        trade_venue="paper",
        mc_simulations=1500,
        mirofish_agents=40,
        mirofish_enabled=True,
        scan_interval_sec=60,
        trade_cooldown_sec=0,
        auto_start_bot=False,
        otc_simulate=True,
    )

    agent = EdgeAgent(s, use_ws=False)
    await agent.start()
    try:
        sigs = await agent.scan_once()
        prices = agent.hub.mid_prices()
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "paper-cloud",
            "venue": "paper",
            "mc_simulations": s.mc_simulations,
            "prices": {k: round(v, 8) for k, v in prices.items() if v},
            "signals": [
                {
                    "action": x.action.value,
                    "symbol": x.symbol,
                    "side": x.side.value,
                    "edge": round(x.edge, 4),
                    "size_usd": x.size_usd,
                    "skip_reason": x.skip_reason,
                    "question": x.market_question,
                }
                for x in sigs
            ],
            "enter_count": sum(1 for x in sigs if x.action.value == "ENTER"),
            "cycles": 1,
            "source": "github-actions",
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {out_path} enters={payload['enter_count']} prices={payload['prices']}")
    finally:
        await agent.stop()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
