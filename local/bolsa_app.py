#!/usr/bin/env python3
"""
Bolsa App: gestor de cartera y escáner de acciones/ETFs.

Uso:
    python3 bolsa_app.py            (abre http://localhost:8765 en el navegador)
    python3 bolsa_app.py --port 9000 --no-browser

Solo usa la biblioteca estándar de Python 3.8+. Los precios vienen de
Yahoo Finance (gráfico diario). La cartera y la lista del escáner se
guardan en bolsa_datos.json junto a este archivo.

Aviso: el score es un indicador técnico orientativo, no una recomendación
de inversión.
"""
import argparse
import json
import math
import os
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "bolsa_datos.json")
CACHE_SECONDS = 300
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

DEFAULT_WATCHLIST = [
    # Índices / ETFs
    "SPY", "QQQ", "VOO", "VTI", "IWM", "DIA", "VT", "GLD", "XLE", "XLF",
    # EE. UU.
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "JPM", "V", "MA", "KO", "PEP", "JNJ", "PG", "XOM", "WMT", "COST",
    # España
    "SAN.MC", "ITX.MC", "IBE.MC", "BBVA.MC",
]

_lock = threading.Lock()
_cache = {}


# ----------------------------------------------------------------- datos
def load_data():
    with _lock:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                d.setdefault("watchlist", list(DEFAULT_WATCHLIST))
                d.setdefault("portfolio", [])
                return d
            except (OSError, ValueError):
                pass
        return {"watchlist": list(DEFAULT_WATCHLIST), "portfolio": []}


