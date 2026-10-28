"""Gold bots live dashboard (READ-ONLY).  http://127.0.0.1:8090/   - binds to this PC only.
Reads each bot's own files (gold_2b_log.txt, gold_2b_trades.csv, gold_2b_state.json, gold_2b_guard.json, .env), the feed monitor's files, the bridge's /api/status, and the MT5 price.
It never sends an order and never writes to any bot folder.
Run:  python server.py        (Ctrl+C to stop)"""
import csv, json, os, re, subprocess, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(os.environ.get("DASH_ROOT") or Path(__file__).resolve().parent.parent)      # DASH_ROOT is only for testing the page with sample data
BOTS = [("v2A", "gold_v2A", "GoCharting bridge, 15m bars"), ("v2B", "gold_v2B", "MT5 tick footprint"), ("v2C", "gold_v2C", "GoCharting bridge, 5m bars")]
FEED = ROOT / "feed_watch"
# the 8 paper bots (RBVE / QuantEdge / PatternHunter15 / Gold 4H, each as A = bridge absorption gate and B = regular). They live in Test_bots_V1\bots8
ROOT8 = Path(os.environ.get("BOTS8_ROOT") or (ROOT.parent / "Test_bots_V1" / "bots8"))
BOTS8 = [("RBVE-A", "RBVE-A", "RBVE + bridge absorption gate"), ("RBVE-B", "RBVE-B", "RBVE regular"),
         ("QE-A", "QE-A", "QuantEdge + bridge absorption gate"), ("QE-B", "QE-B", "QuantEdge regular"),
         ("PH-A", "PH-A", "PatternHunter v1 + bridge absorption gate"), ("PH-B", "PH-B", "PatternHunter v1 regular (enter at pattern close, 1R)"),
         ("G4H-A", "G4H-A", "Gold 4H breakout + bridge absorption gate"), ("G4H-B", "G4H-B", "Gold 4H breakout regular"),
         ("PH2-B", "PH2-B", "PatternHunter v2 (all patterns, absorption filter, 1R)"), ("PH3-B", "PH3-B", "PatternHunter v3 (clean list, 4h filter, absorption 2x, TP1/TP2)")]
PH_RULEBOOK_IDS = ("PH2-B", "PH3-B")      # their absorption comes from the bridge's 15m bars inside the strategy (bots8\ph_engine.py), not from the A gate
FEED8 = ROOT8 / "data" / "absorption_feed.json"
BRIDGE = os.environ.get("BRIDGE_HOST", "127.0.0.1:8015")
PORT = int(os.environ.get("DASH_PORT", "8090"))
SYMBOL = os.environ.get("DASH_SYMBOL", "XAUUSD")        # USD account (was XAUUSDcent on the cent account)
UTC = timezone.utc

mt5 = None
try:
    import MetaTrader5 as _m
    if _m.initialize():
        mt5 = _m
except Exception:
    pass


def nth_sunday(y, m, n):
    d = datetime(y, m, 1, tzinfo=UTC); d += timedelta(days=(6 - d.weekday()) % 7); return d + timedelta(weeks=n - 1)


def broker_offset(ts):
    return 3 if nth_sunday(ts.year, 3, 2) <= ts < nth_sunday(ts.year, 11, 1) else 2


def env_of(folder, root=None):
    out = {}
    p = (root or ROOT) / folder / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); out[k.strip()] = v.strip()
    return out


def jget(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def tail(path, n):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []


import http.client, threading
_conn = {"c": None}
_cache = {}
_lock = threading.Lock()


def bridge_get(path, ttl=15):
    """one persistent keep-alive connection + a 15 s cache: the page polls every 5 s, but the bridge is only asked every 15 s (a Windows asyncio bug can wedge its listener when clients connect and drop a lot)"""
    with _lock:
        hit = _cache.get(path)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        data = None
        for _ in range(2):
            try:
                if _conn["c"] is None:
                    _conn["c"] = http.client.HTTPConnection(BRIDGE, timeout=5)
                _conn["c"].request("GET", path)
                r = _conn["c"].getresponse()
                body = r.read()
                data = json.loads(body.decode("utf-8")) if r.status == 200 else None
                break
            except Exception:
                try:
                    _conn["c"].close()
                except Exception:
                    pass
                _conn["c"] = None
        _cache[path] = (time.time(), data)
        return data


_proc = {"t": 0, "n": None}
def procs():
    if time.time() - _proc["t"] > 30:
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*gold_2b_bot.py*' } | Measure-Object).Count"],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
            _proc["n"] = int(out)
        except Exception:
            _proc["n"] = None
        _proc["t"] = time.time()
    return _proc["n"]


_proc8 = {"t": 0, "n": None, "feed": None}
def procs8():
    """running bots8 processes: (run_bot.py count, absfeed.py running)"""
    if time.time() - _proc8["t"] > 30:
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\"; (($p | Where-Object { $_.CommandLine -like '*run_bot.py*' } | Measure-Object).Count).ToString() + ',' + (($p | Where-Object { $_.CommandLine -like '*absfeed.py*' } | Measure-Object).Count).ToString()"],
                                 capture_output=True, text=True, timeout=20).stdout.strip().split(",")
            _proc8["n"], _proc8["feed"] = int(out[0]), int(out[1]) > 0
        except Exception:
            _proc8["n"], _proc8["feed"] = None, None
        _proc8["t"] = time.time()
    return _proc8["n"], _proc8["feed"]


