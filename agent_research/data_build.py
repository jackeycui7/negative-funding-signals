"""Build the agent's point-in-time data store from the research caches.  python3 data_build.py
Outputs (agent/data/):
  features.parquet  one row per (day d, coin): everything known at 00:00 UTC of day d (the market_screen table)
  daily.parquet     one row per (day, coin): that day's own values (for coin_detail); a row for day k is only shown when k < as_of day
  outcomes.parquet  (d, sym, hit, mag) over [d+3, d+10): NEVER shown to the agent; used by eval and by base_rates (matured rows only)
  episodes.csv, announcements.csv  copies with parsed timestamps
Day index d = days since 2025-04-01 (UTC)."""
import os, numpy as np, pandas as pd
from pathlib import Path
A = Path(__file__).resolve().parent; B = Path(os.environ.get("NF_RESEARCH_DIR", A.parent)); E = B / "data_events"; O = A / "data"; O.mkdir(exist_ok=True)
T0 = pd.Timestamp("2025-04-01", tz="UTC")
z = np.load(B / "cache2.npz"); m = pd.read_csv(B / "meta2.csv"); fut = m.fut.to_numpy(); T, N = z["sv"].shape; ND = T // 24
ivh, ev = z["ivh"], z["ev"]; st = ivh > 0
r8 = np.full((T, N), np.nan); r8[st] = ev[st] * 8 / ivh[st] * 100           # settled 8h-eq, %
r8f = pd.DataFrame(r8).ffill()
neg = (np.nan_to_num(r8, nan=0) < -0.1) & st
paid = pd.DataFrame(np.where(st & (np.nan_to_num(ev) < 0), -np.nan_to_num(ev) * 100, 0.0))
sc = pd.DataFrame(z["sc"]).ffill(); sq = pd.DataFrame(np.nan_to_num(z["sq"])); fq = pd.DataFrame(np.nan_to_num(z["fq"]))
oi = pd.DataFrame(z["oi"]).ffill(limit=168); r8p = pd.DataFrame(z["r8p"] * 100)
has = np.cumsum(st, 0) > 0; firsth = np.where(has.any(0), np.argmax(has, 0), T)
hrs = 24 * np.arange(1, ND) - 1                                                  # last hour before day d (d = 1..ND-1)
def at(df): return df.to_numpy()[hrs]                                            # (ND-1, N) value known at day d
roll = lambda df, w, f: getattr(df.rolling(w, min_periods=1), f)()
F = {
    "r_last8": at(r8f), "r_pred8": at(r8p),
    "m7": at(roll(r8f, 168, "mean")), "m30": at(roll(r8f, 720, "mean")),
    "min7": at(roll(pd.DataFrame(r8), 168, "min")),
    "paid7": at(roll(paid, 168, "sum")), "paid30": at(roll(paid, 720, "sum")),
    "pvol24_m": at(roll(fq, 24, "sum")) / 1e6, "svol24_m": at(roll(sq, 24, "sum")) / 1e6,
}
pv3, sv3 = at(roll(fq, 72, "sum")), at(roll(sq, 72, "sum")); F["pv_sv3"] = np.where(sv3 > 0, pv3 / np.maximum(sv3, 1), np.nan)
scv = sc.to_numpy()
for k in (7, 30, 60):
    prev = scv[np.maximum(hrs - 24 * k, 0)]; F[f"ret{k}"] = np.where(((hrs - 24 * k >= 0)[:, None]) & (prev > 0), (scv[hrs] / prev - 1) * 100, np.nan)
oiv = oi.to_numpy(); F["oi_m"] = oiv[hrs] / 1e6
oir = pd.DataFrame(z["oi"]).ffill(limit=3).to_numpy()                            # OI with real data within 3h (gaps -> NaN, not a fake 0% change)
def oichg(h):
    a, b = oir[hrs], oir[np.maximum(hrs - h, 0)]
    with np.errstate(all="ignore"): return np.where(b > 0, (a / b - 1) * 100, np.nan)
