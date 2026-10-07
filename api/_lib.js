// Lógica compartida: descarga de Yahoo Finance, indicadores y score.
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const cache = new Map();
const CACHE_MS = 5 * 60 * 1000;

async function getJson(url) {
  const r = await fetch(url, { headers: { "User-Agent": UA, Accept: "application/json" } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = (j.chart && j.chart.error && j.chart.error.description) || `HTTP ${r.status}`;
    throw new Error(e);
  }
  return j;
}

async function fetchChart(symbol) {
  let last;
  for (const host of ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]) {
    try {
      const j = await getJson(`https://${host}/v8/finance/chart/${encodeURIComponent(symbol)}?range=2y&interval=1d&includePrePost=false`);
      const res = j.chart && j.chart.result && j.chart.result[0];
      if (!res) throw new Error((j.chart && j.chart.error && j.chart.error.description) || "símbolo no encontrado");
      const ts = res.timestamp || [];
      const cl = (((res.indicators || {}).quote || [{}])[0].close) || [];
      const t = [], c = [];
      ts.forEach((x, i) => { if (cl[i] != null) { t.push(x); c.push(+cl[i]); } });
      return { meta: res.meta || {}, ts: t, closes: c };
    } catch (e) { last = e; }
  }
  throw last;
}

const sma = (v, n) => v.length < n ? null : v.slice(-n).reduce((a, b) => a + b, 0) / n;
function smaSeries(v, n) {
  const out = new Array(v.length).fill(null); let s = 0;
  v.forEach((x, i) => { s += x; if (i >= n) s -= v[i - n]; if (i >= n - 1) out[i] = s / n; });
  return out;
}
function rsiSeries(v, n = 14) {
  const out = new Array(v.length).fill(null);
  if (v.length <= n) return out;
  let g = 0, l = 0;
  for (let i = 1; i <= n; i++) { const d = v[i] - v[i - 1]; g += Math.max(d, 0); l += Math.max(-d, 0); }
  let ag = g / n, al = l / n;
  out[n] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  for (let i = n + 1; i < v.length; i++) {
    const d = v[i] - v[i - 1];
    ag = (ag * (n - 1) + Math.max(d, 0)) / n; al = (al * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  }
  return out;
}
const pct = (a, b) => (a == null || !b) ? null : (a / b - 1) * 100;

function computeScore(price, smas, rsi, sma20prev, ret3m) {
  const parts = [];
  let t = 0;
  [[200, 12], [100, 8], [50, 10], [20, 5]].forEach(([n, p]) => { if (smas[n] != null && price > smas[n]) t += p; });
  if (smas[50] != null && smas[200] != null && smas[50] > smas[200]) t += 5;
  parts.push(["Tendencia (precio vs medias)", t, 40]);
  let r;
  if (rsi == null) r = 10; else if (rsi < 30) r = 20; else if (rsi < 45) r = 25; else if (rsi < 60) r = 18; else if (rsi < 70) r = 10; else r = 2;
  parts.push(["RSI(14)", r, 25]);
  let m = 0;
  if (smas[20] != null && sma20prev != null && smas[20] > sma20prev) m += 10;
  if (ret3m != null) m += Math.max(0, Math.min(10, Math.round(ret3m / 2)));
  parts.push(["Momentum", m, 20]);
  const d50 = pct(price, smas[50]);
  let e;
  if (d50 == null) e = 7; else if (d50 >= 0 && d50 <= 8) e = 15; else if (d50 > 8 && d50 <= 15) e = 8; else if (d50 > 15) e = 2; else if (d50 >= -5) e = 10; else e = 4;
  parts.push(["Punto de entrada (distancia a MM50)", e, 15]);
  const score = parts.reduce((a, p) => a + p[1], 0);
  const label = score >= 70 ? "Favorable" : score >= 50 ? "Neutral" : "Desfavorable";
  return { score, label, breakdown: parts.map(([name, points, max]) => ({ name, points, max })) };
}

async function analyze(symbol, withHistory = false) {
  symbol = String(symbol || "").trim().toUpperCase();
  if (!symbol) throw new Error("símbolo vacío");
  let hit = cache.get(symbol);
  if (!hit || Date.now() - hit.at > CACHE_MS) { hit = { at: Date.now(), data: await fetchChart(symbol) }; cache.set(symbol, hit); }
  const { meta, ts, closes } = hit.data;
  if (!closes.length) throw new Error("sin datos de precio");
  const price = meta.regularMarketPrice != null ? meta.regularMarketPrice : closes[closes.length - 1];
  const series = closes.slice(); series[series.length - 1] = +price;
  const prev = closes.length > 1 ? closes[closes.length - 2] : null;
  const smas = {}; [20, 50, 100, 200].forEach(n => smas[n] = sma(series, n));
  const rsis = rsiSeries(series, 14), rsi = rsis[rsis.length - 1];
  const sma20prev = series.length > 25 ? sma(series.slice(0, -5), 20) : null;
  const ret3m = series.length > 64 ? pct(series[series.length - 1], series[series.length - 64]) : null;
  const year = series.slice(-252);
  const sc = computeScore(price, smas, rsi, sma20prev, ret3m);
  const out = {
    symbol, name: meta.longName || meta.shortName || symbol, type: meta.instrumentType || "",
    exchange: meta.fullExchangeName || meta.exchangeName || "", currency: meta.currency || "",
    price, change_pct: pct(price, prev),
    sma: { 20: smas[20], 50: smas[50], 100: smas[100], 200: smas[200] },
    dist: { 20: pct(price, smas[20]), 50: pct(price, smas[50]), 100: pct(price, smas[100]), 200: pct(price, smas[200]) },
    rsi, ret_3m: ret3m, high_52w: Math.max(...year), low_52w: Math.min(...year),
    ...sc, updated: meta.regularMarketTime || ts[ts.length - 1],
  };
  if (withHistory) {
    const k = 260, s = {};
    [20, 50, 100, 200].forEach(n => s[n] = smaSeries(series, n).slice(-k));
    out.history = { t: ts.slice(-k), close: series.slice(-k), sma20: s[20], sma50: s[50], sma100: s[100], sma200: s[200], rsi: rsis.slice(-k) };
  }
  return out;
}

async function analyzeMany(symbols) {
  const out = new Array(symbols.length); let i = 0;
  async function worker() {
    while (i < symbols.length) {
      const k = i++;
      try { out[k] = await analyze(symbols[k]); } catch (e) { out[k] = { symbol: String(symbols[k]).toUpperCase(), error: e.message }; }
    }
  }
  await Promise.all(Array.from({ length: 8 }, worker));
  return out;
}

async function search(q) {
  const j = await getJson("https://query1.finance.yahoo.com/v1/finance/search?quotesCount=8&newsCount=0&q=" + encodeURIComponent(q));
  return (j.quotes || []).filter(x => x.symbol).map(x => ({ symbol: x.symbol, name: x.longname || x.shortname || "", type: x.quoteType || "", exchange: x.exchDisp || "" }));
}

function send(res, code, body) {
  res.statusCode = code;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "s-maxage=60, stale-while-revalidate=300");
  res.end(JSON.stringify(body));
}

module.exports = { analyze, analyzeMany, search, send, computeScore, rsiSeries, smaSeries };
