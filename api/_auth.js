// Protección de las rutas /api con Firebase Authentication.
// Se activa sola cuando existe la variable FIREBASE_PROJECT_ID en Vercel; sin ella la app sigue abierta.
const crypto = require("crypto");
const CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com";
let certs = null, certsUntil = 0;
// Correos con acceso (decisión de jose); la variable ALLOWED_EMAILS de Vercel la reemplaza
const DEFAULT_ALLOWED = "angelcordoni@gmail.com";

async function getCerts() {
  if (certs && Date.now() < certsUntil) return certs;
  const r = await fetch(CERTS_URL);
  if (!r.ok) throw new Error("no se pudieron leer las claves de Google");
  const m = /max-age=(\d+)/.exec(r.headers.get("cache-control") || "");
  certs = await r.json();
  certsUntil = Date.now() + (m ? +m[1] : 3600) * 1000;
  return certs;
}

const b64 = s => Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64");

// Verifica el token de sesión de Firebase (JWT RS256) y devuelve sus datos
async function verifyToken(token, projectId) {
  const [h, p, s] = String(token || "").split(".");
  if (!h || !p || !s) throw new Error("token inválido");
  const head = JSON.parse(b64(h).toString()), body = JSON.parse(b64(p).toString());
  if (head.alg !== "RS256") throw new Error("token inválido");
  const pem = (await getCerts())[head.kid];
  if (!pem) throw new Error("token inválido");
  const key = new crypto.X509Certificate(pem).publicKey;
  if (!crypto.verify("RSA-SHA256", Buffer.from(h + "." + p), key, b64(s))) throw new Error("token inválido");
  const now = Math.floor(Date.now() / 1000);
  if (body.aud !== projectId || body.iss !== "https://securetoken.google.com/" + projectId) throw new Error("token inválido");
  if (!(body.exp > now - 60) || !(body.iat <= now + 60) || !body.sub) throw new Error("sesión vencida");
  return body;
}

function deny(res, code, msg) {
  res.statusCode = code;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify({ error: msg, auth: true }));
}

// Envuelve una ruta para que solo responda con una sesión válida
function guard(handler) {
  return async (req, res) => {
    const projectId = process.env.FIREBASE_PROJECT_ID;
    if (!projectId) return handler(req, res);
    const m = /^Bearer (.+)$/.exec(req.headers.authorization || "");
    let user;
    try { user = await verifyToken(m && m[1], projectId); }
    catch (e) { return deny(res, 401, "Inicia sesión para usar Bag Scanner"); }
    const allow = (process.env.ALLOWED_EMAILS || DEFAULT_ALLOWED).split(",").map(x => x.trim().toLowerCase()).filter(Boolean);
    if (allow.length && !allow.includes(String(user.email || "").toLowerCase())) return deny(res, 403, "Este correo no tiene acceso a Bag Scanner");
    req.user = user;
    return handler(req, res);
  };
}

module.exports = { guard, verifyToken };
