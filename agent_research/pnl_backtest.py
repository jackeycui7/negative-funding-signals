"""Money, not depth: run the portfolio engine with the borrow list restricted to each method's weekly 40-coin list.

Engine: engine/port.py + engine/sim2.py (needs cache2.npz, meta2.csv, spread_all.csv in engine/): settled-rate entry < -0.10%/8h, VIP3 taker fees, k_imp=4, OI cap 10%, S=10M,
per-coin cap = S/40 (equal, public). Two rule sets: 'improved' (exit_confirm=3, basis<=-0.6%, pov 0.10) and 'default' (mkp defaults).
List decided at day d 00:00 UTC (agent/eval lists) -> coins usable for NEW entries/adds from d+3 until the next list takes over
(holdout: weekly, [d+3, d+10); dev: every 2 weeks, [d+3, d+17)). Open positions are never forced out (slightly optimistic for lists).
Scenarios: all coins always (Leslie's assumption) / agent final / chronic rule / 7d-mean rank / oracle (hindsight).
  python3 pnl_backtest.py   -> runs/pnl_equal_caps.csv
"""
import json, sys, numpy as np, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'engine'))
from port import Port
AG = Path(__file__).resolve().parent; sys.path.insert(0, str(AG))
from eval import DEV, HOLD, lists_for
S = 1e7
RULES = {"improved": dict(exit_confirm=3, basis_thr=-0.006, pov=0.10, k_imp=4.0, oi_frac=0.10, fee_s=0.0006, fee_f=0.00032),
         "default": dict(k_imp=4.0, oi_frac=0.10, fee_s=0.0006, fee_f=0.00032)}
p = Port(); d = p.d; a = d.a; T, N = a["sv"].shape; fut = d.meta.fut.to_numpy(); ix = {f: i for i, f in enumerate(fut)}
a["oi"] = pd.DataFrame(a["oi"]).ffill().to_numpy()
caps = np.full(N, S / 40)                                   # equal cap per coin (public; no private inventory)
T0 = pd.Timestamp("2025-04-01")
rows = []
for setname, dates, step in (("holdout", HOLD, 7), ("dev", DEV, 14)):
    masks = {k: np.zeros((T, N), np.uint8) for k in ("agent", "chronic_rule", "m7_rank", "oracle")}
    for dt in dates:
        log = json.loads((AG / "runs" / "final" / f"{dt}.json").read_text()); _, L = lists_for(dt, log["picks"])
        h0 = 24 * ((pd.Timestamp(dt) - T0).days + 3); h1 = min(h0 + 24 * step, T)
        for k in masks:
            for s in L[k][:40]:
                if s in ix: masks[k][h0:h1, ix[s]] = 1
    w0 = str((pd.Timestamp(dates[0]) + pd.Timedelta(days=3)).date()); w1 = str((pd.Timestamp(dates[-1]) + pd.Timedelta(days=3 + step)).date())
    for rn, R in RULES.items():
        res = {"all_coins": p.run(w0, w1, S, caps, **R)}
        for k, m in masks.items(): res[k] = p.run(w0, w1, S, caps, ok=m, **R)
        base = res["all_coins"]["net"]
        for k, r in res.items():
            rows.append(dict(set=setname, window=f"{w0}..{w1}", rules=rn, scenario=k, ann_pct=round(r["ann"], 1), net_wan=round(r["net"] / 1e4, 1),
                             funding_wan=round(r["fund"] / 1e4, 1), fees_wan=round(r["fees"] / 1e4, 1), episodes=r["eps"], vs_all_coins=round(r["net"] / base * 100, 1)))
            print(rows[-1], flush=True)
R = pd.DataFrame(rows); R.to_csv(AG / "runs" / "pnl_equal_caps.csv", index=False); print(R.to_markdown(index=False))
