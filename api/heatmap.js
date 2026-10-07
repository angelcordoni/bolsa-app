// Mapa de calor del S&P 500: variación del día y capitalización de cada empresa, agrupadas por sector.
const { live, send } = require("./_lib");
const SP = require("./_sp500.json");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
let auth = null, cache = null;

// Yahoo exige una cookie y un "crumb" para la API de cotizaciones con capitalización
async function getAuth() {
  if (auth && Date.now() - auth.at < 3600e3) return auth;
  const r = await fetch("https://fc.yahoo.com", { headers: { "User-Agent": UA }, redirect: "manual" });
  const sc = typeof r.headers.getSetCookie === "function" ? r.headers.getSetCookie() : [r.headers.get("set-cookie") || ""];
  const cookie = sc.map(c => c.split(";")[0]).filter(Boolean).join("; ");
  const c = await fetch("https://query1.finance.yahoo.com/v1/test/getcrumb", { headers: { "User-Agent": UA, Cookie: cookie } });
  const crumb = (await c.text()).trim();
  if (!c.ok || !crumb || crumb.includes("<")) throw new Error("sin crumb");
  auth = { cookie, crumb, at: Date.now() };
  return auth;
}

async function quotes(symbols) {
  const a = await getAuth();
  const url = "https://query1.finance.yahoo.com/v7/finance/quote?fields=marketCap,regularMarketChangePercent,regularMarketPrice,shortName&crumb="
    + encodeURIComponent(a.crumb) + "&symbols=" + encodeURIComponent(symbols.join(","));
  const r = await fetch(url, { headers: { "User-Agent": UA, Cookie: a.cookie } });
  if (!r.ok) { auth = null; throw new Error("HTTP " + r.status); }
  const j = await r.json();
  return (j.quoteResponse && j.quoteResponse.result) || [];
}

async function build() {
  const info = new Map(SP.map(([s, sec, name]) => [s, { sec, name }]));
  const syms = SP.map(x => x[0]);
  const out = [];
  try {
    const chunks = []; for (let i = 0; i < syms.length; i += 100) chunks.push(syms.slice(i, i + 100));
    const res = await Promise.all(chunks.map(quotes));
    res.flat().forEach(q => { const i = info.get(q.symbol); if (i && q.marketCap) out.push({ s: q.symbol, n: q.shortName || i.name, sec: i.sec, cap: q.marketCap, chg: q.regularMarketChangePercent, p: q.regularMarketPrice }); });
    if (out.length < 300) throw new Error("respuesta incompleta");
    return { source: "cap", items: out };
  } catch (e) {
    // Plan B: sin capitalización, cada empresa con el mismo peso
    let i = 0; const items = [];
    async function w() { while (i < syms.length) { const s = syms[i++]; try { const q = await live(s); if (q.price != null && q.prevClose) items.push({ s, n: info.get(s).name, sec: info.get(s).sec, cap: 1, chg: (q.price / q.prevClose - 1) * 100, p: q.price }); } catch (_) {} } }
    await Promise.all(Array.from({ length: 16 }, w));
    return { source: "equal", error: e.message, items };
  }
}

module.exports = async (req, res) => {
  try {
    if (!cache || Date.now() - cache.at > 60e3) cache = { at: Date.now(), data: await build() };
    send(res, 200, cache.data, 60);
  } catch (e) { send(res, 502, { error: e.message }); }
};