def feed8():
    """state of the shared absorption feed the A bots read (bots8\\absfeed.py -> data\\absorption_feed.json)"""
    d = jget(FEED8)
    if not d:
        return dict(ok=False, age_s=None, connected=False, bars=0, recent=[])
    bars = d.get("bars", [])
    flagged = [b for b in bars if b.get("buy") or b.get("sell")][-4:]
    return dict(ok=True, age_s=int(time.time() - d.get("updated", 0)), connected=bool(d.get("connected")) and (time.time() - d.get("updated", 0)) < 90, bars=len(bars), last_event_age_s=int(time.time() - d["last_event"]) if d.get("last_event") else None,
                recent=[dict(tf=b["tf"], t=datetime.fromtimestamp(b["t"], UTC).strftime("%H:%M"), side="buy" if b.get("buy") else "sell") for b in flagged])


def price():
    if not mt5:
        return None
    t = mt5.symbol_info_tick(SYMBOL)
    if t is None:
        return None
    now = datetime.now(UTC)
    age = int(now.timestamp() + broker_offset(now) * 3600 - t.time)
    return dict(bid=t.bid, ask=t.ask, age_s=age, market_open=age < 180, broker_time=datetime.fromtimestamp(t.time, UTC).strftime("%Y-%m-%d %H:%M:%S"))


def trades_of(folder, root=None):
    p = (root or ROOT) / folder / "gold_2b_trades.csv"
    rows = []
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    r["pnl_usc"] = float(r["pnl_usc"]); r["entry"] = float(r["entry"]); r["exit"] = float(r["exit"]); rows.append(r)
                except Exception:
                    pass
    return rows


def bot_state(bid, folder, desc, px, ws_names, nprocs, root=None):
    d = (root or ROOT) / folder
    env = env_of(folder, root)
    tr = trades_of(folder, root)
    pnls = [r["pnl_usc"] for r in tr]
    won, lost = [x for x in pnls if x > 0], [x for x in pnls if x < 0]
    cum, peak, dd, curve = 0.0, 0.0, 0.0, []
    for r in tr:
        cum += r["pnl_usc"]; peak = max(peak, cum); dd = max(dd, peak - cum); curve.append([r["closed"], round(cum, 2)])
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    today_pnl = round(sum(r["pnl_usc"] for r in tr if str(r["closed"]).startswith(today)), 2)
    pos = jget(d / "gold_2b_state.json")
    floating = None
    if pos and px:
        mark = px["bid"] if pos["side"] > 0 else px["ask"]
        floating = round(pos.get("banked", 0.0) + pos["side"] * (mark - pos["entry"]) * pos.get("vol", 1.0), 2)     # vol/banked only exist on the bots8 paper bots (partial closes)
    guard = jget(d / "gold_2b_guard.json", {})
    log = tail(d / "gold_2b_log.txt", 400)
    events = [l for l in log if any(k in l for k in ("signal", "OPENED", "CLOSED", "retest", "NO NEW TRADE", "KILL", "BREAK-EVEN", "bridge", "ERROR", "EARLY", "engulfing", "NO TRADE"))][-30:]
    src = env.get("ABSORPTION_SOURCE", "?")
    connected = None
    if src == "bridge":
        connected = "gold-v2A" in (ws_names or [])
    elif src == "bridge5":
        connected = "gold-v2C" in (ws_names or [])
    sigs = sum(1 for l in log if " signal " in l)
    return dict(id=bid, folder=folder, desc=desc, profile=env.get("PROFILE", "?"), source=src, dry_run=env.get("DRY_RUN", "true"), magic=env.get("MAGIC"), connected=connected,
                trades=len(tr), won=len(won), lost=len(lost), win_pct=round(100 * len(won) / len(tr), 1) if tr else None, profit=round(sum(won), 2), loss=round(sum(lost), 2), net=round(cum, 2),
                biggest_loss=round(min(pnls), 2) if lost else 0, max_dd=round(dd, 2), today=today_pnl, floating=floating, equity=round(cum + (floating or 0), 2),
                position=pos, guard=guard, curve=curve[-300:], recent=tr[-25:][::-1], events=events[::-1], signals_logged=sigs,
                last_log=log[-1] if log else None, log_mtime=(datetime.fromtimestamp((d / "gold_2b_log.txt").stat().st_mtime, UTC).strftime("%Y-%m-%d %H:%M:%S") if (d / "gold_2b_log.txt").exists() else None))