F["oi7"] = oichg(168)
deepday = neg[:ND * 24].reshape(ND, 24, N).any(1)                               # day k had a deep settled print
cdd = np.vstack([np.zeros((1, N)), np.cumsum(deepday, 0)])
d_idx = np.arange(1, ND)
F["deep_days90"] = cdd[d_idx] - cdd[np.maximum(d_idx - 90, 0)]
last = np.full(N, np.nan); dsd = np.full((ND - 1, N), np.nan)
for i, d in enumerate(d_idx):
    last = np.where(deepday[d - 1], d - 1, last); dsd[i] = d - last
F["days_since_deep"] = dsd
F["age_d"] = (hrs[:, None] + 1 - firsth[None, :]) / 24
iv_last = pd.DataFrame(np.where(st, ivh, np.nan)).ffill().to_numpy(); F["iv"] = iv_last[hrs]
rows = []
for k, v in F.items(): rows.append(pd.DataFrame(v, columns=fut).stack(future_stack=True).rename(k))
X = pd.concat(rows, axis=1).reset_index(); X.columns = ["i", "sym"] + list(F); X["d"] = X.i + 1; X = X.drop(columns="i")
X = X[X.age_d > 1]
# CMC mcap / circulating (previous day's value)
cm = []
for f in fut:
    p = E / "supply_cmc" / f"{f}.csv"
    if not p.exists(): continue
    c = pd.read_csv(p); c["d"] = ((pd.to_datetime(c.date, utc=True) - T0) / pd.Timedelta(days=1)).round().astype(int) + 1   # known from next day
    c["circ_chg30"] = (c.circ / c.circ.shift(30) - 1) * 100; c["sym"] = f; cm.append(c[["d", "sym", "mcap", "circ", "circ_chg30"]])
cm = pd.concat(cm); X = X.merge(cm, on=["d", "sym"], how="left")
X["mcap_m"] = X.mcap / 1e6; X["oi_mc"] = np.where(X.mcap > 0, X.oi_m * 1e6 / X.mcap * 100, np.nan); X = X.drop(columns=["mcap", "circ"])
# cross-venue: last rate before day d and 7d mean (8h-eq %)
xv = []
for pre in ("bybit", "hl"):
    for f in fut:
        p = B / "data_xv" / f"{pre}_{f}.parquet"
        if not p.exists(): continue
        x = pd.read_parquet(p)
        if not len(x): continue
        x = x.sort_values("t"); iv = x.t.diff().dt.total_seconds().div(3600).round().clip(1, 8).bfill().fillna(8)
        s = pd.Series((x.rate * 8 / iv * 100).to_numpy(), index=x.t)
        day = ((s.index - T0) / pd.Timedelta(days=1)).astype(int)
        g = pd.DataFrame({"v": s.to_numpy(), "day": day}).groupby("day").v
        dl = pd.DataFrame({"last": g.last(), "mean": g.mean()}).reindex(range(ND)).ffill(limit=2)
        dl[f"{pre}_m7"] = dl["mean"].rolling(7, min_periods=1).mean(); dl[f"{pre}_now8"] = dl["last"]
        dl = dl[[f"{pre}_now8", f"{pre}_m7"]].shift(1); dl["d"] = dl.index; dl["sym"] = f; xv.append(dl.reset_index(drop=True))
XV = pd.concat(xv); XV = XV.groupby(["d", "sym"]).first().reset_index()
X = X.merge(XV, on=["d", "sym"], how="left")
# hourly-derived features at 00:00 of day d ("warming up" signals)
r8pv = z["r8p"] * 100; fcv = pd.DataFrame(z["fc"]).ffill().to_numpy(); prem = (fcv / scv - 1) * 100
def lagh(a, h): return a[np.maximum(hrs - h, 0)]
fqv, sqv = fq.to_numpy(), sq.to_numpy()
with np.errstate(all="ignore"):
    HX = {"pred_24min": roll(pd.DataFrame(r8pv), 24, "min").to_numpy()[hrs], "pred_24mean": roll(pd.DataFrame(r8pv), 24, "mean").to_numpy()[hrs],
          "pred_72mean": roll(pd.DataFrame(r8pv), 72, "mean").to_numpy()[hrs], "prem24": roll(pd.DataFrame(prem), 24, "mean").to_numpy()[hrs],
          "prem_now": prem[hrs], "ret1": (scv[hrs] / lagh(scv, 24) - 1) * 100, "ret3": (scv[hrs] / lagh(scv, 72) - 1) * 100,
          "oi1": oichg(24), "oi3": oichg(72),
          "pvol_surge": fq.rolling(24).sum().to_numpy()[hrs] / np.maximum(fq.rolling(168).sum().to_numpy()[hrs] / 7, 1),
          "pv_sv1": fq.rolling(24).sum().to_numpy()[hrs] / np.maximum(sq.rolling(24).sum().to_numpy()[hrs], 1),
          "dd30": (scv[hrs] / sc.rolling(720, min_periods=1).max().to_numpy()[hrs] - 1) * 100}
