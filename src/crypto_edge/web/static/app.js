async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
  return data;
}

function fmtPrice(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  return x.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function renderStatus(s) {
  const badge = document.getElementById("badge-run");
  badge.textContent = s.running ? "RUNNING" : "STOPPED";
  badge.className = "badge " + (s.running ? "on" : "off");

  document.getElementById("st-cycles").textContent = s.cycles ?? 0;
  document.getElementById("st-enter").textContent = s.enter_count ?? 0;
  document.getElementById("st-skip").textContent = s.skip_count ?? 0;
  document.getElementById("st-equity").textContent =
    s.equity != null ? "$" + Number(s.equity).toFixed(2) : "—";

  const compact = {
    running: s.running,
    started_at: s.started_at,
    cycles: s.cycles,
    mode: s.mode,
    venue: s.venue,
    equity: s.equity,
    enter_count: s.enter_count,
    skip_count: s.skip_count,
    last_error: s.last_error,
    cooldown_sec: s.trade_cooldown_sec,
    scan_interval_sec: s.scan_interval_sec,
  };
  document.getElementById("status-box").textContent = JSON.stringify(compact, null, 2);

  const tbody = document.getElementById("signals-body");
  tbody.innerHTML = "";
  (s.last_signals || []).forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="${row.action === "ENTER" ? "enter" : "skip"}">${row.action}</td>
      <td>${row.symbol || ""}</td>
      <td>${row.side || ""}</td>
      <td>${row.edge ?? ""}</td>
      <td>${row.size_usd ? "$" + row.size_usd : "-"}</td>
      <td>${(row.skip_reason || row.question || "").slice(0, 48)}</td>`;
    tbody.appendChild(tr);
  });

  // prices from status cache
  if (s.live_prices && Object.keys(s.live_prices).length) {
    renderPrices(s.live_prices, "hub-cache");
  }

  // activity
  const act = (s.activity || [])
    .slice(0, 30)
    .map((a) => `${(a.ts || "").slice(11, 19)} [${a.kind}] ${a.message}`)
    .join("\n");
  document.getElementById("activity-box").textContent = act || "Chưa có activity…";
}

function renderPrices(prices, source) {
  const el = document.getElementById("prices");
  el.innerHTML = Object.entries(prices)
    .map(([sym, v]) => {
      const px = typeof v === "object" ? v.price : v;
      return `<div class="price-chip"><b>${sym}</b><span>${fmtPrice(px)}</span></div>`;
    })
    .join("");
  document.getElementById("price-src").textContent = source
    ? "Nguồn: " + source + " · tự refresh"
    : "";
}

async function refreshTrades() {
  try {
    const t = await api("/api/trades");
    const body = document.getElementById("trades-body");
    body.innerHTML = "";
    (t.trades || [])
      .slice()
      .reverse()
      .slice(0, 25)
      .forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${(row.id || "").toString().slice(0, 8)}</td>
          <td>${row.symbol || ""}</td>
          <td>${row.side || ""}</td>
          <td>${row.size_usd != null ? "$" + row.size_usd : "-"}</td>
          <td>${row.edge != null ? Number(row.edge).toFixed(3) : "-"}</td>
          <td>${row.mode || ""}</td>`;
        body.appendChild(tr);
      });
  } catch (e) {
    /* ignore */
  }
}

async function refresh() {
  try {
    const s = await api("/api/status");
    renderStatus(s);
    // if no cache yet, hit prices endpoint
    if (!s.live_prices || !Object.keys(s.live_prices).length) {
      const p = await api("/api/prices");
      if (p.ok) renderPrices(p.prices, p.source || "rest");
    }
    await refreshTrades();
  } catch (e) {
    document.getElementById("status-box").textContent = String(e.message || e);
  }
}

async function notify(channels) {
  const text = document.getElementById("notify-text").value || "test";
  const r = await api("/api/notify/test", {
    method: "POST",
    body: JSON.stringify({ text, channels }),
  });
  document.getElementById("notify-result").textContent = JSON.stringify(r, null, 2);
}

document.getElementById("btn-start").onclick = async () => {
  await api("/api/bot/start", { method: "POST" });
  await refresh();
};
document.getElementById("btn-stop").onclick = async () => {
  await api("/api/bot/stop", { method: "POST" });
  await refresh();
};
document.getElementById("btn-once").onclick = async () => {
  const r = await api("/api/bot/once", { method: "POST" });
  document.getElementById("status-box").textContent = JSON.stringify(r, null, 2);
  await refresh();
};
document.getElementById("btn-refresh").onclick = refresh;
document.getElementById("btn-tg").onclick = () => notify(["telegram"]);
document.getElementById("btn-wa").onclick = () => notify(["whatsapp"]);
document.getElementById("btn-both").onclick = () => notify(["telegram", "whatsapp"]);

refresh();
// Hot refresh every 5s — web is the control plane
setInterval(refresh, 5000);
