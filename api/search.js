const { search, send } = require("./_lib");
const { guard } = require("./_auth");
module.exports = guard(async (req, res) => {
  try { send(res, 200, await search(String(req.query.q || ""))); } catch (e) { send(res, 502, { error: e.message }); }
});