HX["pred_trend"] = HX["pred_24mean"] - HX["pred_72mean"]
hr = [pd.DataFrame(v, columns=fut).stack(future_stack=True).rename(k) for k, v in HX.items()]
Hh = pd.concat(hr, axis=1).replace([np.inf, -np.inf], np.nan).reset_index(); Hh.columns = ["i", "sym"] + list(HX); Hh["d"] = Hh.i + 1; Hh = Hh.drop(columns="i")
X = X.merge(Hh, on=["d", "sym"], how="left")
X["quiet"] = ~((X.min7 < -0.1) | (X.r_pred8 < -0.1))
np.savez_compressed(O / "hourly.npz", fut=fut, r8=r8, pred=r8pv, prem=prem, close=scv, oi=oiv, pvol=fqv, svol=sqv)
num = X.select_dtypes("number").columns; X[num] = X[num].round(4)
X.to_parquet(O / "features.parquet", index=False)
# daily series (day k values; visible when k < as_of day)
D = {"fund_min8": pd.DataFrame(np.where(st, r8, np.nan)), "pred_min8": r8p, "close": sc, "perp_vol_m": fq / 1e6, "spot_vol_m": sq / 1e6, "oi_m": oi / 1e6}
dd = []
for k, df in D.items():
    a = df.to_numpy()[:ND * 24].reshape(ND, 24, N)
    with np.errstate(all="ignore"):
        v = np.nanmin(a, 1) if k.endswith("min8") else (np.nansum(a, 1) if "vol" in k else a[:, -1])
    dd.append(pd.DataFrame(v, columns=fut).stack(future_stack=True).rename(k))
with np.errstate(all="ignore"):
    fm = np.nanmean(np.where(st, r8, np.nan)[:ND * 24].reshape(ND, 24, N), 1)
dd.append(pd.DataFrame(fm, columns=fut).stack(future_stack=True).rename("fund_mean8"))
Dd = pd.concat(dd, axis=1).reset_index(); Dd.columns = ["day", "sym"] + list(D) + ["fund_mean8"]
Dd = Dd.merge(XV.assign(day=XV.d - 1).drop(columns="d"), on=["day", "sym"], how="left")    # venue values of that day
Dd = Dd.merge(cm.assign(day=cm.d - 1).drop(columns=["d", "circ_chg30"]), on=["day", "sym"], how="left")
Dd = Dd[Dd.close.notna()]; num = Dd.select_dtypes("number").columns; Dd[num] = Dd[num].round(5)
Dd.to_parquet(O / "daily.parquet", index=False)
P = pd.read_parquet(E / "panel.parquet")[["d", "fut", "hit", "mag"]].rename(columns={"fut": "sym"}); P.to_parquet(O / "outcomes.parquet", index=False)
ep = pd.read_csv(B / "cases" / "episodes_all.csv"); ep.rename(columns={"fut": "sym"}).to_csv(O / "episodes.csv", index=False)
an = pd.read_csv(E / "events_ann.csv")[["type", "fut", "ts", "title"]].rename(columns={"fut": "sym"}); an.to_csv(O / "announcements.csv", index=False)
print("features", X.shape, "daily", Dd.shape, "outcomes", P.shape, "d range", X.d.min(), X.d.max())
