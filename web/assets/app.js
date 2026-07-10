/* Trade-coin-2026 static live dashboard — GitHub Pages compatible */
(function () {
  const activityEl = document.getElementById("activity");
  const pricesEl = document.getElementById("prices");
  const badgeSrc = document.getElementById("badge-src");
  const badgeClock = document.getElementById("badge-clock");
  const autoEl = document.getElementById("auto-refresh");

  const history = {}; // sym -> number[]
  let lastPrices = {};
  let timer = null;

  function log(msg) {
    const t = new Date().toLocaleTimeString();
    const line = `${t}  ${msg}`;
    activityEl.textContent = (line + "\n" + (activityEl.textContent || ""))
      .split("\n")
      .slice(0, 40)
      .join("\n");
  }

  function fmt(n) {
    if (!Number.isFinite(n)) return "—";
    if (n >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    if (n >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
    return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }

  async function fetchCryptoCompare() {
    const fsyms = TradeEngine.COINS.map((c) => c.cc).join(",");
    const url = `https://min-api.cryptocompare.com/data/pricemultifull?fsyms=${fsyms}&tsyms=USD`;
    const r = await fetch(url);
    if (!r.ok) throw new Error("CryptoCompare " + r.status);
    const data = await r.json();
    const raw = data.RAW || {};
    const out = {};
    for (const c of TradeEngine.COINS) {
      const row = raw[c.cc] && raw[c.cc].USD;
      if (!row) continue;
      out[c.sym] = {
        price: row.PRICE,
        change24h: row.CHANGEPCT24HOUR,
        high: row.HIGH24HOUR,
        low: row.LOW24HOUR,
        vol: row.VOLUME24HOURTO,
        source: "cryptocompare",
      };
    }
    if (!Object.keys(out).length) throw new Error("CryptoCompare empty");
    return out;
  }

  async function fetchCoinGecko() {
    const ids = TradeEngine.COINS.map((c) => c.cg).join(",");
    const url =
      `https://api.coingecko.com/api/v3/simple/price?ids=${ids}` +
      `&vs_currencies=usd&include_24hr_change=true`;
    const r = await fetch(url);
    if (!r.ok) throw new Error("CoinGecko " + r.status);
    const data = await r.json();
    const out = {};
    for (const c of TradeEngine.COINS) {
      const row = data[c.cg];
      if (!row) continue;
      out[c.sym] = {
        price: row.usd,
        change24h: row.usd_24h_change,
        source: "coingecko",
      };
    }
    if (!Object.keys(out).length) throw new Error("CoinGecko empty");
    return out;
  }

  /** Optional: Binance via public CORS-friendly mirror (best-effort) */
  async function fetchBinanceProxy() {
    // data-api may still block CORS in some browsers — try/catch only
    const url = "https://api.binance.com/api/v3/ticker/24hr";
    const r = await fetch(url);
    if (!r.ok) throw new Error("Binance " + r.status);
    const rows = await r.json();
    const want = new Set(TradeEngine.COINS.map((c) => c.sym + "USDT"));
    const out = {};
    for (const row of rows) {
      if (!want.has(row.symbol)) continue;
      const sym = row.symbol.replace("USDT", "");
      out[sym] = {
        price: parseFloat(row.lastPrice),
        change24h: parseFloat(row.priceChangePercent),
        high: parseFloat(row.highPrice),
        low: parseFloat(row.lowPrice),
        vol: parseFloat(row.quoteVolume),
        source: "binance",
      };
    }
    if (!Object.keys(out).length) throw new Error("Binance empty");
    return out;
  }

  async function loadPrices() {
    const errors = [];
    for (const fn of [fetchBinanceProxy, fetchCryptoCompare, fetchCoinGecko]) {
      try {
        const prices = await fn();
        lastPrices = prices;
        renderPrices(prices);
        const src = Object.values(prices)[0]?.source || "api";
        badgeSrc.textContent = src.toUpperCase();
        badgeClock.textContent = new Date().toLocaleTimeString();
        // update rolling history for engine
        for (const [sym, v] of Object.entries(prices)) {
          if (!history[sym]) history[sym] = TradeEngine.synthHistory(v.price, v.change24h || 0);
          history[sym].push(v.price);
          if (history[sym].length > 120) history[sym].shift();
        }
        log(`prices ok · source=${src} · ${Object.keys(prices).length} coins`);
        return prices;
      } catch (e) {
        errors.push(String(e.message || e));
      }
    }
    pricesEl.textContent = "Lỗi tải giá: " + errors.join(" | ");
    log("price error: " + errors.join(" | "));
    throw new Error(errors.join("; "));
  }

  function renderPrices(prices) {
    pricesEl.innerHTML = Object.entries(prices)
      .map(([sym, v]) => {
        const chg = Number(v.change24h || 0);
        const cls = chg >= 0 ? "up" : "down";
        const sign = chg >= 0 ? "+" : "";
        return `<div class="price-chip">
          <b>${sym}/USD</b>
          <div class="px">${fmt(v.price)}</div>
          <div class="chg ${cls}">${sign}${chg.toFixed(2)}% 24h</div>
        </div>`;
      })
      .join("");
  }

  function ledgerGet() {
    try {
      return JSON.parse(localStorage.getItem("tc2026_ledger") || "[]");
    } catch {
      return [];
    }
  }
  function ledgerSet(rows) {
    localStorage.setItem("tc2026_ledger", JSON.stringify(rows.slice(-200)));
  }
  function renderLedger() {
    const body = document.getElementById("ledger-body");
    body.innerHTML = "";
    ledgerGet()
      .slice()
      .reverse()
      .slice(0, 30)
      .forEach((r) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${r.t || ""}</td><td>${r.symbol}</td><td>${r.side}</td>
          <td>${r.edge}</td><td>${fmt(r.price)}</td>`;
        body.appendChild(tr);
      });
  }

  function scanSignals() {
    const rows = [];
    for (const c of TradeEngine.COINS) {
      const p = lastPrices[c.sym];
      if (!p) continue;
      const hist = history[c.sym] || TradeEngine.synthHistory(p.price, p.change24h || 0);
      const sig = TradeEngine.decide(c.sym, p.price, hist, 0.05);
      rows.push(sig);
      if (sig.action === "ENTER") {
        const led = ledgerGet();
        led.push({
          t: new Date().toLocaleTimeString(),
          symbol: sig.symbol,
          side: sig.side,
          edge: sig.edge,
          price: sig.price,
        });
        ledgerSet(led);
      }
    }
    const body = document.getElementById("sig-body");
    body.innerHTML = "";
    rows.forEach((s) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td class="${s.action === "ENTER" ? "enter" : "skip"}">${s.action}</td>
        <td>${s.symbol}</td><td>${s.side}</td><td>${s.edge}</td>
        <td>${s.note}</td>`;
      body.appendChild(tr);
    });
    document.getElementById("st-sig").textContent = String(rows.filter((r) => r.action === "ENTER").length);
    document.getElementById("st-run").textContent = new Date().toLocaleTimeString();
    renderLedger();
    log(`scan: ${rows.length} symbols, ENTER=${rows.filter((r) => r.action === "ENTER").length}`);
  }

  async function loadCloudSignals() {
    const box = document.getElementById("cloud-box");
    const body = document.getElementById("cloud-body");
    // Works on GitHub Pages: /Trade-coin-2026/data/public/latest.json OR relative
    const candidates = [
      "data/public/latest.json",
      "../data/public/latest.json",
      "./data/public/latest.json",
    ];
    // Also try absolute path for project pages
    const base = document.querySelector("base")?.href || "";
    if (location.pathname.includes("Trade-coin-2026")) {
      candidates.unshift(location.pathname.replace(/\/web\/?.*$/, "/data/public/latest.json"));
      candidates.unshift("/Trade-coin-2026/data/public/latest.json");
    }
    for (const url of candidates) {
      try {
        const r = await fetch(url + "?t=" + Date.now(), { cache: "no-store" });
        if (!r.ok) continue;
        const j = await r.json();
        box.textContent = JSON.stringify(
          {
            updated_at: j.updated_at,
            mode: j.mode,
            venue: j.venue,
            cycles: j.cycles,
            prices: j.prices,
          },
          null,
          2
        );
        body.innerHTML = "";
        (j.signals || []).forEach((s) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `<td>${s.symbol || ""}</td><td>${s.side || ""}</td>
            <td>${s.edge ?? ""}</td><td>${s.size_usd ?? "-"}</td>
            <td class="${s.action === "ENTER" ? "enter" : "skip"}">${s.action || ""}</td>`;
          body.appendChild(tr);
        });
        log("cloud latest.json loaded · " + (j.updated_at || ""));
        return;
      } catch {
        /* try next */
      }
    }
    box.textContent =
      "Chưa có data/public/latest.json (GitHub Action sẽ tạo sau khi bật workflow).\n" +
      "Web vẫn chạy live giá + signal client-side.";
  }

  function schedule() {
    if (timer) clearInterval(timer);
    if (!autoEl.checked) return;
    timer = setInterval(async () => {
      try {
        await loadPrices();
      } catch {
        /* logged */
      }
    }, 8000);
  }

  document.getElementById("btn-refresh").onclick = () => loadPrices().catch(() => {});
  document.getElementById("btn-scan").onclick = scanSignals;
  document.getElementById("btn-clear").onclick = () => {
    ledgerSet([]);
    renderLedger();
    log("ledger cleared");
  };
  autoEl.onchange = schedule;

  // boot
  log("Trade-coin-2026 static web boot");
  loadPrices()
    .then(() => scanSignals())
    .catch(() => {});
  loadCloudSignals();
  renderLedger();
  schedule();
  // refresh cloud every 2 min
  setInterval(loadCloudSignals, 120000);
})();
