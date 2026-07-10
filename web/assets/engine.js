/**
 * Lightweight client-side signal engine (paper only).
 * No Python / no GPU — runs in the browser.
 */
(function (global) {
  const COINS = [
    { sym: "BTC", cg: "bitcoin", cc: "BTC" },
    { sym: "ETH", cg: "ethereum", cc: "ETH" },
    { sym: "SOL", cg: "solana", cc: "SOL" },
    { sym: "BNB", cg: "binancecoin", cc: "BNB" },
    { sym: "DOGE", cg: "dogecoin", cc: "DOGE" },
    { sym: "NEAR", cg: "near", cc: "NEAR" },
  ];

  function mulberry32(a) {
    return function () {
      let t = (a += 0x6d2b79f5);
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /** Simple Monte Carlo on log returns history */
  function monteCarlo(prices, n = 2000, seed = 42) {
    if (!prices || prices.length < 8) {
      return { p_up: 0.5, expected: 0, n };
    }
    const rets = [];
    for (let i = 1; i < prices.length; i++) {
      rets.push(Math.log(prices[i] / prices[i - 1]));
    }
    const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
    const varr =
      rets.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, rets.length - 1);
    const sigma = Math.sqrt(Math.max(varr, 1e-10));
    const rnd = mulberry32(seed);
    let up = 0;
    let exp = 0;
    const steps = 12;
    for (let i = 0; i < n; i++) {
      let s = 0;
      for (let k = 0; k < steps; k++) {
        // Box-Muller
        const u1 = Math.max(1e-12, rnd());
        const u2 = rnd();
        const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
        s += mean + sigma * z;
      }
      const move = Math.exp(s) - 1;
      exp += move;
      if (s > 0) up++;
    }
    return { p_up: up / n, expected: exp / n, n };
  }

  function structureScore(prices) {
    if (!prices || prices.length < 20) return { trend: "range", score: 0 };
    const a = prices.slice(-40);
    const ema = (arr, span) => {
      const k = 2 / (span + 1);
      let e = arr[0];
      for (let i = 1; i < arr.length; i++) e = k * arr[i] + (1 - k) * e;
      return e;
    };
    const f = ema(a, 8);
    const s = ema(a, 21);
    const last = a[a.length - 1];
    const hi = Math.max(...a);
    const lo = Math.min(...a);
    const mid = (hi + lo) / 2;
    let score = 0;
    let trend = "range";
    if (f > s * 1.001) {
      trend = "bull";
      score += 0.25;
    } else if (f < s * 0.999) {
      trend = "bear";
      score -= 0.25;
    }
    if (last < mid && trend === "bull") score += 0.15;
    if (last > mid && trend === "bear") score -= 0.15;
    const mom = (last - a[0]) / a[0];
    score += Math.max(-0.3, Math.min(0.3, mom * 5));
    return { trend, score: Math.max(-1, Math.min(1, score)) };
  }

  function decide(sym, price, hist, edgeThr = 0.05) {
    const mc = monteCarlo(hist, 2000, sym.charCodeAt(0) * 97);
    const st = structureScore(hist);
    const edgeUp = mc.p_up - 0.5;
    const edgeDn = 1 - mc.p_up - 0.5;
    let side = null;
    let edge = 0;
    let action = "SKIP";
    let note = "no edge";

    if (edgeUp >= edgeThr && st.score >= -0.2) {
      if (st.trend === "bear" && st.score < -0.3) {
        note = "conflict structure bear";
      } else {
        action = "ENTER";
        side = "BUY";
        edge = edgeUp;
        note = `mc_up=${mc.p_up.toFixed(3)} ${st.trend}`;
      }
    } else if (edgeDn >= edgeThr && st.score <= 0.2) {
      if (st.trend === "bull" && st.score > 0.3) {
        note = "conflict structure bull";
      } else {
        action = "ENTER";
        side = "SELL";
        edge = edgeDn;
        note = `mc_dn=${(1 - mc.p_up).toFixed(3)} ${st.trend}`;
      }
    }

    return {
      action,
      symbol: sym,
      side: side || "-",
      edge: Number(edge.toFixed(4)),
      price,
      fair: Number(mc.p_up.toFixed(4)),
      note,
      trend: st.trend,
    };
  }

  /** Build synthetic history from last price + 24h change if no series */
  function synthHistory(price, changePct) {
    const n = 48;
    const out = [];
    let p = price / (1 + (changePct || 0) / 100);
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1);
      p = p * (1 + ((changePct || 0) / 100 / n) * (0.6 + 0.8 * Math.sin(i))) ;
      // mean-revert path toward current
      p = p * 0.85 + price * 0.15 * (0.5 + t);
      out.push(p);
    }
    out[out.length - 1] = price;
    return out;
  }

  global.TradeEngine = {
    COINS,
    monteCarlo,
    structureScore,
    decide,
    synthHistory,
  };
})(window);
