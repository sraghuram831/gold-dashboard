"""Paper-trading results of v2A / v2B / v2C since a given broker date (default Monday 2026-10-19), same columns as the backtest table.
Run:  python live_table.py [YYYY-MM-DD]"""
import csv, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SINCE = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-10-19")
BOTS = [("v2A", "gold_v2A", "GoCharting 15m"), ("v2B", "gold_v2B", "MT5 ticks"), ("v2C", "gold_v2C", "GoCharting 5m")]
now_broker = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None)) + pd.Timedelta(hours=3)
days = (now_broker - SINCE).total_seconds() / 86400
rows, extra, daily, bytype = [], [], [], []
for bid, folder, src in BOTS:
    p = ROOT / folder / "gold_2b_trades.csv"
    d = pd.read_csv(p) if p.exists() else pd.DataFrame()
    if len(d):
        d["closed"] = pd.to_datetime(d["closed"]); d["opened"] = pd.to_datetime(d["opened"]); d = d[d.closed >= SINCE].sort_values("closed").reset_index(drop=True)
    if not len(d):
        rows.append(f"| v3_v2 | {bid} ({src}) | 0 | 0 | - | 0 | 0 | 0 | - | - | 0 | 0 | - |"); continue
    w, l = d[d.pnl_usc > 0], d[d.pnl_usc < 0]
    eq = d.pnl_usc.cumsum(); dd = (eq.cummax().clip(lower=0) - eq).max()
    pf = f"{w.pnl_usc.sum() / -l.pnl_usc.sum():.2f}" if len(l) else "n/a"
    rows.append(f"| v3_v2 | {bid} ({src}) | {len(d)} ({len(d) / days:.1f}) | {len(w)} | {100 * len(w) / len(d):.1f} | {w.pnl_usc.sum():,.0f} | {len(l)} | {l.pnl_usc.sum():,.0f} | "
                f"{(l.pnl_usc.mean() if len(l) else 0):.1f} | {d.pnl_usc.min() if len(l) else 0:.0f} | {d.pnl_usc.sum():+,.1f} | {dd:.1f} | {pf} |")
    for r in d.itertuples():
        pass
    g = d.groupby(d.closed.dt.strftime("%a %m-%d")).pnl_usc.agg(["count", lambda s: int((s > 0).sum()), lambda s: int((s < 0).sum()), "sum"])
    g.columns = ["trades", "won", "lost", "net"]; g.insert(0, "bot", bid); daily.append(g.reset_index().rename(columns={"closed": "day"}))
    t = d.groupby(["pattern", "session"]).pnl_usc.agg(["count", lambda s: int((s < 0).sum()), "sum"]); t.columns = ["trades", "lost", "net"]; t.insert(0, "bot", bid); bytype.append(t.reset_index())
    ls = l.groupby("reason").pnl_usc.agg(["count", "sum"]); extra.append((bid, ls, l))
print(f"Paper trading since {SINCE:%Y-%m-%d} 00:00 broker time until {now_broker:%Y-%m-%d %H:%M} broker ({days:.2f} days), 0.01 lot, USC\n")
print("| Strategy | Bot (absorption) | Trades (per day) | Won | Win % | Profit | Lost | Total loss | Avg loss | Biggest loss | Net | Max DD | PF |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
print("\n".join(rows))
print("\nLOSING TRADES")
for bid, ls, l in extra:
    print(f"\n{bid}:")
    for r in l.itertuples():
        print(f"  {r.opened:%a %m-%d %H:%M} -> {r.closed:%H:%M} {r.side} {r.pattern} ({r.session}, {r.mode}) entry {r.entry} exit {r.exit} pnl {r.pnl_usc:+.2f} [{r.reason}]")
print("\nPER DAY"); print(pd.concat(daily).to_string(index=False) if daily else "-")
print("\nBY ENTRY TYPE / SESSION"); print(pd.concat(bytype).to_string(index=False) if bytype else "-")
