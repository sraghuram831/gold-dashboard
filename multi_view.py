"""/multi page of the Gold dashboard: the 21 paper bots (7 strategies x 3 absorption sources) run by gold_v2_multi/multi_runner.py.  READ-ONLY.
Included by server.py with:  from multi_view import router; app.include_router(router)"""
import csv, json, time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parent.parent / "gold_v2_multi"
STRATS = ["b1_v2", "b2_v2", "v3_v2", "v3 safe", "v3c", "v4 balanced", "v4 calm"]
SRC = [("A", "v2A (GoCharting 15m)"), ("B", "v2B (MT5 ticks)"), ("C", "v2C (GoCharting 5m)")]
router = APIRouter()


def jget(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def cell(src, name, bid, ask):
    iid = f"{src}_{name.replace(' ', '_')}"
    d = ROOT / "instances" / iid
    rows = []
    p = d / "gold_2b_trades.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    r["pnl_usc"] = float(r["pnl_usc"]); rows.append(r)
                except Exception:
                    pass
    pnls = [r["pnl_usc"] for r in rows]
    won = [x for x in pnls if x > 0]; lost = [x for x in pnls if x < 0]
    cum = peak = dd = 0.0
    for x in pnls:
        cum += x; peak = max(peak, cum); dd = max(dd, peak - cum)
    pos = jget(d / "gold_2b_state.json")
    floating = None
    if pos and bid is not None:
        floating = round(pos["side"] * ((bid if pos["side"] > 0 else ask) - pos["entry"]), 2)
    g = jget(d / "gold_2b_guard.json", {})
    log = []
    try:
        log = [l for l in (d / "gold_2b_log.txt").read_text(encoding="utf-8", errors="replace").splitlines() if any(k in l for k in ("PAPER", "CLOSED", "KILL", "NO NEW TRADE"))][-4:]
    except Exception:
        pass
    return dict(id=iid, trades=len(rows), won=len(won), lost=len(lost), profit=round(sum(won), 2), loss=round(sum(lost), 2), net=round(cum, 2), max_dd=round(dd, 2), biggest_loss=round(min(pnls), 2) if lost else 0,
                avg_loss=round(sum(lost) / len(lost), 2) if lost else 0, pf=round(sum(won) / -sum(lost), 2) if lost else None, position=pos, floating=floating, halted=bool(g.get("halted")),
                recent=[dict(closed=r["closed"], side=r["side"], pattern=r["pattern"], pnl=r["pnl_usc"], reason=r["reason"]) for r in rows[-3:]][::-1], log=log)


@router.get("/api/multi")
def api_multi():
    st = jget(ROOT / "multi_status.json", {}) or {}
    upd = None
    try:
        upd = (datetime.utcnow() - datetime.strptime(st["updated"], "%Y-%m-%d %H:%M:%S")).total_seconds()
    except Exception:
        pass
    bid, ask = st.get("bid"), st.get("ask")
    grid = {name: {src: cell(src, name, bid, ask) for src, _ in SRC} for name in STRATS}
    return dict(now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), runner=dict(started=st.get("started"), updated=st.get("updated"), age_s=upd, alive=upd is not None and upd < 60, last_candle=st.get("last_candle"),
                feeds=st.get("feeds"), open_positions=st.get("open_positions"), bid=bid, ask=ask), strats=STRATS, sources=SRC, grid=grid)


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Gold 21 bots (paper)</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--mut:#6a7280;--line:#e2e5ea;--ok:#127a3d;--bad:#b3261e;--warn:#9a6700}
@media(prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--ink:#e8eaed;--mut:#9aa3af;--line:#272d36;--ok:#4cc38a;--bad:#ff7b72;--warn:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}.wrap{max-width:1250px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 2px}h2{font-size:15px;margin:16px 0 6px}
.sub{color:var(--mut);font-size:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600}.ok{color:var(--ok)}.bad{color:var(--bad)}.mut{color:var(--mut)}.warn{color:var(--warn)}
td.c{text-align:left;white-space:normal;min-width:190px}.chip{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:1px 9px;font-size:12px;margin:0 4px 4px 0}a{color:inherit}
</style></head><body><div class=wrap>
<div style="display:flex;justify-content:space-between;flex-wrap:wrap"><div><h1>21 paper bots: 7 strategies x 3 absorption sources</h1><div class=sub>One runner process (gold_v2_multi). Paper only, USD at 0.01 lot ($1 move = $1). Counts closed trades since the runner started. <a href="/">main dashboard</a></div></div><div class=sub id=upd></div></div>
<div id=runner style="margin-top:8px"></div>
<h2>Trades, wins and losses (net USC)</h2><div class=card id=short></div>
<h2>Full table</h2><div class=card id=full></div>
<h2>Recent activity</h2><div class=card id=recent></div>
</div><script>
const f=(x,d=2)=>x==null?'-':Number(x).toFixed(d);const sg=x=>x==null?'-':(x>0?'+':'')+Number(x).toFixed(1);const cl=x=>x>0?'ok':x<0?'bad':'mut';
async function tick(){let s;try{s=await (await fetch('/api/multi')).json()}catch(e){document.getElementById('upd').textContent='not reachable';return}
 document.getElementById('upd').textContent='updated '+s.now+' UTC';const r=s.runner;
 let h=`<span class="chip ${r.alive?'ok':'bad'}">runner ${r.alive?'running':'NOT running'}</span><span class=chip>started ${r.started||'-'} UTC</span><span class=chip>last 5m candle ${r.last_candle||'-'} broker</span><span class=chip>open positions ${r.open_positions??'-'}</span>`;
 if(r.feeds)for(const k in r.feeds){const x=r.feeds[k];h+=`<span class="chip ${k=='B'?'':(x.connected?'ok':'bad')}">feed ${k}: ${k=='B'?'ticks':(x.connected?'connected':'down')}, ${x.windows} windows</span>`}
 document.getElementById('runner').innerHTML=h;
 let t='<table><tr><th>Strategy</th>'+s.sources.map(x=>`<th>${x[1]}</th>`).join('')+'</tr>';
 s.strats.forEach(n=>{t+=`<tr><td><b>${n}</b></td>`+s.sources.map(([k])=>{const c=s.grid[n][k];const op=c.position?` <span class=warn>(open ${sg(c.floating)})</span>`:'';
  return `<td>${c.trades} trade${c.trades==1?'':'s'}: ${c.won} won, ${c.lost} lost (<b class="${cl(c.net)}">${sg(c.net)}</b>)${op}${c.halted?' <span class=bad>KILL SWITCH</span>':''}</td>`}).join('')+'</tr>'});
 document.getElementById('short').innerHTML=t+'</table>';
 let u='<table><tr><th>Strategy</th><th>Bot</th><th>Trades</th><th>Won</th><th>Win %</th><th>Profit</th><th>Lost</th><th>Total loss</th><th>Avg loss</th><th>Biggest loss</th><th>Net</th><th>Open</th><th>Max DD</th><th>PF</th></tr>';
 s.strats.forEach(n=>s.sources.forEach(([k,lab])=>{const c=s.grid[n][k];u+=`<tr><td>${n}</td><td>${lab}</td><td>${c.trades}</td><td>${c.won}</td><td>${c.trades?f(100*c.won/c.trades,1):'-'}</td><td>${f(c.profit)}</td><td>${c.lost}</td><td>${f(c.loss)}</td><td>${f(c.avg_loss)}</td><td>${f(c.biggest_loss)}</td><td class="${cl(c.net)}"><b>${sg(c.net)}</b></td><td class="${cl(c.floating)}">${c.position?sg(c.floating):'-'}</td><td>${f(c.max_dd)}</td><td>${c.pf==null?'-':c.pf}</td></tr>`}));
 document.getElementById('full').innerHTML=u+'</table>';
 let v='<table><tr><th>Bot</th><th>Last trades / events</th></tr>';let any=false;
 s.strats.forEach(n=>s.sources.forEach(([k,lab])=>{const c=s.grid[n][k];const lines=(c.recent.map(x=>`${String(x.closed).slice(5,16)} ${x.side} ${x.pattern||''} <b class="${cl(x.pnl)}">${sg(x.pnl)}</b> ${x.reason}`)).join(' &nbsp;|&nbsp; ');if(lines||c.position){any=true;v+=`<tr><td>${n} / ${lab}</td><td class=c style="text-align:left">${c.position?'<span class=warn>OPEN '+(c.position.side>0?'BUY':'SELL')+' '+(c.position.pattern||'')+' @ '+f(c.position.entry)+'</span> &nbsp; ':''}${lines}</td></tr>`}}));
 document.getElementById('recent').innerHTML=any?v+'</table>':'<span class=mut>no trades yet</span>'}
tick();setInterval(tick,10000);
</script></body></html>"""


@router.get("/multi", response_class=HTMLResponse)
def page():
    return PAGE
