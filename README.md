# Trade-coin-2026

**Crypto trading edge agent** — multi-exchange data, SMC + Monte Carlo (10k) + MiroFish-style graph, paper-first execution on **Binance / MEXC**, **web dashboard online**, automation alerts via **Telegram + WhatsApp**.

> Repo: https://github.com/mrbit4578/Trade-coin-2026  
> Workspace path (local): `E:\01-Grok-2026\projects\crypto-edge-agent`  
> **Not financial advice.** Risk of loss. Paper mode by default.

---

## Features

| Area | Capability |
|------|------------|
| **Data** | BTC/ETH/SOL/BNB/DOGE/NEAR from Binance + Coinbase + Bybit (REST/WS) |
| **Depth** | Multi-venue L2 aggregation (closed-book *proxy*) |
| **SMC** | BOS / CHoCH / stop-hunt / premium-discount confluence |
| **Sim** | 10,000 Monte Carlo paths + MiroFish force-graph swarm |
| **Trade bot** | Spot BUY/SELL when edge ≥ 5%; half-Kelly × Bayesian sizing |
| **Risk** | 2% daily loss, halt after 5 consecutive losses |
| **Venues** | paper / Binance (testnet+main) / MEXC / Polymarket (research) |
| **Web** | FastAPI dashboard — start/stop bot, prices, signals, notify test |
| **Alerts** | Telegram + WhatsApp (CallMeBot / Twilio / Meta Cloud) |
| **Deploy** | Docker Compose, healthcheck, optional Render blueprint |

---

## Cách dùng khuyến nghị: **GitHub Pages (không PowerShell)**

1. Bật **Settings → Pages → Source = GitHub Actions** trên repo  
2. Chạy workflow **Deploy GitHub Pages**  
3. Mở: **https://mrbit4578.github.io/Trade-coin-2026/**  

- Giá **real-time** chạy trong trình duyệt (API công khai)  
- Bot paper cloud: workflow **Cloud paper bot** (mỗi 30 phút → `data/public/latest.json`)  
- Máy bạn **không** cần Python / uvicorn / PowerShell  

Chi tiết: [docs/GITHUB-PAGES.md](docs/GITHUB-PAGES.md)

### Local (tuỳ chọn)

**Web tĩnh siêu nhẹ** (không cài bot):

```bash
cd web && python -m http.server 5500
# http://127.0.0.1:5500
```

**Full bot + FastAPI** (nặng hơn, paper/live):

```bash
git clone https://github.com/mrbit4578/Trade-coin-2026.git
cd Trade-coin-2026
python -m venv .venv
# Windows: .\.venv\Scripts\activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env
python -m crypto_edge.cli web   # http://127.0.0.1:8080
```

### Docker

```bash
cp .env.example .env
docker compose up -d --build
```

---

## CLI

```bash
python -m crypto_edge.cli install-check
python -m crypto_edge.cli checklist
python -m crypto_edge.cli once
python -m crypto_edge.cli run --cycles 20
python -m crypto_edge.cli web --port 8080
python -m crypto_edge.cli keys
python -m crypto_edge.cli balance
python -m crypto_edge.cli notify-test --text "hello"
```

---

## Web API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard UI |
| GET | `/health` | Health |
| GET | `/api/status` | Bot status |
| POST | `/api/bot/start` | Start automation |
| POST | `/api/bot/stop` | Stop |
| POST | `/api/bot/once` | One scan |
| GET | `/api/prices` | Live prices |
| GET | `/api/trades` | Paper ledger |
| POST | `/api/notify/test` | Test Telegram/WhatsApp |
| GET | `/api/config` | Safe config |

Optional: `WEB_API_TOKEN` → `Authorization: Bearer <token>`

Set `AUTO_START_BOT=true` to start trading loop when web boots.

---

## Telegram & WhatsApp

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# none | callmebot | twilio | meta
WHATSAPP_PROVIDER=callmebot
WHATSAPP_PHONE=84901234567
WHATSAPP_CALLMEBOT_APIKEY=
```

See [docs/HUONG-DAN-DAY-DU.md](docs/HUONG-DAN-DAY-DU.md).

---

## Live trading (careful)

```env
TRADE_VENUE=binance
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=true   # keep true first
MODE=live
LIVE_CONFIRM=true
MAX_POSITION_PCT=0.02
```

Live requires **all three**: `MODE=live` + `LIVE_CONFIRM=true` + venue API keys.  
API keys: **Spot only**, **no withdraw**, IP whitelist recommended.

---

## Architecture

```
feeds → orderbook/OTC → SMC → Monte Carlo 10k → MiroFish
  → edge gate + risk → half-Kelly size → paper/Binance/MEXC
  → Telegram + WhatsApp → Web dashboard
```

```
src/crypto_edge/
  feeds/ execution/ simulation/ smc/ risk/ bayesian/
  alerts/   # telegram, whatsapp, multi notify
  bot/      # background automation service
  web/      # FastAPI + dashboard
  agent/    # main scan engine
  cli.py
```

---

## Docs

- [Hướng dẫn đầy đủ (VI)](docs/HUONG-DAN-DAY-DU.md)
- [Kiến thức phân tích SMC/Risk](docs/KIEN-THUC-PHAN-TICH.md)
- [config/default.yaml](config/default.yaml)

---

## Safety & disclaimer

- Default **paper** mode — no real orders until explicitly enabled  
- Past marketing win-rate claims are **not guaranteed**  
- Crypto trading can result in total loss of capital  
- Check local regulations (Polymarket may be restricted)  

MIT License — see [LICENSE](LICENSE)
