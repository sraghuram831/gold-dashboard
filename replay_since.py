"""Replay of EVERY strategy for each bot on the market data since a broker date (default Monday 2026-10-19), 5,000 USC, 0.01 lot.
   v2B flags: MT5 tick footprint, rebuilt from MT5 ticks up to now.   v2A flags: the bridge's recorded 15m absorption flags.   v2C flags: the bridge's recorded 5m flags, any of the three per quarter hour.
   v2A / v2C entries are blocked while the bridge feed is stale (newest bar older than 25 min), as the live bots do.
Run:  python replay_since.py [YYYY-MM-DD]       (needs MT5 open and the bridge up; read-only)"""
import contextlib, http.client, io, json, os, sys
from datetime import datetime, timedelta
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2B = os.path.join(ROOT, "gold_v2B")
sys.path.insert(0, V2B)
with contextlib.redirect_stdout(io.StringIO()):
    import backtest_v2 as V
B, S = V.B, V.S
START = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-10-19")
OUT = os.path.join(ROOT, "dashboard", "since_monday"); os.makedirs(OUT, exist_ok=True)

# ---- v2B: footprint from MT5 ticks, extended from the cache to now
fp_old = B.fp
day = (fp_old.index.max() - pd.Timedelta(days=1)).normalize()
parts = []
while day <= pd.Timestamp(datetime.utcnow() + timedelta(hours=3)):
    tk = B.mt5.copy_ticks_range(B.SYM, day.to_pydatetime(), (day + pd.Timedelta(days=1)).to_pydatetime(), B.mt5.COPY_TICKS_ALL)
    if tk is not None and len(tk):
        parts.append(S.build_footprint(pd.DataFrame(tk)))
    day += pd.Timedelta(days=1)
fp_new = pd.concat(parts) if parts else fp_old.iloc[0:0]
fp = pd.concat([fp_old[fp_old.index < fp_new.index.min()], fp_new]).sort_index()
FL_B = {t: (bool(r.buy), bool(r.sell)) for t, r in S.absorption_flags(B.m15, fp).iterrows()}
print(f"footprint rebuilt to {fp.index.max()} ({len(fp_new)} new 15m candles from MT5 ticks)")

# ---- v2A / v2C: the bridge's recorded bars and flags
conn = http.client.HTTPConnection("127.0.0.1:8015", timeout=30)
def api(path):
    conn.request("GET", path); r = conn.getresponse(); return json.loads(r.read().decode("utf-8"))
b15 = api("/api/bars?symbol=XAUUSD&tf=15&limit=1500"); b5 = api("/api/bars?symbol=XAUUSD&tf=5&limit=4000")
def flag(e):
    ab = ((e.get("features") or {}).get("absorption")) or {}
    return (bool(ab.get("buy")), bool(ab.get("sell")))
FL_A = {pd.Timestamp(e["broker_time"]): flag(e) for e in b15}
F5 = {pd.Timestamp(e["broker_time"]): flag(e) for e in b5}
FL_C = {}
for t, (b, s) in F5.items():
    w = t.floor("15min"); ob, os_ = FL_C.get(w, (False, False)); FL_C[w] = (ob or b, os_ or s)
close_a = np.array(sorted(t + pd.Timedelta(minutes=15) for t in FL_A), dtype="datetime64[ns]")
close_c = np.array(sorted(t + pd.Timedelta(minutes=5) for t in F5), dtype="datetime64[ns]")
def gate_for(closes):
    def gate(t):
        i = np.searchsorted(closes, np.datetime64(t), side="right") - 1
        return i < 0 or (t - pd.Timestamp(closes[i])) > pd.Timedelta(minutes=25)
    return gate
print(f"bridge bars loaded: {len(b15)} x 15m ({min(FL_A)} .. {max(FL_A)}), {len(b5)} x 5m ({min(F5)} .. {max(F5)})")

