const { analyze, send } = require("./_lib");
module.exports = async (req, res) => {
  try { send(res, 200, await analyze(req.query.symbol, true)); } catch (e) { send(res, 502, { error: e.message }); }
};
