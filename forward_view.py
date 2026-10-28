"""/forward page of the Gold dashboard: FORWARD TEST of the 31 ported bots, version 1 (regular) vs version 2 (with PH15 bridge absorption gate). PAPER ONLY, READ-ONLY.
Data: bots_v1_v2\\forward\\state.json (written by runner.py).   Included by server.py with:  from forward_view import router; app.include_router(router)"""
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

STATE = Path(r"C:\Users\Administrator\Documents\bot\Sandy_bot\bots_v1_v2\forward\state.json")
router = APIRouter()


@router.get("/api/forward")
def api_forward():
    try:
        s = json.loads(STATE.read_text(encoding="utf-8"))
        s["age_s"] = int((datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(s["updated"])).total_seconds())
        return JSONResponse(s)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]})


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Forward test: version 1 vs version 2</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--mut:#6a7280;--line:#e2e5ea;--ok:#127a3d;--bad:#b3261e;--warn:#9a6700;--acc:#1f5fbf;--band:#eef1f5;--v1:#1f5fbf;--v2:#b4540a}
@media(prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--ink:#e8eaed;--mut:#9aa3af;--line:#272d36;--ok:#4cc38a;--bad:#ff7b72;--warn:#e3b341;--acc:#6ea8ff;--band:#1e242c;--v1:#6ea8ff;--v2:#f0883e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}.wrap{max-width:1500px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:15px;margin:0 0 6px}.sub{color:var(--mut);font-size:12.5px}a{color:var(--acc)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin:12px 0}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow-x:auto}
.k{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}.big{font-size:18px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{padding:4px 7px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600}
thead tr.g th{text-align:center;border-bottom:2px solid var(--line);color:var(--ink)}th.v1,td.v1b{border-left:2px solid var(--v1)}th.v2,td.v2b{border-left:2px solid var(--v2)}
tr.gh td{background:var(--band);text-align:left;white-space:normal;padding:7px}tr.row{cursor:pointer}tr.row:hover td{background:var(--band)}tr.det td{background:var(--bg);white-space:normal;text-align:left;padding:8px 12px}
.pos{color:var(--ok)}.neg{color:var(--bad)}.mut{color:var(--mut)}.chip{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:0 8px;font-size:11.5px}.open{border-color:var(--warn);color:var(--warn);font-weight:600}
.bad{color:var(--bad)}.ok{color:var(--ok)}.warn{color:var(--warn)}.banner{padding:8px 12px;border-radius:8px;margin:10px 0;background:var(--band);border-left:3px solid var(--warn);font-size:13px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:900px){.two{grid-template-columns:1fr}}
</style></head><body><div class=wrap>
<div style="display:flex;justify-content:space-between;flex-wrap:wrap;align-items:baseline"><div><h1>Forward test: version 1 (regular) vs version 2 (with bridge absorption)</h1>
<div class=sub>PAPER ONLY: no orders are sent. Prices come live from your MT5 cent symbol XAUUSDcent; absorption comes from the PH15 bridge. Version 2 takes a trade only when the bridge shows same-direction absorption on one of the last 3 completed 15m bars. Click a row for open position and recent trades. <a href="/">Main dashboard</a> · <a href="/multi">Multi-runner</a></div></div><div class=sub id=upd></div></div>
<div id=banner></div><div class=cards id=cards></div>
<div class=card style="padding:0"><table><thead><tr class=g><th></th><th colspan=7 class=v1>Version 1 (regular)</th><th colspan=7 class=v2>Version 2 (bridge absorption)</th><th></th></tr>
<tr><th>Bot</th><th class=v1>Status</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win%</th><th>Net</th><th>Today</th><th class=v2>Status</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win%</th><th>Net</th><th>Today</th><th>Skipped by gate</th></tr></thead><tbody id=tb></tbody></table></div>
<div class=card style="margin-top:12px"><h2>Not in the forward test (9 bots)</h2><div class=sub>B01_EMA9_VWAP_StopTarget and B02_EMA9_VWAP_CrossExit (need a 3-minute chart). 01_conf1m_bot and 09_mixed_bot (need 1-minute history). The five bitcoin bots 03, 04, 05, 07, 08 (the bridge has no bitcoin order flow). The two Timiline and Gold multi-runner groups are on the <a href="/">main page</a>.</div></div>
</div><script>
const f=(x,d=1)=>x==null?'-':Number(x).toFixed(d),sg=x=>x==null?'-':(x>0?'+':'')+Number(x).toLocaleString(undefined,{maximumFractionDigits:1}),cl=x=>x>0?'pos':x<0?'neg':'';
const open_=new Set();
function st(v){const o=v.open;return o?`<span class="chip open">${o.side} ${f(o.floating,0)}</span>`:'<span class=mut>flat</span>'}
function cells(v,cls){return `<td class="${cls}">${st(v)}</td><td>${v.trades}</td><td>${v.wins}</td><td>${v.losses}</td><td>${v.win_pct==null?'-':v.win_pct+'%'}</td><td class="${cl(v.net)}"><b>${sg(v.net)}</b></td><td class="${cl(v.today)}">${sg(v.today)}</td>`}
function detail(v,name){let h=`<b>${name}</b> `;if(v.open){const o=v.open;h+=`<span class="chip open">OPEN ${o.side}</span> since ${o.time.slice(5,16)} UTC, entry ${f(o.entry,2)}, stop ${f(o.sl,2)}, target ${f(o.tp,2)}, floating ${sg(o.floating)}<br>`}else h+='<span class=mut>no open position</span><br>';
 h+=v.recent.length?'<table><tr><th>Entry (UTC)</th><th>Side</th><th>P&amp;L</th><th>Exit</th></tr>'+v.recent.map(r=>`<tr><td>${r.time.slice(5,16)}</td><td>${r.side}</td><td class="${cl(r.pnl)}">${sg(r.pnl)}</td><td>${r.why||''}</td></tr>`).join('')+'</table>':'<span class=mut>no closed trades yet</span>';
 h+=`<div class=sub>Win amount ${sg(v.gross_win)} · loss amount ${sg(v.gross_loss)} · max drawdown ${f(v.max_dd,0)}</div>`;return h}
async function tick(){let s;try{s=await (await fetch('/api/forward')).json()}catch(e){document.getElementById('upd').textContent='dashboard not reachable';return}
 if(s.error){document.getElementById('banner').innerHTML=`<div class=banner>Runner has not written state yet: ${s.error}</div>`;return}
 document.getElementById('upd').textContent='runner heartbeat '+s.updated+' UTC ('+s.age_s+' s ago)';
 let b='';if(s.age_s>300)b+=`<div class="banner bad">The forward-test runner has not updated for ${Math.round(s.age_s/60)} min: it may have stopped.</div>`;
 if(s.market_closed)b+='<div class=banner>Market closed (weekend / daily break): no new bars, the bots wait. Trades will appear after the market reopens (Sunday 22:00 UTC).</div>';
 if(!s.flags.ok)b+=`<div class="banner bad">Bridge flags unavailable (${s.flags.error||'?'}). Version 2 uses the last flags it had.</div>`;
 const errs=Object.keys(s.errors||{});if(errs.length)b+=`<div class="banner bad">${errs.length} bot(s) failed in the last cycle: ${errs.slice(0,3).join(', ')}</div>`;
 document.getElementById('banner').innerHTML=b;
 let openN=0,t1=0,t2=0,skip=0;s.bots.forEach(x=>{if(x.v1.open)openN++;if(x.v2.open)openN++;t1+=x.v1.trades;t2+=x.v2.trades;skip+=x.v2_skipped});
 const age=s.price.age_min;
 document.getElementById('cards').innerHTML=
  `<div class=card><div class=k>XAUUSDcent (MT5)</div><div class=big>${f(s.price.close,2)}</div><div class=sub>last 5m bar ${s.price.bar.slice(5,16)} UTC (${age<90?age+' min ago':Math.round(age/60)+' h ago'})</div></div>`+
  `<div class=card><div class=k>Bridge absorption feed</div><div class="big ${s.flags.ok?'ok':'bad'}">${s.flags.ok?'connected':'DOWN'}</div><div class=sub>last 15m bar ${s.flags.last_bar?s.flags.last_bar.slice(5,16):'-'} UTC · ${s.flags.bars} bars</div></div>`+
  `<div class=card><div class=k>Forward test started</div><div class=big>${s.start.slice(0,16)}</div><div class=sub>UTC · cycle ${s.cycle_s}s · ${s.bots.length} bots x 2 versions</div></div>`+
  `<div class=card><div class=k>Open paper positions</div><div class=big>${openN}</div><div class=sub>version 1 and version 2 together</div></div>`+
  `<div class=card><div class=k>Closed trades</div><div class=big><span style="color:var(--v1)">${t1}</span> v1 · <span style="color:var(--v2)">${t2}</span> v2</div><div class=sub>${skip} v1 trades skipped by the gate</div></div>`;
 let h='',last=null,gs={};s.bots.forEach(x=>{const g=gs[x.group]=gs[x.group]||{a:0,b:0,u:x.unit};g.a+=x.v1.net;g.b+=x.v2.net});
 s.bots.forEach(x=>{if(x.group!==last){const g=gs[x.group];h+=`<tr class=gh><td colspan=16><b>${x.group}</b> <span class=mut>(${g.u})</span> &nbsp; group net: v1 <b class="${cl(g.a)}">${sg(g.a)}</b> · v2 <b class="${cl(g.b)}">${sg(g.b)}</b></td></tr>`;last=x.group}
  h+=`<tr class=row data-id="${x.id}"><td><b>${x.id}</b></td>${cells(x.v1,'v1b')}${cells(x.v2,'v2b')}<td>${x.v2_skipped}</td></tr>`;
  if(open_.has(x.id))h+=`<tr class=det><td colspan=16><div class=two><div>${detail(x.v1,'Version 1')}</div><div>${detail(x.v2,'Version 2')}</div></div></td></tr>`});
 document.getElementById('tb').innerHTML=h;
 document.querySelectorAll('tr.row').forEach(r=>r.onclick=()=>{const id=r.dataset.id;open_.has(id)?open_.delete(id):open_.add(id);tick()})}
tick();setInterval(tick,5000);
</script></body></html>"""


@router.get("/forward", response_class=HTMLResponse)
def forward_page():
    return PAGE
