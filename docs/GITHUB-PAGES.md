# Chạy web trên GitHub (không PowerShell, không nặng máy)

## Ý tưởng

| Thành phần | Nơi chạy | Máy bạn |
|------------|----------|---------|
| Web UI live | **GitHub Pages** (trình duyệt) | Chỉ mở link |
| Giá real-time | API công khai (Binance / CryptoCompare / CoinGecko) | Trình duyệt fetch |
| Bot paper cloud | **GitHub Actions** mỗi 30 phút | 0 CPU |
| Live trade API key | Không host secret trên Pages | Tùy chọn local/VPS sau |

URL sau khi bật Pages:

**https://mrbit4578.github.io/Trade-coin-2026/**

---

## Bật 1 lần (trên GitHub website)

1. Mở https://github.com/mrbit4578/Trade-coin-2026  
2. **Settings → Pages**  
3. **Build and deployment → Source** = **GitHub Actions**  
4. Vào tab **Actions** → cho phép workflows nếu GitHub hỏi  
5. Chạy workflow **Deploy GitHub Pages** (Run workflow)  
6. Đợi ~1 phút → mở link Pages  

### Bật bot cloud (tín hiệu `latest.json`)

1. **Actions → Cloud paper bot → Run workflow** (chạy tay lần đầu)  
2. Sau đó tự chạy mỗi 30 phút  
3. File `data/public/latest.json` được commit + Pages deploy lại  

---

## Không cần làm gì trên máy

- Không `pip install`  
- Không `python -m crypto_edge.cli web`  
- Không mở PowerShell 24/7  

Chỉ bookmark:

`https://mrbit4578.github.io/Trade-coin-2026/`

---

## Cấu trúc

```
web/                  # static site (Pages)
  index.html
  assets/app.js       # live prices + client engine
  assets/engine.js    # MC nhẹ + structure
data/public/
  latest.json         # cloud bot output
.github/workflows/
  pages.yml           # deploy Pages
  cloud-bot.yml       # scheduled scan
```

---

## Giới hạn (trung thực)

- **GitHub Pages = static** — không giữ WebSocket server Python.  
- Giá live: poll API ~8 giây trong trình duyệt (nhẹ).  
- Bot cloud: paper scan định kỳ, không thay thế bot 15s local.  
- **Không** đặt `BINANCE_API_SECRET` / private key lên repo hoặc Pages.  
- Live trade thật: dùng VPS/Docker hoặc máy local khi cần.  

---

## Local preview (tuỳ chọn, nhẹ)

```powershell
cd web
# Python 3 built-in static server
python -m http.server 5500
# mở http://127.0.0.1:5500
```

Không cài FastAPI / không load full bot.
