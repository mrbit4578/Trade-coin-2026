async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
  return data;
}

function renderStatus(s) {
  const box = document.getElementById("status-box");
  const badge = document.getElementById("badge-run");
  badge.textContent = s.running ? "RUNNING" : "STOPPED";
  badge.className = "badge " + (s.running ? "on" : "off");
  box.textContent = JSON.stringify(s, null, 2);

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
}

async function refresh() {
  const s = await api("/api/status");
  renderStatus(s);
  try {
    const p = await api("/api/prices");
    const el = document.getElementById("prices");
    if (!p.ok) {
      el.textContent = p.error || "price error";
      return;
    }
    el.innerHTML = Object.entries(p.prices)
      .map(
        ([sym, v]) =>
          `<div class="price-chip"><b>${sym}</b><span>${Number(v.price).toLocaleString(undefined, {
            maximumFractionDigits: 6,
          })}</span></div>`
      )
      .join("");
  } catch (e) {
    document.getElementById("prices").textContent = String(e.message || e);
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
setInterval(refresh, 15000);
