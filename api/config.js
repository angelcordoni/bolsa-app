// Datos públicos para que la página arranque Firebase (no son secretos)
module.exports = (req, res) => {
  const pid = process.env.FIREBASE_PROJECT_ID || "";
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify({
    auth: !!pid,
    firebase: pid ? {
      apiKey: process.env.FIREBASE_API_KEY || "",
      authDomain: process.env.FIREBASE_AUTH_DOMAIN || pid + ".firebaseapp.com",
      projectId: pid,
      appId: process.env.FIREBASE_APP_ID || "",
    } : null,
  }));
};