def save_data(d):
    with _lock:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_chart(symbol):
    """Devuelve (meta, fechas, cierres) de ~2 años de velas diarias."""
    q = urllib.parse.quote(symbol)
    last_err = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{q}?range=2y&interval=1d&includePrePost=false"
        try:
            j = http_json(url)
            res = (j.get("chart") or {}).get("result")
            if not res:
                err = (j.get("chart") or {}).get("error") or {}
                raise ValueError(err.get("description") or "símbolo no encontrado")
            res = res[0]
            ts = res.get("timestamp") or []
            closes = (((res.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
            pairs = [(t, c) for t, c in zip(ts, closes) if c is not None]
            return res.get("meta") or {}, [p[0] for p in pairs], [float(p[1]) for p in pairs]
        except Exception as e:  # probar el otro host
            last_err = e
    raise last_err


# ----------------------------------------------------------- indicadores
def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def sma_series(values, n):
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rsi_series(values, n=14):
    """RSI de Wilder."""
    out = [None] * len(values)
    if len(values) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return (a / b - 1) * 100


def compute_score(price, smas, rsi, sma20_prev, ret_3m):
    """Score técnico 0-100 con su desglose. Ver README para la explicación."""
    parts = []

    # 1) Tendencia (40): precio sobre cada media + cruce 50/200
    t = 0
    for n, pts in ((200, 12), (100, 8), (50, 10), (20, 5)):
        m = smas.get(n)
        if m is not None and price > m:
            t += pts
    if smas.get(50) is not None and smas.get(200) is not None and smas[50] > smas[200]:
        t += 5
    parts.append(("Tendencia (precio vs medias)", t, 40))

    # 2) RSI (25): premia zona sana o sobreventa, castiga sobrecompra
    if rsi is None:
        r = 10
    elif rsi < 30:
        r = 20
    elif rsi < 45:
        r = 25
    elif rsi < 60:
        r = 18
    elif rsi < 70:
        r = 10
    else:
        r = 2
    parts.append(("RSI(14)", r, 25))

    # 3) Momentum (20): pendiente de la media 20 y rentabilidad a 3 meses
    m = 0
    if smas.get(20) is not None and sma20_prev is not None and smas[20] > sma20_prev:
        m += 10
    if ret_3m is not None:
        m += max(0, min(10, round(ret_3m / 2)))  # +10 con >= 20 % en 3 meses
    parts.append(("Momentum", m, 20))

    # 4) Punto de entrada (15): distancia a la media 50 (evita comprar muy estirado)
    d50 = pct(price, smas.get(50))
    if d50 is None:
        e = 7
    elif 0 <= d50 <= 8:
        e = 15
    elif 8 < d50 <= 15:
        e = 8
    elif d50 > 15:
        e = 2
    elif d50 >= -5:
        e = 10
    else:
        e = 4
    parts.append(("Punto de entrada (distancia a MM50)", e, 15))

    score = sum(p[1] for p in parts)
    if score >= 70:
        label = "Favorable"
    elif score >= 50:
        label = "Neutral"
    else:
        label = "Desfavorable"
    return score, label, [{"name": a, "points": b, "max": c} for a, b, c in parts]


def analyze(symbol, with_history=False):
    symbol = symbol.strip().upper()
    now = time.time()
    hit = _cache.get(symbol)
    if hit and now - hit[0] < CACHE_SECONDS:
        meta, ts, closes = hit[1]
    else:
        meta, ts, closes = fetch_chart(symbol)
        _cache[symbol] = (now, (meta, ts, closes))
    if not closes:
        raise ValueError("sin datos de precio")

    price = meta.get("regularMarketPrice") or closes[-1]
    # Sustituye el último cierre por el precio actual para que las medias estén al día
    series = closes[:]
    series[-1] = float(price)
    prev = closes[-2] if len(closes) > 1 else None
    smas = {n: sma(series, n) for n in (20, 50, 100, 200)}
    rsis = rsi_series(series, 14)
    rsi = rsis[-1]
    sma20_prev = sma(series[:-5], 20) if len(series) > 25 else None
    ret_3m = pct(series[-1], series[-64]) if len(series) > 64 else None
    year = series[-252:]
    score, label, breakdown = compute_score(price, smas, rsi, sma20_prev, ret_3m)

    out = {
        "symbol": symbol,
        "name": meta.get("longName") or meta.get("shortName") or symbol,
        "type": meta.get("instrumentType") or "",
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        "currency": meta.get("currency") or "",
        "price": price,
        "change_pct": pct(price, prev),
        "sma": {str(n): smas[n] for n in smas},
        "dist": {str(n): pct(price, smas[n]) for n in smas},
        "rsi": rsi,
        "ret_3m": ret_3m,
        "high_52w": max(year),
        "low_52w": min(year),
        "score": score,
        "label": label,
        "breakdown": breakdown,
        "updated": int(meta.get("regularMarketTime") or ts[-1]),
    }
    if with_history:
        k = 260  # ~1 año en el gráfico
        s = {n: sma_series(series, n)[-k:] for n in (20, 50, 100, 200)}
        out["history"] = {
            "t": ts[-k:],
            "close": series[-k:],
            "sma20": s[20], "sma50": s[50], "sma100": s[100], "sma200": s[200],
            "rsi": rsis[-k:],
        }
    return out


def analyze_many(symbols):
    def one(s):
        try:
            return analyze(s)
        except Exception as e:
            return {"symbol": s.upper(), "error": str(e)}
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, symbols))


def search(q):
    url = ("https://query1.finance.yahoo.com/v1/finance/search?quotesCount=8&newsCount=0&q="
           + urllib.parse.quote(q))
    j = http_json(url)
    return [{"symbol": x.get("symbol"), "name": x.get("longname") or x.get("shortname") or "",
             "type": x.get("quoteType") or "", "exchange": x.get("exchDisp") or ""}
            for x in j.get("quotes", []) if x.get("symbol")]


# ------------------------------------------------------------ servidor web
def clean(o):
    """JSON no admite NaN/Infinity."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(clean(body), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                return self.send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if u.path == "/api/data":
                return self.send(200, load_data())
            if u.path == "/api/analyze":
                syms = [s for s in (qs.get("symbols", [""])[0]).split(",") if s.strip()]
                return self.send(200, analyze_many(syms))
            if u.path == "/api/detail":
                return self.send(200, analyze(qs.get("symbol", [""])[0], with_history=True))
            if u.path == "/api/search":
                return self.send(200, search(qs.get("q", [""])[0]))
            self.send(404, {"error": "no encontrado"})
        except Exception as e:
            self.send(502, {"error": str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/api/data":
                d = self.body_json()
                cur = load_data()
                if isinstance(d.get("watchlist"), list):
                    cur["watchlist"] = [str(s).strip().upper() for s in d["watchlist"] if str(s).strip()]
                if isinstance(d.get("portfolio"), list):
                    cur["portfolio"] = [
                        {"symbol": str(p["symbol"]).strip().upper(),
                         "shares": float(p["shares"]), "cost": float(p["cost"])}
                        for p in d["portfolio"] if p.get("symbol")
                    ]
                save_data(cur)
                return self.send(200, cur)
            self.send(404, {"error": "no encontrado"})
        except Exception as e:
            self.send(400, {"error": str(e)})


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0f172a"><meta name="apple-mobile-web-app-capable" content="yes">
<title>Bolsa App</title>
<style>
/* Tema azul marino oscuro, móvil primero: cifras alineadas, color solo para señal */
:root{--bg:#0f172a;--panel:#151f36;--fg:#e5ebf5;--muted:#94a3b8;--line:#25324d;--accent:#3b82f6;
--up:#22c55e;--down:#ef4444;--warn:#f59e0b;--m20:#f59e0b;--m50:#3b82f6;--m100:#a855f7;--m200:#ef4444;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 var(--sans)}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid var(--line);background:var(--panel)}
h1{font-size:18px;margin:0;letter-spacing:.2px}h1 span{color:var(--muted);font-weight:400;font-size:13px;margin-left:8px}
nav{display:flex;gap:4px}nav button{border:1px solid var(--line);background:transparent;color:var(--fg);padding:7px 14px;border-radius:6px;cursor:pointer;font:inherit}
nav button.on{background:var(--accent);border-color:var(--accent);color:#fff}
main{padding:18px 20px;max-width:1400px;margin:0 auto}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
input,select{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--fg)}
button.b{font:inherit;padding:7px 12px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--fg);cursor:pointer}
button.b.p{background:var(--accent);border-color:var(--accent);color:#fff}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--panel)}
td:first-child,th:first-child,td.l,th.l{text-align:left}tr:hover td{background:color-mix(in srgb,var(--accent) 6%,transparent)}
.sym{font-weight:700;font-family:var(--mono);cursor:pointer;color:var(--accent)}.nm{color:var(--muted);font-size:12px;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.up{color:var(--up)}.down{color:var(--down)}.mut{color:var(--muted)}
@media(max-width:640px){header{padding:12px 14px}main{padding:14px}nav{width:100%}nav button{flex:1}.bar input{flex:1 1 100%;min-width:0;width:100%}}
.pill{display:inline-block;min-width:42px;text-align:center;padding:2px 8px;border-radius:999px;font-weight:700;font-family:var(--mono)}
.s-hi{background:color-mix(in srgb,var(--up) 18%,transparent);color:var(--up)}
.s-md{background:color-mix(in srgb,var(--warn) 20%,transparent);color:var(--warn)}
.s-lo{background:color-mix(in srgb,var(--down) 16%,transparent);color:var(--down)}
.ma{font-family:var(--mono);font-size:12px}.ma b{font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}.card .k{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted)}.card .v{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:2px}
.grid2{display:grid;grid-template-columns:2fr 1fr;gap:14px}@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;min-width:0}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted);margin-bottom:6px}.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:4px}
svg text{fill:var(--muted);font-size:10px;font-family:var(--mono)}
.bd{display:grid;grid-template-columns:1fr auto;gap:6px 10px;font-size:13px}.meter{grid-column:1/-1;height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-bottom:6px}.meter span{display:block;height:100%;background:var(--accent)}
.note{font-size:12px;color:var(--muted);margin-top:14px;max-width:80ch}
.err{color:var(--down)}.x{border:none;background:none;color:var(--muted);cursor:pointer;font-size:16px}
#sugs{display:flex;flex-wrap:wrap;gap:6px}#sugs button{font-size:12px}
</style></head><body>
<header><h1>Bolsa App<span id="upd"></span></h1>
<nav><button data-t="scan" class="on">Escáner</button><button data-t="port">Mi cartera</button><button data-t="det">Detalle</button></nav></header>
<main>
<section id="scan">
 <div class="bar"><input id="q" placeholder="Añadir símbolo o buscar (ej. AAPL, Inditex, SAN.MC)" size="38">
 <button class="b p" id="add">Añadir</button><button class="b" id="srch">Buscar</button>
 <select id="flt"><option value="all">Todos</option><option value="fav">Score ≥ 70</option><option value="os">RSI &lt; 30 (sobreventa)</option><option value="ob">RSI &gt; 70 (sobrecompra)</option><option value="up">Sobre MM200</option><option value="dn">Bajo MM200</option></select>
 <button class="b" id="ref">Actualizar precios</button><span id="st" class="mut"></span></div>
 <div id="sugs"></div>
 <div class="wrap"><table id="tscan"></table></div>
</section>
<section id="port" hidden>
 <div class="cards" id="pcards"></div>
 <div class="bar"><input id="ps" placeholder="Símbolo" size="10"><input id="pn" type="number" step="any" placeholder="Nº acciones" size="10"><input id="pc" type="number" step="any" placeholder="Precio medio de compra" size="16"><button class="b p" id="padd">Guardar posición</button></div>
 <div class="wrap"><table id="tport"></table></div>
</section>
<section id="det" hidden>
 <div class="bar"><input id="ds" placeholder="Símbolo" size="12"><button class="b p" id="dgo">Ver</button></div>
 <div id="dout" class="mut">Pulsa un símbolo en el escáner o en tu cartera para ver su gráfico.</div>
</section>
<p class="note"><b>Cómo se calcula el score (0-100):</b> Tendencia 40 pts (precio sobre MM200, MM100, MM50, MM20 y MM50 sobre MM200) · RSI 25 pts (máximo entre 30 y 45, mínimo por encima de 70) · Momentum 20 pts (MM20 subiendo y rentabilidad a 3 meses) · Punto de entrada 15 pts (cerca y por encima de la MM50, sin estar estirado). ≥70 Favorable, 50-69 Neutral, &lt;50 Desfavorable. Es un indicador técnico orientativo y no constituye asesoramiento financiero. Datos de Yahoo Finance, pueden tener retraso.</p>
</main>
<script>
const $=s=>document.querySelector(s);let DATA={watchlist:[],portfolio:[]},SCAN=[],sortK='score',sortD=-1;
const f=(v,d=2)=>v==null?'—':Number(v).toLocaleString('es-ES',{minimumFractionDigits:d,maximumFractionDigits:d});
const sg=v=>v==null?'—':`<span class="${v>=0?'up':'down'}">${v>=0?'+':''}${f(v)}%</span>`;
const pill=s=>`<span class="pill ${s>=70?'s-hi':s>=50?'s-md':'s-lo'}">${s}</span>`;
const rsiC=r=>r==null?'—':`<span class="${r>70?'down':r<30?'up':''}">${f(r,1)}</span>`;
async function api(p,o){const r=await fetch(p,o);const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
async function save(){DATA=await api('/api/data',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(DATA)})}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>tab(b.dataset.t));
function tab(t){document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));['scan','port','det'].forEach(id=>$('#'+id).hidden=id!==t);if(t==='port')renderPort()}
function maCell(x){const ns=['20','50','100','200'];return ns.map(n=>{const d=x.dist[n];return d==null?`<td class="ma mut">—</td>`:`<td class="ma"><b>${f(x.sma[n])}</b><br>${sg(d)}</td>`}).join('')}
async function loadScan(){ $('#st').textContent='Cargando '+DATA.watchlist.length+' valores…';
 try{SCAN=await api('/api/analyze?symbols='+encodeURIComponent(DATA.watchlist.join(',')));$('#st').textContent='';$('#upd').textContent='Actualizado '+new Date().toLocaleTimeString('es-ES')}
 catch(e){$('#st').innerHTML='<span class="err">No se pudieron cargar los datos: '+e.message+'</span>'}
 renderScan();if(!$('#port').hidden)renderPort()}
function renderScan(){const fl=$('#flt').value;let rows=SCAN.filter(x=>{if(x.error)return fl==='all';if(fl==='fav')return x.score>=70;if(fl==='os')return x.rsi<30;if(fl==='ob')return x.rsi>70;if(fl==='up')return x.dist['200']>0;if(fl==='dn')return x.dist['200']<0;return true});
 const key=x=>x.error?-1e9:sortK==='symbol'?x.symbol:sortK.startsWith('d')?(x.dist[sortK.slice(1)]??-1e9):(x[sortK]??-1e9);
 rows.sort((a,b)=>{const A=key(a),B=key(b);return (A>B?1:A<B?-1:0)*sortD});
 const H=[['symbol','Valor'],['price','Precio'],['change_pct','Día'],['d20','MM20'],['d50','MM50'],['d100','MM100'],['d200','MM200'],['rsi','RSI 14'],['ret_3m','3 meses'],['score','Score'],['','']];
 $('#tscan').innerHTML='<thead><tr>'+H.map(([k,t])=>`<th data-k="${k}">${t}${k===sortK?(sortD>0?' ▲':' ▼'):''}</th>`).join('')+'</tr></thead><tbody>'+rows.map(x=>x.error?
 `<tr><td><span class="sym">${x.symbol}</span></td><td colspan="9" class="l err">${x.error}</td><td><button class="x" data-del="${x.symbol}" title="Quitar">×</button></td></tr>`:
 `<tr><td><span class="sym" data-s="${x.symbol}">${x.symbol}</span><div class="nm">${x.name} · ${x.type}</div></td><td>${f(x.price)} <span class="mut">${x.currency}</span></td><td>${sg(x.change_pct)}</td>${maCell(x)}<td>${rsiC(x.rsi)}</td><td>${sg(x.ret_3m)}</td><td>${pill(x.score)}<div class="nm">${x.label}</div></td><td><button class="x" data-del="${x.symbol}" title="Quitar">×</button></td></tr>`).join('')+'</tbody>';
 $('#tscan').querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(!k)return;sortD=sortK===k?-sortD:-1;sortK=k;renderScan()});bindSyms($('#tscan'));
 $('#tscan').querySelectorAll('[data-del]').forEach(b=>b.onclick=async()=>{DATA.watchlist=DATA.watchlist.filter(s=>s!==b.dataset.del);SCAN=SCAN.filter(x=>x.symbol!==b.dataset.del);await save();renderScan()})}
function bindSyms(root){root.querySelectorAll('[data-s]').forEach(el=>el.onclick=()=>detail(el.dataset.s))}
async function addSym(s){s=s.trim().toUpperCase();if(!s)return;if(!DATA.watchlist.includes(s)){DATA.watchlist.push(s);await save()}$('#q').value='';$('#sugs').innerHTML='';
 const [r]=await api('/api/analyze?symbols='+encodeURIComponent(s));SCAN=SCAN.filter(x=>x.symbol!==s).concat([r]);renderScan()}
$('#add').onclick=()=>addSym($('#q').value);$('#q').onkeydown=e=>{if(e.key==='Enter')addSym($('#q').value)};
$('#srch').onclick=async()=>{const q=$('#q').value.trim();if(!q)return;try{const r=await api('/api/search?q='+encodeURIComponent(q));$('#sugs').innerHTML=r.length?r.map(x=>`<button class="b" data-a="${x.symbol}">${x.symbol} · ${x.name} (${x.exchange})</button>`).join(''):'<span class="mut">Sin resultados</span>';$('#sugs').querySelectorAll('[data-a]').forEach(b=>b.onclick=()=>addSym(b.dataset.a))}catch(e){$('#sugs').innerHTML='<span class="err">'+e.message+'</span>'}};
$('#flt').onchange=renderScan;$('#ref').onclick=loadScan;
async function renderPort(){const P=DATA.portfolio;const need=P.map(p=>p.symbol).filter(s=>!SCAN.find(x=>x.symbol===s));
 if(need.length){try{SCAN=SCAN.concat(await api('/api/analyze?symbols='+encodeURIComponent(need.join(','))))}catch(e){}}
 let tv={},tc={};const rows=P.map(p=>{const x=SCAN.find(y=>y.symbol===p.symbol)||{};const val=x.price!=null?x.price*p.shares:null,cost=p.cost*p.shares;const cur=x.currency||'?';
  if(val!=null){tv[cur]=(tv[cur]||0)+val;tc[cur]=(tc[cur]||0)+cost}
  return `<tr><td><span class="sym" data-s="${p.symbol}">${p.symbol}</span><div class="nm">${x.name||''}</div></td><td>${f(p.shares,p.shares%1?4:0)}</td><td>${f(p.cost)}</td><td>${f(x.price)} <span class="mut">${cur}</span></td><td>${f(val)}</td><td>${val==null?'—':`<span class="${val>=cost?'up':'down'}">${f(val-cost)}</span>`}</td><td>${sg(val==null?null:(val/cost-1)*100)}</td><td class="l">${x.error?'<span class="err">'+x.error+'</span>':x.dist?(['20','50','100','200'].map(n=>`<span class="ma">${n}:${x.dist[n]==null?'—':(x.dist[n]>=0?'▲':'▼')}</span>`).join(' ')):''}</td><td>${rsiC(x.rsi)}</td><td>${x.score!=null?pill(x.score):'—'}</td><td><button class="x" data-rm="${p.symbol}" title="Eliminar posición">×</button></td></tr>`}).join('');
 $('#pcards').innerHTML=Object.keys(tv).length?Object.keys(tv).map(c=>`<div class="card"><div class="k">Valor cartera (${c})</div><div class="v">${f(tv[c])}</div></div><div class="card"><div class="k">Ganancia / pérdida (${c})</div><div class="v ${tv[c]>=tc[c]?'up':'down'}">${f(tv[c]-tc[c])} · ${f((tv[c]/tc[c]-1)*100)}%</div></div>`).join(''):'<div class="card"><div class="k">Cartera</div><div class="v">Sin posiciones</div><div class="mut">Añade tu primera posición abajo.</div></div>';
 $('#tport').innerHTML='<thead><tr><th>Valor</th><th>Acciones</th><th>P. compra</th><th>Precio</th><th>Valor actual</th><th>G/P</th><th>G/P %</th><th class="l">Sobre medias</th><th>RSI</th><th>Score</th><th></th></tr></thead><tbody>'+(rows||'<tr><td colspan="11" class="l mut">Aún no hay posiciones.</td></tr>')+'</tbody>';
 bindSyms($('#tport'));$('#tport').querySelectorAll('[data-rm]').forEach(b=>b.onclick=async()=>{DATA.portfolio=DATA.portfolio.filter(p=>p.symbol!==b.dataset.rm);await save();renderPort()})}
$('#padd').onclick=async()=>{const s=$('#ps').value.trim().toUpperCase(),n=parseFloat($('#pn').value),c=parseFloat($('#pc').value);if(!s||!(n>0)||!(c>0))return;
 DATA.portfolio=DATA.portfolio.filter(p=>p.symbol!==s).concat([{symbol:s,shares:n,cost:c}]);await save();['#ps','#pn','#pc'].forEach(i=>$(i).value='');renderPort()};
$('#dgo').onclick=()=>detail($('#ds').value);
async function detail(s){s=(s||'').trim().toUpperCase();if(!s)return;tab('det');$('#ds').value=s;$('#dout').innerHTML='Cargando '+s+'…';
 try{const x=await api('/api/detail?symbol='+encodeURIComponent(s));
 $('#dout').innerHTML=`<div class="cards"><div class="card"><div class="k">${x.name}</div><div class="v">${f(x.price)} ${x.currency}</div><div>${sg(x.change_pct)} hoy</div></div>
 <div class="card"><div class="k">Score</div><div class="v">${pill(x.score)} ${x.label}</div></div><div class="card"><div class="k">RSI 14</div><div class="v">${rsiC(x.rsi)}</div><div class="mut">${x.rsi>70?'Sobrecompra':x.rsi<30?'Sobreventa':'Zona neutral'}</div></div>
 <div class="card"><div class="k">Rango 52 semanas</div><div class="v" style="font-size:15px">${f(x.low_52w)} – ${f(x.high_52w)}</div></div></div>
 <div class="grid2"><div class="panel"><div class="legend"><span><i style="background:var(--fg)"></i>Precio</span><span><i style="background:var(--m20)"></i>MM20 ${f(x.sma['20'])}</span><span><i style="background:var(--m50)"></i>MM50 ${f(x.sma['50'])}</span><span><i style="background:var(--m100)"></i>MM100 ${f(x.sma['100'])}</span><span><i style="background:var(--m200)"></i>MM200 ${f(x.sma['200'])}</span></div><div id="ch"></div></div>
 <div class="panel"><b>Desglose del score</b><div class="bd" style="margin-top:10px">${x.breakdown.map(b=>`<span>${b.name}</span><span>${b.points}/${b.max}</span><div class="meter"><span style="width:${b.points/b.max*100}%"></span></div>`).join('')}</div>
 <div style="margin-top:8px"><b>Distancia a las medias</b>${['20','50','100','200'].map(n=>`<div class="bd"><span>MM${n} (${f(x.sma[n])})</span><span>${sg(x.dist[n])}</span></div>`).join('')}</div></div></div>`;
 drawChart(x.history)}catch(e){$('#dout').innerHTML='<span class="err">No se pudo cargar '+s+': '+e.message+'</span>'}}
function drawChart(h){const W=900,H1=300,H2=110,P=48,n=h.close.length;const all=[...h.close,...h.sma20,...h.sma50,...h.sma100,...h.sma200].filter(v=>v!=null);
 const lo=Math.min(...all),hi=Math.max(...all),X=i=>P+i*(W-P-10)/(n-1),Y=v=>10+(hi-v)/(hi-lo||1)*(H1-20),R=v=>H1+14+(100-v)/100*(H2-20);
 const line=(a,c,w=1.4)=>{let d='';a.forEach((v,i)=>{if(v==null)return;d+=(d?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)});return `<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}"/>`};
 let g='';for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;g+=`<line x1="${P}" x2="${W-10}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="4" y="${Y(v)+3}">${f(v)}</text>`}
 [30,50,70].forEach(v=>g+=`<line x1="${P}" x2="${W-10}" y1="${R(v)}" y2="${R(v)}" stroke="var(--line)" ${v!==50?'stroke-dasharray="4 3"':''}/><text x="4" y="${R(v)+3}">${v}</text>`);
 let rd='';h.rsi.forEach((v,i)=>{if(v==null)return;rd+=(rd?'L':'M')+X(i).toFixed(1)+' '+R(v).toFixed(1)});
 const months=[];let pm=-1;h.t.forEach((t,i)=>{const d=new Date(t*1000);if(d.getMonth()!==pm){pm=d.getMonth();if(i>5)months.push(`<text x="${X(i)}" y="${H1+H2+12}" text-anchor="middle">${d.toLocaleDateString('es-ES',{month:'short'})}</text>`)}});
 $('#ch').innerHTML=`<svg viewBox="0 0 ${W} ${H1+H2+18}" width="100%" role="img" aria-label="Precio, medias móviles y RSI">${g}${line(h.sma200,'var(--m200)')}${line(h.sma100,'var(--m100)')}${line(h.sma50,'var(--m50)')}${line(h.sma20,'var(--m20)')}${line(h.close,'var(--fg)',1.8)}
 <circle cx="${X(n-1)}" cy="${Y(h.close[n-1])}" r="3.5" fill="var(--accent)"/><text x="${P}" y="${H1+10}">RSI 14</text><path d="${rd}" fill="none" stroke="var(--accent)" stroke-width="1.4"/>${months.join('')}</svg>`}
(async()=>{DATA=await api('/api/data');loadScan()})();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Bolsa App")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--lan", action="store_true", help="accesible desde el móvil en tu misma red wifi")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0" if a.lan else "127.0.0.1", a.port), Handler)
    url = f"http://localhost:{a.port}"
    print(f"Bolsa App en {url}  (Ctrl+C para salir)")
    if a.lan:
        import socket
        try:
            sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sk.connect(("8.8.8.8", 80))
            print(f"Desde el móvil: http://{sk.getsockname()[0]}:{a.port}")
            sk.close()
        except OSError:
            pass
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nHasta luego.")


if __name__ == "__main__":
    main()