SOURCES = [("v2A", "GoCharting 15m", FL_A, gate_for(close_a)), ("v2B", "MT5 ticks", FL_B, None), ("v2C", "GoCharting 5m", FL_C, gate_for(close_c))]
STRATS = ["b1_v2", "b2_v2", "v3_v2", "v3 safe / v4 classic", "v3c", "v4 balanced", "v4 calm"]
W = B.window(START)
now_b = pd.Timestamp(datetime.utcnow() + timedelta(hours=3))
days = (now_b - START).total_seconds() / 86400
rows, losers, detail = [], [], {}
for strat in STRATS:
    var, tp, stop, be, nd = V.BOTS[strat]
    for bid, src, FL, gate in SOURCES:
        d = V.sim(W, var, tp, stop, be, nd, FL, gate)
        d = d[d.close >= START] if len(d) else d
        name = strat.replace(" / v4 classic", "")
        detail[(name, bid)] = d
        if not len(d):
            rows.append(f"| {name} | {bid} ({src}) | 0 | 0 | - | 0 | 0 | 0 | - | - | 0 | 0 | - | 0 | 0 |"); continue
        d.to_csv(os.path.join(OUT, f"{bid}__{name.replace(' ', '_')}.csv"), index=False)
        w, l = d[d.pnl > 0], d[d.pnl < 0]
        eq = d.pnl.cumsum(); dd = (eq.cummax().clip(lower=0) - eq).max()
        day_net = d.groupby(d.close.dt.day).pnl.sum()
        mon, tue = day_net.get(19, 0.0), day_net.get(20, 0.0)
        pf = f"{w.pnl.sum() / -l.pnl.sum():.2f}" if len(l) else "n/a"
        rows.append(f"| {name} | {bid} ({src}) | {len(d)} ({len(d) / days:.1f}) | {len(w)} | {100 * len(w) / len(d):.1f} | {w.pnl.sum():,.0f} | {len(l)} | {l.pnl.sum():,.0f} | {(l.pnl.mean() if len(l) else 0):.1f} | "
                    f"{d.pnl.min() if len(l) else 0:.0f} | {d.pnl.sum():+,.1f} | {dd:.1f} | {pf} | {mon:+.1f} | {tue:+.1f} |")
        for r in l.itertuples():
            losers.append(f"{name} / {bid}: {r.open:%a %m-%d %H:%M} -> {r.close:%H:%M} {'BUY' if r.side > 0 else 'SELL'} {r.source} ({r.session}, {r.mode}) pnl {r.pnl:+.2f} [{r.result}]")
print(f"\nREPLAY since {START:%Y-%m-%d} 00:00 broker until {now_b:%Y-%m-%d %H:%M} ({days:.2f} days), 5,000 USC, 0.01 lot, USC\n")
print("| Strategy | Bot (absorption) | Trades (per day) | Won | Win % | Profit | Lost | Total loss | Avg loss | Biggest loss | Net | Max DD | PF | Mon net | Tue net |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
print("\n".join(rows))
print("\nLOSING TRADES"); print("\n".join(losers) if losers else "none")

# ---- check against the live paper trades of v3_v2
print("\nCHECK vs LIVE paper trades (v3_v2):")
for bid, folder in (("v2A", "gold_v2A"), ("v2B", "gold_v2B"), ("v2C", "gold_v2C")):
    p = os.path.join(ROOT, folder, "gold_2b_trades.csv")
    if os.path.exists(p):
        lv = pd.read_csv(p); lv["opened"] = pd.to_datetime(lv["opened"]); lv = lv[lv.opened >= START]
        rp = detail[("v3_v2", bid)]
        rp_open = set(rp.open.dt.strftime("%m-%d %H:%M")); lv_open = set(lv.opened.dt.strftime("%m-%d %H:%M"))
        print(f"{bid}: live {len(lv)} trades net {lv.pnl_usc.sum():+.1f} | replay {len(rp)} trades net {rp.pnl.sum():+.1f} | same entry minute in both: {len(rp_open & lv_open)} | only live: {sorted(lv_open - rp_open)[:6]} | only replay: {sorted(rp_open - lv_open)[:6]}")
B.mt5.shutdown()