PH15_CSV = os.environ.get("PH15_CSV")
if not PH15_CSV:
    _c = sorted(Path(os.environ.get("APPDATA", "")).glob("MetaQuotes/Terminal/*/MQL5/Files/PH15_dry_run.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    PH15_CSV = str(_c[0]) if _c else None
_ph_entry = re.compile(r"^(BUY|SELL) (\S+) (.*?) price=([\d.]+) sl=([\d.]+) tp1=([\d.]+) tp2=([\d.]+) stop_pts=([\d.]+) lots=([\d.]+) absorption=(\w+)")
_ph_exit = re.compile(r"^(BUY|SELL) (\S+) (.*?) exit=([\d.]+) result=(\S+) pnl=(-?[\d.]+)")
_ph_tp1 = re.compile(r"closed ([\d.]+) lots at ([\d.]+)")


def ph15_state(px):
    """PatternHunter15 (PH15_Rulebook EA, MT5, dry run): rebuilt from PH15_dry_run.csv (ENTRY/PENDING/FILLED/TP1/EXIT/CANCEL lines; pnl is already in USC)"""
    rows = []
    mtime = None
    if PH15_CSV and Path(PH15_CSV).exists():
        mtime = datetime.fromtimestamp(Path(PH15_CSV).stat().st_mtime, UTC).strftime("%Y-%m-%d %H:%M:%S")
        for line in Path(PH15_CSV).read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
            p = line.split(",", 3)
            if len(p) == 4:
                rows.append(p)
    tr, pos, cur, signals = [], None, None, 0
    for t, ev, sym, det in rows:
        if ev in ("ENTRY", "PENDING"):
            m = _ph_entry.match(det)
            if m:
                signals += 1
                cur = dict(side=1 if m[1] == "BUY" else -1, level=m[2], pattern=m[3], entry=float(m[4]), sl=float(m[5]), tp1=float(m[6]), tp=float(m[7]), lots=float(m[9]), rem=float(m[9]), banked=0.0,
                           mode="absorption x2" if m[10] == "yes" else "normal", opened=t, active=(ev == "ENTRY"))
        elif ev == "FILLED" and cur:
            cur["active"] = True; cur["opened"] = t
        elif ev == "CANCEL":
            cur = None
        elif ev == "TP1" and cur:
            m = _ph_tp1.search(det)
            if m:
                part = float(m[1]); cur["banked"] += (float(m[2]) - cur["entry"]) * cur["side"] * part * 100.0; cur["rem"] = cur["lots"] - part; cur["sl"] = cur["entry"]
        elif ev == "EXIT":
            m = _ph_exit.match(det)
            if m and cur:
                tr.append(dict(closed=t, side=m[1], pattern=f"{cur['pattern']} @{cur['level']}", entry=cur["entry"], exit=float(m[4]), pnl_usc=float(m[6]), reason=m[5]))
            cur = None
    if cur and cur["active"]:
        pos = dict(side=cur["side"], pattern=f"{cur['pattern']} @{cur['level']}", mode=cur["mode"], entry=cur["entry"], tp=cur["tp"], sl=cur["sl"], opened=cur["opened"])
    pnls = [r["pnl_usc"] for r in tr]
    won, lost = [x for x in pnls if x > 0], [x for x in pnls if x < 0]
    cum, peak, dd, curve = 0.0, 0.0, 0.0, []
    for r in tr:
        cum += r["pnl_usc"]; peak = max(peak, cum); dd = max(dd, peak - cum); curve.append([r["closed"], round(cum, 2)])
    broker_today = (datetime.now(UTC) + timedelta(hours=broker_offset(datetime.now(UTC)))).strftime("%Y-%m-%d")
    floating = None
    if pos and px:
        mark = px["bid"] if cur["side"] > 0 else px["ask"]
        floating = round(cur["banked"] + (mark - cur["entry"]) * cur["side"] * cur["rem"] * 100.0, 2)
    events = [f"{t} {ev} {det}" for t, ev, sym, det in rows][-30:]
    return dict(id="PH15", folder="PatternHunter15", desc="PatternHunter15 Rulebook v3 (MT5 EA, lot 0.10)", profile="v3", source="bridge file", dry_run="true", magic="15160001", connected=None, nokill=True,
                trades=len(tr), won=len(won), lost=len(lost), win_pct=round(100 * len(won) / len(tr), 1) if tr else None, profit=round(sum(won), 2), loss=round(sum(lost), 2), net=round(cum, 2),
                biggest_loss=round(min(pnls), 2) if lost else 0, max_dd=round(dd, 2), today=round(sum(r["pnl_usc"] for r in tr if str(r["closed"]).replace(".", "-").startswith(broker_today)), 2), floating=floating,
                equity=round(cum + (floating or 0), 2), position=pos, guard={}, curve=curve[-300:], recent=tr[-25:][::-1], events=events[::-1], signals_logged=signals, last_log=events[-1] if events else None, log_mtime=mtime)


app = FastAPI(title="Gold bots dashboard")
try:                                                    # /multi = the 21 paper bots of gold_v2_multi (separate module so it never clashes with edits to this file)
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from multi_view import router as _multi_router
    app.include_router(_multi_router)
except Exception as _e:
    print("multi view not loaded:", _e)
try:                                                    # /live = REAL trades of the MT5 account, read-only (separate module)
    from live_view import router as _live_router
    app.include_router(_live_router)
except Exception as _e:
    print("live view not loaded:", _e)
try:
    from forward_view import router as _forward_router
    app.include_router(_forward_router)
except Exception as _e:
    print("forward view not loaded:", _e)


@app.get("/api/state")
def state():
    px = price()
    st = bridge_get("/api/status")
    ws = [b["name"] for b in (st or {}).get("bots", {}).get("websocket", [])] if st else None
    latest = {}
    for tf in (5, 15):
        b = bridge_get(f"/api/latest?symbol=XAUUSD&tf={tf}")
        if b:
            t = datetime.strptime(b["time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            ab = ((b.get("features") or {}).get("absorption")) or {}
            latest[tf] = dict(open=b["time"], broker_time=b["broker_time"], close_age_s=int((datetime.now(UTC) - t).total_seconds() - tf * 60), source=b.get("source"), order_flow=b.get("delta") is not None,
                              delta=b.get("delta"), volume=b.get("volume"), buy=bool(ab.get("buy")), sell=bool(ab.get("sell")), close=b.get("close"))
    n = procs()
    bots = [bot_state(i, f, d, px, ws, n) for i, f, d in BOTS]
    try:
        bots.append(ph15_state(px))
    except Exception as e:
        print("ph15_state failed:", e)
    f8 = feed8()
    for i, f, d in BOTS8:
        try:
            b8 = bot_state(i, f, d, px, ws, n, root=ROOT8 / "bots")
            b8["group"] = "A" if i.endswith("-A") else "B"
            b8["connected"] = (f8["ok"] and f8["connected"] and f8["age_s"] is not None and f8["age_s"] < 90) if b8["group"] == "A" else None
            b8["source"] = "bridge gate" if b8["group"] == "A" else "none (regular)"
            if i in PH_RULEBOOK_IDS:
                b8["connected"], b8["source"], b8["group"] = None, "bridge 15m flag (built in)", "R"
            bots.append(b8)
        except Exception as e:
            print("bots8 state failed:", i, e)
    n8, feed_proc = procs8()
    summ = (FEED / "feed_summary.txt")
    return dict(now=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"), price=px, bridge=dict(up=st is not None, last_webhook=(st or {}).get("last_webhook"), counts=(st or {}).get("counts"), ws=ws, latest=latest),
                procs=n, procs8=n8, procs8_expected=len(BOTS8), feed8=dict(f8, process=feed_proc), feed_summary=summ.read_text(encoding="utf-8") if summ.exists() else None, feed_log=tail(FEED / "feed_watch.log", 8)[::-1], bots=bots)


@app.get("/api/replay")
def replay_data():
    p = Path(__file__).resolve().parent / "replay_data.json"      # built by build_replay.py; simulated trades only
    return JSONResponse(json.loads(p.read_text(encoding="utf-8")) if p.exists() else {})


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Gold Bots Live</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--mut:#6a7280;--line:#e2e5ea;--ok:#127a3d;--bad:#b3261e;--warn:#9a6700;--acc:#1f5fbf;--a:#1f5fbf;--b:#127a3d;--c:#b4540a}
@media(prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--ink:#e8eaed;--mut:#9aa3af;--line:#272d36;--ok:#4cc38a;--bad:#ff7b72;--warn:#e3b341;--acc:#6ea8ff;--a:#6ea8ff;--b:#4cc38a;--c:#f0883e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 2px}h2{font-size:15px;margin:0 0 8px}.sub{color:var(--mut);font-size:12px}
.grid{display:grid;gap:12px}.g3{grid-template-columns:repeat(3,1fr)}.g2{grid-template-columns:1.1fr 1fr}@media(max-width:1150px){.g3{grid-template-columns:1fr}}@media(max-width:900px){.g2{grid-template-columns:1fr}.kpi{grid-template-columns:repeat(2,1fr)!important}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}.chip{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:1px 9px;font-size:12px;margin:0 4px 4px 0}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.mut{color:var(--mut)}b.n{font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:4px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600}
.kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:8px 0}.kpi div{background:var(--bg);border-radius:8px;padding:6px 8px}.kpi span{display:block;font-size:11px;color:var(--mut)}.kpi b{font-size:16px}
canvas{width:100%;height:110px;display:block}.log{font:12px/1.4 ui-monospace,Consolas,monospace;max-height:190px;overflow:auto;white-space:pre-wrap;color:var(--mut)}
.pos{border:1px dashed var(--line);border-radius:8px;padding:8px;margin:6px 0;font-size:13px}pre{margin:0;white-space:pre-wrap;font:12px/1.4 ui-monospace,Consolas,monospace}
</style></head><body><div class=wrap>
<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap"><div><h1>Gold bots - live (paper / dry run)</h1><div class=sub>Read-only. Refreshes every 5 s. P&amp;L in account currency (USD). Paper bots are sized at 0.01 lot, so a $1 gold move = $1 of paper P&amp;L; the live page shows real deals. Trade times are broker time. <a href="/forward">Forward test: version 1 vs version 2</a> · <a href="/multi">Multi-runner</a></div></div><div class=sub id=upd></div></div>
<div class="grid g2" style="margin-top:12px"><div class=card><h2>Price and feed</h2><div id=feed></div></div><div class=card><h2>Comparison</h2><div id=cmp></div></div></div>
<div class=card style="margin-top:12px"><h2>Absorption gate: A (bridge absorption on every entry) vs B (regular)</h2><div id=ab></div></div>
<div class="grid g3" id=bots style="margin-top:12px"></div>
<div class=card style="margin-top:12px"><h2>Feed monitor verdict</h2><pre id=verdict class=mut></pre><div class=log id=feedlog style="margin-top:6px"></div></div>
<div class=card style="margin-top:12px;border:2px dashed var(--warn)"><h2>REPLAY / BACKTEST - simulated, not live paper trades</h2><div class=sub id=rpnote></div><div id=rp></div></div>
</div><script>
const f=(x,d=2)=>x==null?'-':Number(x).toFixed(d);const sg=x=>x==null?'-':(x>0?'+':'')+Number(x).toFixed(2);const cl=x=>x>0?'ok':x<0?'bad':'mut';
const col={v2A:'var(--a)',v2B:'var(--b)',v2C:'var(--c)',PH15:'var(--warn)','RBVE-A':'#e0556e','RBVE-B':'#e58a9a','QE-A':'#2f9ed6','QE-B':'#7cc3e6','PH-A':'#c9a227','PH-B':'#dcc56e','G4H-A':'#8b5cf6','G4H-B':'#b39cf9','PH2-B':'#d9822b','PH3-B':'#1fa37a'};
function chip(t,k){return `<span class="chip ${k||''}">${t}</span>`}
function curve(cv,pts,color){const c=cv.getContext('2d');const w=cv.width=cv.clientWidth*2,h=cv.height=cv.clientHeight*2;c.clearRect(0,0,w,h);const css=getComputedStyle(document.documentElement);
 c.strokeStyle=css.getPropertyValue('--line');c.lineWidth=2;c.beginPath();c.moveTo(0,h/2);c.lineTo(w,h/2);c.stroke();
 if(!pts.length){c.fillStyle=css.getPropertyValue('--mut');c.font='22px system-ui';c.fillText('no closed trades yet',16,h/2-10);return}
 const v=[0,...pts.map(p=>p[1])];const mn=Math.min(...v),mx=Math.max(...v),r=(mx-mn)||1;c.strokeStyle=color.startsWith('var')?css.getPropertyValue(color.slice(4,-1)):color;c.lineWidth=3;c.beginPath();
 v.forEach((y,i)=>{const X=i/(v.length-1||1)*(w-8)+4,Y=h-8-(y-mn)/r*(h-16);i?c.lineTo(X,Y):c.moveTo(X,Y)});c.stroke()}
async function tick(){let s;try{s=await (await fetch('/api/state')).json()}catch(e){document.getElementById('upd').textContent='dashboard server not reachable';return}
 document.getElementById('upd').textContent='updated '+s.now+' UTC';
 const p=s.price,b=s.bridge,L=b.latest;let h='';
 h+=p?`<div>XAUUSD <b class=n>${f(p.bid)}</b> / ${f(p.ask)} ${chip(p.market_open?'market OPEN':'market closed (last tick '+p.age_s+' s ago, '+p.broker_time+')',p.market_open?'ok':'warn')}</div>`:'<div class=bad>MT5 price not available</div>';
 h+=`<div style="margin-top:6px">${chip('bridge '+(b.up?'up':'DOWN'),b.up?'ok':'bad')}${chip('bots running '+(s.procs??'?')+'/3',s.procs==3?'ok':'bad')}${chip('webhooks '+(b.counts?b.counts.webhooks:'-'))}${chip('paper bots ('+(s.procs8_expected||8)+') running '+(s.procs8??'?')+'/'+(s.procs8_expected||8),s.procs8==(s.procs8_expected||8)?'ok':'bad')}</div>`;
 const f8=s.feed8||{};h+=`<div class=sub style="margin-top:4px">A-bot absorption feed: ${f8.ok?(f8.connected?'<span class=ok>connected to bridge</span>':'<span class=bad>bridge not connected</span>')+' | file '+f8.age_s+' s old | '+f8.bars+' bars | last flags: '+((f8.recent||[]).map(r=>r.tf+'m '+r.t+' '+r.side).join(', ')||'none')+(f8.process===false?' | <span class=bad>absfeed.py NOT running</span>':''):'<span class=bad>no feed file (start bots8\\absfeed.py)</span>'}</div>`;
 for(const tf of [5,15]){const x=L[tf];h+=x?`<div class=sub>${tf}m bridge bar ${x.broker_time} broker | source <b>${x.source}</b> | order flow ${x.order_flow?'<span class=ok>yes</span>':'<span class=bad>NO</span>'} | closed ${x.close_age_s>3600?Math.round(x.close_age_s/3600)+' h':Math.round(x.close_age_s/60)+' min'} ago | absorption buy=${x.buy} sell=${x.sell}</div>`:`<div class="sub bad">${tf}m: no bar</div>`}
 h+=`<div class=sub style="margin-top:4px">connected to bridge: ${(b.ws||[]).filter(n=>n.startsWith('gold')).join(', ')||'none'}</div>`;document.getElementById('feed').innerHTML=h;
 let t='<table><tr><th>Bot</th><th>Trades</th><th>W/L</th><th>Win%</th><th>Net</th><th>Today</th><th>Open</th><th>Max DD</th><th>Biggest loss</th></tr>';
 s.bots.forEach(x=>{t+=`<tr><td style="color:${col[x.id]}"><b>${x.id}</b> <span class=mut>${x.profile}</span></td><td>${x.trades}</td><td>${x.won}/${x.lost}</td><td>${x.win_pct==null?'-':x.win_pct}</td><td class="${cl(x.net)}"><b class=n>${sg(x.net)}</b></td><td class="${cl(x.today)}">${sg(x.today)}</td><td class="${cl(x.floating)}">${x.position?sg(x.floating):'-'}</td><td>${f(x.max_dd)}</td><td class=bad>${f(x.biggest_loss)}</td></tr>`});
 document.getElementById('cmp').innerHTML=t+'</table><div class=sub style="margin-top:6px">Net = closed paper trades. Open = floating P&amp;L of the open paper position. Kill switch trips at 500 USC below the best point; daily loss limit 200 USC.</div>';
 const grp={};s.bots.forEach(x=>{const m=/^(RBVE|QE|PH|G4H)-([AB])$/.exec(x.id);if(m){(grp[m[1]]=grp[m[1]]||{})[m[2]]=x}});
 let ab='<table><tr><th>Strategy</th><th>A trades</th><th>A win%</th><th>A net</th><th>A open</th><th>B trades</th><th>B win%</th><th>B net</th><th>B open</th><th>A - B (net)</th></tr>';
 Object.keys(grp).forEach(k=>{const a=grp[k].A,r=grp[k].B;if(!a||!r)return;ab+=`<tr><td><b>${k}</b></td><td>${a.trades}</td><td>${a.win_pct==null?'-':a.win_pct}</td><td class="${cl(a.net)}">${sg(a.net)}</td><td>${a.position?'yes':'-'}</td><td>${r.trades}</td><td>${r.win_pct==null?'-':r.win_pct}</td><td class="${cl(r.net)}">${sg(r.net)}</td><td>${r.position?'yes':'-'}</td><td class="${cl(a.net-r.net)}"><b class=n>${sg(a.net-r.net)}</b></td></tr>`});
 document.getElementById('ab').innerHTML=ab+'</table><div class=sub style="margin-top:6px">A takes a strategy signal only if the bridge shows same-direction absorption on a bridge 5-minute bar in the last 30-60 min before the signal bar closed; B takes every signal. Same strategy code, same prices, paper only (USC, 1 unit = $1 move = 1 USC).</div>';
 const host=document.getElementById('bots');if(!host.children.length){s.bots.forEach(x=>{host.insertAdjacentHTML('beforeend',`<div class=card id=card-${x.id}></div>`)})}
 s.bots.forEach(x=>{const el=document.getElementById('card-'+x.id);const g=x.guard||{};const feedBad=(x.connected===false);
  let c=`<h2 style="color:${col[x.id]}">${x.id} <span class=mut style="font-weight:400">${x.desc}</span></h2>`;
  c+=chip(x.dry_run=='true'?'PAPER (dry run)':'LIVE ORDERS',x.dry_run=='true'?'ok':'bad')+chip('profile '+x.profile)+chip('absorption: '+x.source)+(x.connected==null?'':chip(x.connected?'bridge connected':'bridge NOT connected',x.connected?'ok':'bad'))+(x.nokill?'':g.halted?chip('KILL SWITCH HALTED','bad'):chip('kill switch ok','ok'));
  c+=`<div class=kpi><div><span>Net (closed)</span><b class="n ${cl(x.net)}">${sg(x.net)}</b></div><div><span>Equity incl. open</span><b class="n ${cl(x.equity)}">${sg(x.equity)}</b></div><div><span>Today</span><b class="n ${cl(x.today)}">${sg(x.today)}</b></div><div><span>Max drawdown</span><b class=n>${f(x.max_dd)}</b></div>
   <div><span>Trades</span><b class=n>${x.trades}</b></div><div><span>Won / lost</span><b class=n>${x.won} / ${x.lost}</b></div><div><span>Profit / loss</span><b class=n>${sg(x.profit)} / ${sg(x.loss)}</b></div><div><span>Signals logged</span><b class=n>${x.signals_logged}</b></div></div>`;
  if(x.position){const q=x.position;c+=`<div class=pos><b>OPEN (paper)</b> ${q.side>0?'BUY':'SELL'} ${q.pattern||''} (${q.mode}) entry ${f(q.entry)} | target ${f(q.tp)} | stop ${f(q.sl)} | opened ${q.opened}<br>floating <b class="${cl(x.floating)}">${sg(x.floating)} USC</b></div>`}else c+=`<div class="pos mut">No open position.</div>`;
  c+=`<canvas id=cv-${x.id}></canvas><div class=sub>cumulative closed P&amp;L (USC)</div>`;
  c+=`<h2 style="margin-top:10px">Recent trades</h2>`+(x.recent.length?'<table><tr><th>Closed</th><th>Side</th><th>Pattern</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Why</th></tr>'+x.recent.slice(0,10).map(r=>`<tr><td>${String(r.closed).slice(5,16)}</td><td>${r.side}</td><td>${r.pattern||''}</td><td>${f(r.entry)}</td><td>${f(r.exit)}</td><td class="${cl(r.pnl_usc)}">${sg(r.pnl_usc)}</td><td>${r.reason}</td></tr>`).join('')+'</table>':'<div class=mut>none yet</div>');
  c+=`<h2 style="margin-top:10px">Bot events</h2><div class=log>${(x.events.length?x.events:['(nothing logged yet)']).slice(0,14).join('\n').replace(/</g,'&lt;')}</div><div class=sub>log last written ${x.log_mtime||'-'}</div>`;
  el.innerHTML=c;curve(document.getElementById('cv-'+x.id),x.curve,col[x.id])});
 document.getElementById('verdict').textContent=s.feed_summary||'(feed monitor has not written a summary yet)';document.getElementById('feedlog').textContent=(s.feed_log||[]).join('\n')}
tick();setInterval(tick,5000);
async function loadReplay(){let d;try{d=await (await fetch('/api/replay')).json()}catch(e){return}if(!d.gold)return;
 document.getElementById('rpnote').textContent=d.note+' Built '+d.built+' (python build_replay.py to refresh).';
 let h='<h2 style="margin-top:8px">Gold v2 profiles, backtest 12 Feb - 15 Oct 2026 (USC)</h2><table><tr><th>Profile</th><th>B trades</th><th>B win%</th><th>B net</th><th>B max DD</th><th>B PF</th><th>A trades</th><th>A net</th><th>A max DD</th><th>A PF</th></tr>';
 const A={};d.gold.summary.V2A_gocharting.forEach(r=>A[r.bot]=r);
 d.gold.summary.V2B_ticks.slice().sort((x,y)=>y.net-x.net).forEach(r=>{const a=A[r.bot]||{};h+=`<tr><td><b>${r.bot}</b></td><td>${r.trades}</td><td>${r.win_pct}</td><td class="${cl(+r.net)}"><b class=n>${sg(+r.net)}</b></td><td>${r.max_dd}</td><td>${r.pf}</td><td>${a.trades||'-'}</td><td class="${cl(+a.net)}">${a.net==null?'-':sg(+a.net)}</td><td>${a.max_dd||'-'}</td><td>${a.pf||'-'}</td></tr>`});
 h+='</table><div class=sub>B = tick-footprint absorption, A = GoCharting bridge absorption. Sorted by B net.</div>';
 h+='<h2 style="margin-top:14px">Top 3 gold profiles: cumulative curve and last trades</h2><div class="grid g3">';
 d.gold.top.forEach((t,i)=>{h+=`<div><b>${t.profile}</b> <span class=mut>(${t.source})</span><canvas id=rpg-${i}></canvas><table><tr><th>Closed</th><th>Side</th><th>P&amp;L</th><th>Result</th></tr>${t.recent.slice(0,6).map(r=>`<tr><td>${r.closed.slice(5,16)}</td><td>${r.side}</td><td class="${cl(r.pnl)}">${sg(r.pnl)}</td><td>${r.result}</td></tr>`).join('')}</table></div>`});
 h+='</div><h2 style="margin-top:14px">bots8 strategies, replay of last ~2,500 M15 bars (USD points)</h2><div class="grid g3">';
 Object.keys(d.replay).forEach(k=>{const r=d.replay[k];h+=`<div><b>${k}</b> ${chip(r.signals+' signals')}${chip(r.tp+' TP / '+r.sl+' SL')}<b class="n ${cl(r.net)}">${sg(r.net)}</b><canvas id=rpr-${k}></canvas><table><tr><th>Time</th><th>Side</th><th>Pattern</th><th>Result</th><th>P&amp;L</th></tr>${r.trades.slice(0,8).map(x=>`<tr><td>${x.time.slice(5)}</td><td>${x.side}</td><td>${x.pattern}</td><td>${x.result}</td><td class="${cl(x.pnl)}">${x.pnl==null?'-':sg(x.pnl)}</td></tr>`).join('')}</table></div>`});
 document.getElementById('rp').innerHTML=h+'</div>';
 d.gold.top.forEach((t,i)=>curve(document.getElementById('rpg-'+i),t.curve,i%3==0?'var(--a)':i%3==1?'var(--b)':'var(--c)'));
 Object.keys(d.replay).forEach(k=>curve(document.getElementById('rpr-'+k),d.replay[k].curve,'var(--warn)'))}
loadReplay();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


if __name__ == "__main__":
    print(f"Gold bots dashboard: http://127.0.0.1:{PORT}/  (read-only; Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
