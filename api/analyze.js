const { analyzeMany, send } = require("./_lib");
module.exports = async (req, res) => {
  const syms = String(req.query.symbols || "").split(",").map(s => s.trim()).filter(Boolean).slice(0, 80);
  try { send(res, 200, await analyzeMany(syms)); } catch (e) { send(res, 502, { error: e.message }); }
};
