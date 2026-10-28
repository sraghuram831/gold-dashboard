"""/live page of the Gold dashboard: REAL trades on the MT5 account (read-only).  Reads the account, open positions and closed deals straight from MT5, groups them by magic number (= bot) and shows
balance / equity, open positions with floating P&L, today's and recent closed trades, and the four bots you want to run live (v2C v3_v2, G4H-A, QE-A, PH15 v3).  It NEVER sends an order.
Included by server.py with:  from live_view import router; app.include_router(router)"""
import csv, json, subprocess, threading, time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parent.parent                 # Gold_basket_bot
SYMBOL = "XAUUSD"
UTC = timezone.utc
router = APIRouter()
_lock = threading.Lock()
mt5 = None
try:
    import MetaTrader5 as _m
    if _m.initialize():
        mt5 = _m
except Exception:
    pass

# the four bots to run live: label -> (magic number, kind)
WANTED = {262504: ("v2C v3_v2", "gold"), 870041: ("G4H-A", "bots8"), 870021: ("QE-A", "bots8"), 15160001: ("PH15 v3 (EA)", "ea")}
PATHS = {"v2C v3_v2": ROOT / "gold_v2C", "G4H-A": ROOT.parent / "Test_bots_V1" / "bots8" / "bots" / "G4H-A", "QE-A": ROOT.parent / "Test_bots_V1" / "bots8" / "bots" / "QE-A"}


def nth_sunday(y, m, n):
    d = datetime(y, m, 1, tzinfo=UTC); d += timedelta(days=(6 - d.weekday()) % 7); return d + timedelta(weeks=n - 1)


def broker_off(ts):
    return 3 if nth_sunday(ts.year, 3, 2) <= ts < nth_sunday(ts.year, 11, 1) else 2


def env_of(p):
    out = {}
    f = Path(p) / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); out[k.strip()] = v.strip()
    return out


_procs = {"t": 0, "txt": ""}
def proc_text():
    if time.time() - _procs["t"] > 30:
        try:
            _procs["txt"] = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.CommandLine }) -join [char]10"],
                                           capture_output=True, text=True, timeout=25).stdout
        except Exception:
            pass
        _procs["t"] = time.time()
    return _procs["txt"]


def mode_of(label):
    """what each bot is right now: LIVE orders, PAPER, or cannot trade live at all"""
    txt = proc_text()
    if label == "v2C v3_v2":
        e = env_of(PATHS[label])
        live = e.get("DRY_RUN", "true").lower() == "false" and e.get("ALLOW_REAL", "false").lower() == "true"
        running = "gold_2b_bot.py" in txt                                # the single v2C bot (the paper runner is multi_runner.py)
        return dict(mode="LIVE ORDERS (armed)" if live else "PAPER (dry run)", note="orders need DRY_RUN=false and ALLOW_REAL=true in gold_v2C\\.env" if not live else "settings allow real orders; sends none unless the bot is running", running=running)
    if label in ("G4H-A", "QE-A"):
        e = env_of(ROOT / "live_bots8" / "bots" / label)                  # the live-capable copy (live_bots8); the paper originals in Test_bots_V1 cannot send orders
        live = e.get("DRY_RUN", "true").lower() == "false" and e.get("ALLOW_REAL", "false").lower() == "true"
        running = f"run_live.py {label}" in txt
        return dict(mode="LIVE ORDERS" if live else "PAPER (live-capable)", note=("real orders from live_bots8" if live else "real orders need DRY_RUN=false and ALLOW_REAL=true in live_bots8\\bots\\" + label + "\\.env"), running=running)
    if label == "PH15 v3 (EA)":
        return dict(mode="MT5 EA (dry-run file)", note="live/dry-run is an input of the EA inside MT5; this page shows its real deals once it trades", running=None)
    return dict(mode="?", note="", running=None)


def label_of(magic, comment_by_magic):
    if magic in WANTED:
        return WANTED[magic][0]
    if magic == 0:
        return "manual / no magic"
    c = comment_by_magic.get(magic)
    return f"other bot {magic}" + (f" ({c})" if c else "")


