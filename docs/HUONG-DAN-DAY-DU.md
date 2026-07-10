# Trade-coin-2026 — Hướng dẫn đầy đủ (tiếng Việt)

Repo: https://github.com/mrbit4578/Trade-coin-2026

## 1. Cài đặt local (Windows / PowerShell)

```powershell
git clone https://github.com/mrbit4578/Trade-coin-2026.git
cd Trade-coin-2026
python -m venv .venv
.\.venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
pip install -e .
copy .env.example .env
python -m crypto_edge.cli install-check
```

Nếu lỗi `No module named 'crypto_edge'`: **bắt buộc** `pip install -e .`

## 2. Chạy paper (CLI)

```powershell
python -m crypto_edge.cli once
python -m crypto_edge.cli run --cycles 10
```

## 3. Chạy web online (dashboard)

```powershell
python -m crypto_edge.cli web
```

Mở: http://127.0.0.1:8080

Trên dashboard:
- **Start bot** — vòng lặp trade automation
- **Scan once** — 1 chu kỳ phân tích
- **Send Telegram / WhatsApp** — test alert

### Docker

```powershell
docker compose up -d --build
```

## 4. Telegram automation

1. Chat `@BotFather` → `/newbot` → lấy token  
2. Lấy chat_id (ví dụ bot `@userinfobot`)  
3. `.env`:

```env
TELEGRAM_BOT_TOKEN=123:ABC
TELEGRAM_CHAT_ID=987654321
```

4. Test:

```powershell
python -m crypto_edge.cli notify-test --text "Xin chao"
```

## 5. WhatsApp automation

### Cách A — CallMeBot (nhanh, cá nhân)

1. Thêm `+34 644 59 71 67` vào liên hệ, gửi tin: `I allow callmebot to send me messages`  
2. Nhận apikey  
3. `.env`:

```env
WHATSAPP_PROVIDER=callmebot
WHATSAPP_PHONE=84901234567
WHATSAPP_CALLMEBOT_APIKEY=your_key
```

### Cách B — Twilio WhatsApp

```env
WHATSAPP_PROVIDER=twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=+14155238886
TWILIO_WHATSAPP_TO=+8490...
```

### Cách C — Meta Cloud API

```env
WHATSAPP_PROVIDER=meta
WHATSAPP_META_TOKEN=...
WHATSAPP_META_PHONE_ID=...
WHATSAPP_META_TO=8490...
```

## 6. Bot trade Binance / MEXC

### Paper trước

```env
MODE=paper
LIVE_CONFIRM=false
TRADE_VENUE=paper
```

### Binance Testnet

```env
TRADE_VENUE=binance
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_TESTNET=true
MODE=live
LIVE_CONFIRM=true
```

```powershell
python -m crypto_edge.cli keys
python -m crypto_edge.cli balance
python -m crypto_edge.cli run --cycles 5
```

### Mainnet (cẩn thận)

```env
BINANCE_TESTNET=false
MODE=live
LIVE_CONFIRM=true
MAX_POSITION_PCT=0.02
PAPER_CAPITAL_USD=100
```

**Live chỉ khi:** `MODE=live` + `LIVE_CONFIRM=true` + API keys.

## 7. Pipeline phân tích (kiến thức cốt lõi)

1. **Feeds** đa sàn: Binance + Coinbase + Bybit (spot + depth)  
2. **Orderbook proxy**: depth, imbalance, toxicity (closed-book proxy)  
3. **OTC overlay**: feed private hoặc sim research  
4. **SMC**: BOS / CHoCH / stop-hunt / premium-discount / confluence  
5. **Monte Carlo 10.000** path fat-tail  
6. **MiroFish graph** + swarm consensus  
7. **Edge ≥ 5%** mới vào lệnh  
8. **Half-Kelly × Bayesian** win-rate  
9. Risk: daily 2%, halt 5 thua liên tiếp  
10. Alert Telegram + WhatsApp khi ENTER / START / STOP / ERROR  

## 8. API web (tự động hóa)

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/health` | healthcheck |
| GET | `/api/status` | trạng thái bot |
| POST | `/api/bot/start` | start automation |
| POST | `/api/bot/stop` | stop |
| POST | `/api/bot/once` | 1 scan |
| GET | `/api/prices` | giá live |
| GET | `/api/trades` | ledger paper |
| POST | `/api/notify/test` | test alert |
| GET | `/api/config` | config an toàn (không secret) |

Optional: set `WEB_API_TOKEN` → gửi header `Authorization: Bearer <token>`.

## 9. Checklist trước live

- [ ] Paper ≥ 7 ngày  
- [ ] ≥ 50–200 tín hiệu  
- [ ] 0 crash  
- [ ] Telegram/WhatsApp OK  
- [ ] API Spot only, **không Withdraw**  
- [ ] Vốn nhỏ $50–100  

## 10. Disclaimer

Không phải lời khuyên tài chính. Rủi ro mất vốn. Polymarket / crypto có thể bị hạn chế theo quốc gia.
