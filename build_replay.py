"""Builds replay_data.json for the dashboard's "Replay / backtest" section (simulated trades, never mixed with live paper trades).
Sources: gold_v2A/results/*_summary.csv + top profile trade files (backtest_v2.py both), bots8/data/replay_{QE,PH,RBVE}.txt (replay.py output).
Run:  python build_replay.py"""
import csv, json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RES = ROOT / "Gold_basket_bot" / "gold_v2A" / "results"
REP = ROOT / "Test_bots_V1" / "bots8" / "data"
TOP = ["v3_v2_plus_Monday_block", "b2_v2_plus_Monday_block", "v3_safe_-_v4_classic"]


def summary(path):
    return [dict(r) for r in csv.DictReader(open(path, encoding="utf-8"))]


def curve_and_recent(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    cum, daily = 0.0, {}
    for r in rows:
        cum += float(r["pnl"])
        daily[r["close"][:10]] = round(cum, 2)
    recent = [dict(closed=r["close"], side="BUY" if r["side"] == "1" else "SELL", mode=r["mode"], entry=round(float(r["entry"]), 2), pnl=round(float(r["pnl"]), 2), result=r["result"]) for r in rows[-12:]][::-1]
    return [[k, v] for k, v in daily.items()], recent


gold = {"summary": {}, "top": []}
for src in ("V2B_ticks", "V2A_gocharting"):
    gold["summary"][src] = summary(RES / f"{src}_summary.csv")
for src in ("V2B_ticks", "V2A_gocharting"):
    for t in TOP:
        f = RES / f"{src}__{t}_trades.csv"
        if f.exists():
            c, rec = curve_and_recent(f)
            gold["top"].append(dict(source=src, profile=t.replace("_plus_", " + ").replace("_", " "), curve=c, recent=rec))

LINE = re.compile(r"^(\d\d-\d\d \d\d:\d\d) (BUY |SELL) (.+?)\s+entry ([\d.]+) sl ([\d.]+) tp ([\d.]+) -> (\w+)")
replay = {}
for w in ("QE", "PH", "RBVE"):
    f = REP / f"replay_{w}.txt"
    trades, cum, curve = [], 0.0, []
    for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = LINE.match(ln)
        if not m:
            continue
        t, side, pat, e, sl, tp, res = m.groups()
        e, sl, tp = float(e), float(sl), float(tp)
        pnl = None
        if res in ("TP", "SL"):
            pnl = round(((tp if res == "TP" else sl) - e) * (1 if side.strip() == "BUY" else -1), 2)
            cum += pnl
            curve.append([t, round(cum, 2)])
        trades.append(dict(time="2026-" + t, side=side.strip(), pattern=pat.strip(), entry=e, sl=sl, tp=tp, result=res, pnl=pnl))
    done = [x for x in trades if x["pnl"] is not None]
    replay[w] = dict(signals=len(trades), resolved=len(done), tp=sum(1 for x in done if x["result"] == "TP"), sl=sum(1 for x in done if x["result"] == "SL"),
                     net=round(sum(x["pnl"] for x in done), 1), curve=curve, trades=trades[::-1])
out = dict(built=__import__("datetime").datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), gold=gold, replay=replay,
           note="SIMULATED. Gold: backtest_v2.py 12 Feb-15 Oct 2026, 5,000 USC, 0.01 lot. Replay: bots8 replay.py on the last ~2,500 M15 bars, USD points per 1 unit, no trade management.")
(HERE / "replay_data.json").write_text(json.dumps(out), encoding="utf-8")
print("wrote replay_data.json", {k: (v["signals"], v["net"]) for k, v in replay.items()}, len(gold["top"]), "top curves")