def collect(days):
    now = datetime.now(UTC).replace(tzinfo=None)
    off = broker_off(datetime.now(UTC))
    bnow = now + timedelta(hours=off)
    today0 = datetime(bnow.year, bnow.month, bnow.day)
    with _lock:
        ai = mt5.account_info(); ti = mt5.terminal_info()
        pos = list(mt5.positions_get() or [])
        deals = list(mt5.history_deals_get(now - timedelta(days=days + 1), now + timedelta(days=1)) or [])
        tick = mt5.symbol_info_tick(SYMBOL)
    comment_by_magic = {}
    byp = defaultdict(list)
    for d in deals:
        byp[d.position_id].append(d)
        if d.entry == 0 and d.comment and d.magic and d.magic not in comment_by_magic and not d.comment.startswith("["):
            comment_by_magic[d.magic] = d.comment[:14]
    trades = []
    for pid, ds in byp.items():
        if pid == 0:
            continue
        ins = [x for x in ds if x.entry == 0]; outs = [x for x in ds if x.entry == 1]
        if not outs:
            continue
        o, c = (ins[0] if ins else outs[0]), outs[-1]
        net = sum(x.profit + x.commission + x.swap for x in ds)
        opened = datetime.utcfromtimestamp(o.time); closed = datetime.utcfromtimestamp(c.time)
        trades.append(dict(position=pid, magic=o.magic, bot=label_of(o.magic, comment_by_magic), side="BUY" if o.type == 0 else "SELL", volume=o.volume, entry=o.price, exit=c.price, opened=str(opened), closed=str(closed),
                           net=round(net, 2), why=(c.comment or "")[:18], today=closed >= today0, symbol=o.symbol))
    trades.sort(key=lambda x: x["closed"])
    balance_ops = [x for x in deals if x.type == 2]
    positions = [dict(ticket=p.ticket, symbol=p.symbol, side="BUY" if p.type == 0 else "SELL", volume=p.volume, entry=p.price_open, sl=p.sl, tp=p.tp, price=p.price_current, profit=round(p.profit + p.swap, 2), magic=p.magic,
                      bot=label_of(p.magic, comment_by_magic), opened=str(datetime.utcfromtimestamp(p.time)), comment=p.comment) for p in pos]
    def agg(sub):
        w = [t["net"] for t in sub if t["net"] > 0]; l = [t["net"] for t in sub if t["net"] < 0]
        return dict(trades=len(sub), won=len(w), lost=len(l), net=round(sum(t["net"] for t in sub), 2), biggest_loss=round(min(l), 2) if l else 0, profit=round(sum(w), 2), loss=round(sum(l), 2))
    bots = {}
    for t in trades:
        bots.setdefault(t["magic"], []).append(t)
    rows = []
    for magic in list(WANTED) + [m for m in bots if m not in WANTED]:
        sub = bots.get(magic, [])
        pp = [p for p in positions if p["magic"] == magic]
        label = label_of(magic, comment_by_magic)
        r = dict(magic=magic, bot=label, wanted=magic in WANTED, today=agg([t for t in sub if t["today"]]), period=agg(sub), open=len(pp), floating=round(sum(p["profit"] for p in pp), 2),
                 last=sub[-1]["closed"] if sub else None)
        if magic in WANTED:
            r.update(mode_of(label))
        rows.append(r)
    cum, curve = 0.0, []
    for t in trades:
        cum += t["net"]; curve.append([t["closed"], round(cum, 2)])
    first_bal = None
    return dict(now=str(bnow), broker_date=str(today0.date()), days=days,
                account=dict(login=ai.login, server=ai.server, mode={0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(ai.trade_mode, ai.trade_mode), currency=ai.currency, balance=ai.balance, equity=ai.equity, margin=ai.margin,
                             free=ai.margin_free, level=ai.margin_level, floating=ai.profit, leverage=ai.leverage, algo_allowed=bool(ti.trade_allowed), connected=bool(ti.connected)),
                price=dict(bid=tick.bid, ask=tick.ask) if tick else None, positions=positions, bots=rows, recent=trades[-40:][::-1], curve=curve[-400:], all_today=agg([t for t in trades if t["today"]]), all_period=agg(trades),
                balance_ops=[dict(time=str(datetime.utcfromtimestamp(x.time)), amount=x.profit, comment=x.comment) for x in balance_ops][-5:])


@router.get("/api/live")
def api_live(days: int = 14):
    if mt5 is None:
        return dict(error="MT5 is not available to the dashboard")
    try:
        return collect(max(1, min(days, 90)))
    except Exception as e:
        return dict(error=f"{type(e).__name__}: {e}")


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Gold LIVE trades</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--mut:#6a7280;--line:#e2e5ea;--ok:#127a3d;--bad:#b3261e;--warn:#9a6700;--acc:#1f5fbf}
@media(prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--ink:#e8eaed;--mut:#9aa3af;--line:#272d36;--ok:#4cc38a;--bad:#ff7b72;--warn:#e3b341;--acc:#6ea8ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}.wrap{max-width:1280px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 2px}h2{font-size:15px;margin:18px 0 6px}
.sub{color:var(--mut);font-size:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600}.ok{color:var(--ok)}.bad{color:var(--bad)}.mut{color:var(--mut)}.warn{color:var(--warn)}
.kpi{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:8px 0}@media(max-width:900px){.kpi{grid-template-columns:repeat(3,1fr)}}.kpi div{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}.kpi span{display:block;font-size:11px;color:var(--mut)}.kpi b{font-size:17px}
.chip{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:1px 9px;font-size:12px;margin:0 4px 4px 0}canvas{width:100%;height:120px;display:block}td.l{text-align:left;white-space:normal}a{color:inherit}
</style></head><body><div class=wrap>
<div style="display:flex;justify-content:space-between;flex-wrap:wrap"><div><h1>Live trades - real MT5 account</h1><div class=sub>Read-only: straight from MT5 (positions, closed deals), grouped by bot magic number. account currency, broker time. <a href="/">main dashboard</a> | <a href="/multi">21 paper bots</a></div></div><div class=sub id=upd></div></div>
<div id=acct></div><div class=kpi id=kpi></div>
<h2>Your four live bots</h2><div class=card id=wanted></div>
<h2>Open positions (all bots on the account)</h2><div class=card id=pos></div>
<h2>Cumulative closed P&amp;L, whole account (<span id=days></span> days)</h2><div class=card><canvas id=cv></canvas></div>
<h2>Closed trades (latest 40, all bots)</h2><div class=card id=recent></div>
<h2>Everything else trading on this account</h2><div class=card id=others></div>
</div><script>
const f=(x,d=2)=>x==null?'-':Number(x).toFixed(d);const sg=x=>x==null?'-':(x>0?'+':'')+Number(x).toFixed(2);const cl=x=>x>0?'ok':x<0?'bad':'mut';
function draw(pts){const cv=document.getElementById('cv'),c=cv.getContext('2d');const w=cv.width=cv.clientWidth*2,h=cv.height=cv.clientHeight*2;c.clearRect(0,0,w,h);const css=getComputedStyle(document.documentElement);
 c.strokeStyle=css.getPropertyValue('--line');c.lineWidth=2;c.beginPath();c.moveTo(0,h/2);c.lineTo(w,h/2);c.stroke();if(!pts.length){c.fillStyle=css.getPropertyValue('--mut');c.font='22px system-ui';c.fillText('no closed trades in this period',16,h/2-10);return}
 const v=[0,...pts.map(p=>p[1])];const mn=Math.min(...v),mx=Math.max(...v),r=(mx-mn)||1;c.strokeStyle=css.getPropertyValue('--acc');c.lineWidth=3;c.beginPath();v.forEach((y,i)=>{const X=i/(v.length-1||1)*(w-8)+4,Y=h-8-(y-mn)/r*(h-16);i?c.lineTo(X,Y):c.moveTo(X,Y)});c.stroke()}
async function tick(){let s;try{s=await (await fetch('/api/live')).json()}catch(e){document.getElementById('upd').textContent='dashboard not reachable';return}
 if(s.error){document.getElementById('acct').innerHTML='<span class="chip bad">'+s.error+'</span>';return}
 document.getElementById('upd').textContent='updated '+s.now+' broker | refreshes every 10 s';const a=s.account;document.getElementById('days').textContent=s.days;
 document.getElementById('acct').innerHTML=`<span class="chip ${a.mode=='REAL'?'warn':'ok'}"><b>${a.mode} account</b> ${a.login} @ ${a.server}</span><span class="chip ${a.connected?'ok':'bad'}">terminal ${a.connected?'connected':'DISCONNECTED'}</span><span class="chip ${a.algo_allowed?'ok':'warn'}">algo trading ${a.algo_allowed?'ON':'OFF'}</span>`+(s.price?`<span class=chip>XAUUSD ${f(s.price.bid)} / ${f(s.price.ask)}</span>`:'');
 document.getElementById('kpi').innerHTML=[['Balance',f(a.balance)],['Equity',f(a.equity)],['Floating P&L',sg(a.floating),cl(a.floating)],['Closed today (all)',sg(s.all_today.net)+' ('+s.all_today.trades+')',cl(s.all_today.net)],['Closed '+s.days+' d (all)',sg(s.all_period.net)+' ('+s.all_period.trades+')',cl(s.all_period.net)],['Free margin',f(a.free)]].map(x=>`<div><span>${x[0]}</span><b class="${x[2]||''}">${x[1]}</b></div>`).join('');
 let t='<table><tr><th>Bot</th><th>Mode now</th><th>Open</th><th>Floating</th><th>Today: trades</th><th>W/L</th><th>Net today</th><th>'+s.days+' d: trades</th><th>W/L</th><th>Net</th><th>Biggest loss</th><th>Last trade closed</th></tr>';
 s.bots.filter(b=>b.wanted).forEach(b=>{t+=`<tr><td><b>${b.bot}</b> <span class=mut>#${b.magic}</span></td><td class=l style="text-align:right"><span class="${b.mode.startsWith('LIVE')?'bad':b.mode.startsWith('PAPER')?'ok':'warn'}">${b.mode}</span>${b.running===true?' <span class=ok>(running)</span>':b.running===false?' <span class=bad>(not running)</span>':''}<div class=sub style="white-space:normal;max-width:260px;margin-left:auto">${b.note||''}</div></td><td>${b.open}</td><td class="${cl(b.floating)}">${b.open?sg(b.floating):'-'}</td><td>${b.today.trades}</td><td>${b.today.won}/${b.today.lost}</td><td class="${cl(b.today.net)}"><b>${sg(b.today.net)}</b></td><td>${b.period.trades}</td><td>${b.period.won}/${b.period.lost}</td><td class="${cl(b.period.net)}"><b>${sg(b.period.net)}</b></td><td class=bad>${b.period.lost?f(b.period.biggest_loss):'-'}</td><td>${b.last?b.last.slice(5,16):'no real trades yet'}</td></tr>`});
 document.getElementById('wanted').innerHTML=t+'</table><div class=sub style="margin-top:6px">Real trades appear here only when a bot actually sends orders under its magic number. Paper trades are on the main dashboard.</div>';
 let p='<table><tr><th>Bot</th><th>Ticket</th><th>Side</th><th>Lots</th><th>Entry</th><th>Price</th><th>Stop</th><th>Target</th><th>P&amp;L</th><th>Opened</th></tr>';
 p+=s.positions.map(x=>`<tr><td>${x.bot}</td><td>${x.ticket}</td><td>${x.side}</td><td>${x.volume}</td><td>${f(x.entry)}</td><td>${f(x.price)}</td><td>${x.sl?f(x.sl):'-'}</td><td>${x.tp?f(x.tp):'-'}</td><td class="${cl(x.profit)}"><b>${sg(x.profit)}</b></td><td>${x.opened.slice(5,16)}</td></tr>`).join('');
 document.getElementById('pos').innerHTML=s.positions.length?p+'</table>':'<span class=mut>no open positions</span>';draw(s.curve);
 let r='<table><tr><th>Closed</th><th>Bot</th><th>Side</th><th>Lots</th><th>Entry</th><th>Exit</th><th>Net</th><th>Why</th></tr>'+s.recent.map(x=>`<tr><td>${x.closed.slice(5,16)}</td><td>${x.bot}</td><td>${x.side}</td><td>${x.volume}</td><td>${f(x.entry)}</td><td>${f(x.exit)}</td><td class="${cl(x.net)}"><b>${sg(x.net)}</b></td><td>${x.why}</td></tr>`).join('')+'</table>';
 document.getElementById('recent').innerHTML=s.recent.length?r:'<span class=mut>no closed trades in this period</span>';
 let o='<table><tr><th>Bot / magic</th><th>Open</th><th>Floating</th><th>Today trades</th><th>Net today</th><th>'+s.days+' d trades</th><th>W/L</th><th>Net</th><th>Biggest loss</th></tr>';
 o+=s.bots.filter(b=>!b.wanted).map(b=>`<tr><td>${b.bot}</td><td>${b.open}</td><td class="${cl(b.floating)}">${b.open?sg(b.floating):'-'}</td><td>${b.today.trades}</td><td class="${cl(b.today.net)}">${sg(b.today.net)}</td><td>${b.period.trades}</td><td>${b.period.won}/${b.period.lost}</td><td class="${cl(b.period.net)}"><b>${sg(b.period.net)}</b></td><td class=bad>${b.period.lost?f(b.period.biggest_loss):'-'}</td></tr>`).join('');
 document.getElementById('others').innerHTML=o+'</table>'}
tick();setInterval(tick,10000);
</script></body></html>"""


@router.get("/live", response_class=HTMLResponse)
def live_page():
    return PAGE
