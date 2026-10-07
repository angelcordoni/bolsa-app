// Cotización rápida (sin histórico) para la cinta de índices, materias primas, divisas y cripto.
const { live, send } = require("./_lib");
module.exports = async (req, res) => {
  const syms = String(req.query.symbols || "").split(",").map(s => s.trim()).filter(Boolean).slice(0, 12);
  const out = await Promise.all(syms.map(async symbol => {
    try {
      const q = await live(symbol);
      const chg = q.price != null && q.prevClose ? q.price - q.prevClose : null;
      return { symbol, price: q.price, change: chg, change_pct: chg == null ? null : chg / q.prevClose * 100, time: q.time, open: q.open, currency: q.meta.currency || "" };
    } catch (e) { return { symbol, error: e.message }; }
  }));
  send(res, 200, out, 15);
};
