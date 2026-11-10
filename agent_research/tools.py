"""Point-in-time research tools for the negative-funding agent.

Every tool is bound to an AS_OF day (00:00 UTC) fixed by the caller; the model cannot change it.
Nothing dated on or after AS_OF is ever returned. Outcomes are only used inside base_rates(), and only for
decision days whose 7-day outcome window had fully ended before AS_OF.
"""
import json, numpy as np, pandas as pd
from pathlib import Path
DATA = Path(__file__).resolve().parent / "data"
T0 = pd.Timestamp("2025-04-01", tz="UTC")
_F = pd.read_parquet(DATA / "features.parquet")
_D = pd.read_parquet(DATA / "daily.parquet")
_Y = pd.read_parquet(DATA / "outcomes.parquet")
_EP = pd.read_csv(DATA / "episodes.csv"); _EP["start"] = pd.to_datetime(_EP.start, utc=True); _EP["end"] = pd.to_datetime(_EP.end, utc=True)
_HZ = np.load(DATA / "hourly.npz", allow_pickle=True); _HI = {s: i for i, s in enumerate(_HZ["fut"])}
_H = {k: _HZ[k] for k in ("r8", "pred", "prem", "close", "oi", "pvol", "svol")}
_AN = pd.read_csv(DATA / "announcements.csv"); _AN["ts"] = pd.to_datetime(_AN.ts, utc=True, format="ISO8601")
SCREEN_COLS = list(_F.columns.drop(["d"]))
COL_DOC = {
    "sym": "Binance USDT perpetual symbol", "r_last8": "last settled funding, 8h-equivalent %", "r_pred8": "last predicted funding (from premium index), 8h-eq %",
    "m7": "mean settled funding over 7d, 8h-eq %", "m30": "mean settled funding over 30d, 8h-eq %", "min7": "deepest settled print in 7d, 8h-eq %",
    "paid7": "funding a 1x long received over 7d, % of notional", "paid30": "same over 30d", "pvol24_m": "perp volume 24h, $M", "svol24_m": "Binance spot volume 24h, $M",
    "pv_sv3": "perp/spot volume ratio over 72h", "ret7": "price change 7d %", "ret30": "price change 30d %", "ret60": "price change 60d %",
    "oi_m": "open interest $M", "oi7": "OI change 7d %", "deep_days90": "days in last 90 with a settled print < -0.10% (8h-eq)",
    "days_since_deep": "days since the last such day", "age_d": "days since perp listing", "iv": "settlement interval hours",
    "circ_chg30": "circulating supply change 30d % (CMC; unlock proxy)", "mcap_m": "market cap $M (CMC)", "oi_mc": "OI / market cap %",
    "pred_24min": "lowest hourly predicted funding over last 24h, 8h-eq %", "pred_24mean": "mean predicted funding last 24h", "pred_72mean": "mean predicted funding last 72h",
    "pred_trend": "pred_24mean - pred_72mean (negative = predicted funding falling)", "prem24": "mean perp-vs-spot price premium last 24h, % (negative = perp below spot)",
    "prem_now": "perp-vs-spot premium at the last hour, %", "ret1": "price change 24h %", "ret3": "price change 72h %", "oi1": "OI change 24h %", "oi3": "OI change 72h %",
    "pvol_surge": "perp volume last 24h / average daily perp volume of last 7d", "pv_sv1": "perp/spot volume ratio last 24h", "dd30": "price vs 30d high, %",
    "quiet": "true if NOT already negative (min7 >= -0.1 and r_pred8 >= -0.1)",
    "bybit_now8": "Bybit last funding 8h-eq %", "bybit_m7": "Bybit 7d mean 8h-eq %", "hl_now8": "Hyperliquid last funding 8h-eq %", "hl_m7": "Hyperliquid 7d mean 8h-eq %",
}

def _j(x):
    return json.dumps(x, ensure_ascii=False, default=lambda o: None if (isinstance(o, float) and np.isnan(o)) else str(o))

def _clean(df):
    return json.loads(df.replace({np.nan: None}).to_json(orient="records", force_ascii=False))

class Tools:
    def __init__(self, as_of: str):
        self.ts = pd.Timestamp(as_of, tz="UTC").normalize()
        self.d = int((self.ts - T0) / pd.Timedelta(days=1))
        self.screen = _F[_F.d == self.d].drop(columns="d").reset_index(drop=True)
        if self.screen.empty: raise ValueError(f"no data for {as_of}")
        self.syms = set(self.screen.sym)

    # ---------------- tools ----------------
    def market_screen(self, filters: dict | None = None, sort_by: str = "m7", ascending: bool = True, limit: int = 60, columns: list | None = None):
        """Cross-section of all coins at AS_OF. filters: {"col__op": value}, op in lt/le/gt/ge/eq, e.g. {"min7__lt": -0.1, "ret30__gt": 60}."""
        x = self.screen
        for k, v in (filters or {}).items():
            c, _, op = k.partition("__")
            if c not in x.columns: return _j({"error": f"unknown column {c}"})
            s = x[c]
            m = {"lt": s < v, "le": s <= v, "gt": s > v, "ge": s >= v, "eq": s == v, "ne": s != v}.get(op or "eq")
            if m is None: return _j({"error": f"bad op in {k}"})
            x = x[m]
        if sort_by not in x.columns: return _j({"error": f"unknown sort column {sort_by}"})
        x = x.sort_values(sort_by, ascending=ascending, na_position="last")
        cols = ["sym"] + [c for c in (columns or SCREEN_COLS) if c in x.columns and c != "sym"]
        lim = int(min(max(limit, 1), 120))
        return _j({"as_of": str(self.ts.date()), "matched": int(len(x)), "returned": min(lim, len(x)), "rows": _clean(x[cols].head(lim))})

    def coin_detail(self, sym: str | None = None, days: int = 45, syms: list | None = None):
        """Daily history of one coin before AS_OF + its past deep-funding episodes."""
        if syms: return "[" + ",".join(self.coin_detail(x, days) for x in syms[:6]) + "]"
        if sym not in self.syms: return _j({"error": f"unknown symbol {sym}"})
        days = int(min(max(days, 5), 120))
        h = _D[(_D.sym == sym) & (_D.day < self.d) & (_D.day >= self.d - days)].copy()
        h.insert(0, "date", (T0 + pd.to_timedelta(h.day, unit="D")).dt.strftime("%Y-%m-%d")); h = h.drop(columns=["day", "sym"])
        e = _EP[(_EP.sym == sym) & (_EP.start < self.ts)].copy()
        ongoing = e[e.end >= self.ts]; past = e[e.end < self.ts]
        eps = [dict(start=str(r.start.date()), end=str(r.end.date()), days=round(r.days, 1), funding_paid_pct=round(r.paid_pct, 2), deepest_8h=round(r.min_r8, 3)) for r in past.itertuples()]
        eps += [dict(start=str(r.start.date()), end="ongoing", days=None, funding_paid_pct=None, deepest_8h=None) for r in ongoing.itertuples()]
        now = _clean(self.screen[self.screen.sym == sym])[0]
        return _j({"sym": sym, "as_of": str(self.ts.date()), "today_features": now,
                   "daily_columns": "fund_min8/fund_mean8 = settled funding that day 8h-eq % (min/mean); pred_min8 = min predicted; close = spot close; perp_vol_m/spot_vol_m $M; oi_m $M at day end; bybit/hl = venue funding 8h-eq %; mcap, circ = CMC",
                   "daily": _clean(h), "deep_episodes_before_as_of": eps[-15:], "n_episodes_total": len(eps)})

    def announcements(self, sym: str | None = None, days: int = 60):
        """Binance announcements before AS_OF (listings, margin, delistings, monitoring tags, HODLer, launchpool, funding adjustments)."""
        days = int(min(max(days, 1), 365))
        a = _AN[(_AN.ts < self.ts) & (_AN.ts >= self.ts - pd.Timedelta(days=days))]
        if sym: a = a[a.sym == sym]
        mon = _AN[(_AN.type == "monitoring") & (_AN.ts < self.ts)].drop_duplicates("sym", keep="last")
        out = [dict(sym=r.sym, time=r.ts.strftime("%Y-%m-%d %H:%M"), type=r.type, title=r.title) for r in a.sort_values("ts").itertuples()]
        tags = {r.sym: r.ts.strftime("%Y-%m-%d") for r in mon.itertuples() if (not sym or r.sym == sym)}
        return _j({"as_of": str(self.ts.date()), "n": len(out), "announcements": out[-150:], "monitoring_tag_added_on": tags})

    def base_rates(self):
        """Historical frequencies computed ONLY from decision days whose outcome window ended before AS_OF."""
        F = _F[_F.d <= self.d - 10].merge(_Y, on=["d", "sym"])
        if len(F) < 1000: return _j({"error": "not enough matured history"})
        neg = (F.min7 < -0.1) | (F.r_pred8 < -0.1); q = F[~neg]; n = F[neg]
        def g(x, name): return {"group": name, "coin_days": int(len(x)), "p_hit": round(float(x.hit.mean()), 3) if len(x) else None, "mean_depth": round(float(x.mag.mean()), 3) if len(x) else None}
        out = [g(F, "all coins"), g(n, "already negative (min7<-0.1 or predicted<-0.1)"), g(q, "quiet (not negative)")]
        for lo, hi in [(0, 0), (1, 4), (5, 11), (12, 24), (25, 90)]:
            out.append(g(q[(q.deep_days90 >= lo) & (q.deep_days90 <= hi)], f"quiet, deep_days90 {lo}-{hi}"))
            out.append(g(n[(n.deep_days90 >= lo) & (n.deep_days90 <= hi)], f"negative, deep_days90 {lo}-{hi}"))
        pp = (F.ret30 > 60) & (F.pv_sv3 > 5)
        out += [g(n[pp[neg]], "negative + post-pump (ret30>60%, perp/spot vol>5)"), g(q[pp[~neg]], "quiet + post-pump"),
                g(n[(F.ret30 > 50)[neg] & (F.ret7 < -10)[neg]], "negative + ret30>50% and ret7<-10% (rolling over)"),
                g(q[(q.bybit_m7 < -0.05) | (q.hl_m7 < -0.05)], "quiet but Bybit/HL 7d mean < -0.05"),
                g(q[q.oi_mc > q.oi_mc.quantile(0.9)], "quiet, OI/mcap top decile"), g(q[q.oi7 > 100], "quiet, OI +100% in 7d"),
                g(F[F.age_d < 45], "listed < 45 days"),
                g(q[(q.prem24 < -0.1) | (q.pred_24min < -0.05)], "quiet but warming (prem24<-0.1 or pred_24min<-0.05)"),
                g(q[(q.prem24 < -0.2) & (q.pred_24min < -0.08)], "quiet, hot (prem24<-0.2 and pred_24min<-0.08)"),
                g(q[(q.prem24 >= -0.05) & (q.pred_24min >= -0.02)], "quiet and cold (prem24>=-0.05, pred_24min>=-0.02)"),
                g(q[((q.prem24 < -0.1) | (q.pred_24min < -0.05)) & (q.deep_days90 >= 12)], "quiet, warming, deep_days90>=12"),
                g(q[((q.prem24 < -0.1) | (q.pred_24min < -0.05)) & (q.deep_days90 <= 4)], "quiet, warming, deep_days90<=4"),
                g(q[q.pred_trend < -0.03], "quiet, predicted funding falling (pred_trend<-0.03)"),
                g(q[q.age_d < 30], "quiet, listed < 30 days")]
        return _j({"as_of": str(self.ts.date()), "outcome": "hit = any settled 8h-eq print < -0.10% during [d+3, d+10); depth = sum of max(0, -r8-0.1)/8 per hour",
                   "history_used": f"decision days up to {(T0 + pd.Timedelta(days=self.d - 10)).date()}", "rates": out})

    def coin_hourly(self, syms: list, hours: int = 72, step: int = 2):
        """Hour-level path of up to 8 coins before AS_OF: settled funding, predicted funding, perp premium, price, OI, volumes."""
        if isinstance(syms, str): syms = [syms]
        hours = int(min(max(hours, 6), 240)); step = int(min(max(step, 1), 12)); end = 24 * self.d; out = {}
        for sym in syms[:8]:
            if sym not in self.syms or sym not in _HI: out[sym] = {"error": "unknown symbol"}; continue
            j = _HI[sym]; rows = []
            for h0 in range(max(end - hours, 0), end, step):
                sl = slice(h0, min(h0 + step, end))
                with np.errstate(all="ignore"):
                    r = _H["r8"][sl, j]
                    rows.append({"t": (T0 + pd.Timedelta(hours=h0)).strftime("%m-%d %H:00"),
                                 "settled_8h": None if np.all(np.isnan(r)) else round(float(np.nanmin(r)), 4),
                                 "pred_8h_min": round(float(np.nanmin(_H["pred"][sl, j])), 4) if not np.all(np.isnan(_H["pred"][sl, j])) else None,
                                 "prem_pct": round(float(np.nanmean(_H["prem"][sl, j])), 3) if not np.all(np.isnan(_H["prem"][sl, j])) else None,
                                 "close": float(f"{_H['close'][sl.stop - 1, j]:.6g}") if not np.isnan(_H["close"][sl.stop - 1, j]) else None,
                                 "oi_m": round(float(_H["oi"][sl.stop - 1, j]) / 1e6, 3) if not np.isnan(_H["oi"][sl.stop - 1, j]) else None,
                                 "perp_vol_m": round(float(np.nansum(_H["pvol"][sl, j])) / 1e6, 3), "spot_vol_m": round(float(np.nansum(_H["svol"][sl, j])) / 1e6, 3)})
            out[sym] = rows
        return _j({"as_of": str(self.ts.date()), "bucket_hours": step, "columns": "settled_8h = lowest settled funding in bucket (8h-eq %, null if no settlement); pred_8h_min = lowest predicted funding; prem_pct = mean perp/spot premium %; close/oi at bucket end", "coins": out})

    def past_onsets(self, lookback_days: int = 60, limit: int = 30):
        """Recent matured cases where a QUIET coin went deeply negative in the following window: what it looked like at decision time,
        plus median features of all onsets vs all quiet coins over the lookback. Only decision days whose window ended before AS_OF."""
        lo = self.d - 10 - int(min(max(lookback_days, 14), 240))
        F = _F[(_F.d <= self.d - 10) & (_F.d > lo) & _F.quiet].merge(_Y, on=["d", "sym"])
        if F.empty: return _j({"error": "no matured history"})
        top = F.sort_values("mag", ascending=False).drop_duplicates("sym").head(int(min(max(limit, 5), 60)))
        cols = ["sym", "mag", "deep_days90", "days_since_deep", "age_d", "ret7", "ret30", "ret3", "oi7", "oi3", "oi_mc", "pv_sv3", "r_pred8", "pred_24min", "pred_trend", "prem24", "mcap_m", "circ_chg30", "bybit_now8", "hl_now8"]
        t = top[cols].copy(); t.insert(1, "decision_day", (T0 + pd.to_timedelta(top.d, unit="D")).dt.strftime("%Y-%m-%d").to_numpy())
        feat = ["deep_days90", "days_since_deep", "age_d", "ret7", "ret30", "ret3", "oi7", "oi_mc", "pv_sv3", "r_pred8", "pred_24min", "pred_trend", "prem24", "mcap_m", "dd30"]
        hit = F[F.hit]; prof = {c: {"onsets_median": round(float(hit[c].median()), 3), "all_quiet_median": round(float(F[c].median()), 3)} for c in feat}
        return _j({"as_of": str(self.ts.date()), "window": f"decision days {(T0 + pd.Timedelta(days=lo + 1)).date()}..{(T0 + pd.Timedelta(days=self.d - 10)).date()}",
                   "quiet_coin_days": int(len(F)), "onset_rate": round(float(F.hit.mean()), 3), "depth_held_by_top5_coins_per_day": round(float(F.groupby('d').mag.apply(lambda m: m.nlargest(5).sum() / max(m.sum(), 1e-9)).mean()), 3),
                   "feature_profile": prof, "biggest_onsets": _clean(t.round(3))})

    def quiet_board(self, page: int = 1, per_page: int = 70):
        """The WHOLE quiet universe, compact, one line per coin, in pages (sorted by symbol so nothing is skipped).
        Each line: key features + 72h paths in 6h buckets (oldest -> newest) of min predicted funding and mean perp premium."""
        q = self.screen[self.screen.quiet].sort_values("sym").reset_index(drop=True)
        per = int(min(max(per_page, 20), 100)); pages = max(1, -(-len(q) // per)); page = int(min(max(page, 1), pages))
        self.board_seen = getattr(self, "board_seen", set()) | {page}
        an = _AN[(_AN.ts < self.ts) & (_AN.ts >= self.ts - pd.Timedelta(days=30))].groupby("sym").type.apply(lambda t: "/".join(sorted(set(t))))
        end = 24 * self.d; lines = []
        def f(v, nd=2): return "na" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}"
        for r in q.iloc[(page - 1) * per: page * per].itertuples():
            j = _HI.get(r.sym); pp = pr = "na"
            if j is not None:
                with np.errstate(all="ignore"):
                    pp = " ".join(f(np.nanmin(_H["pred"][h:h + 6, j]), 2) for h in range(end - 72, end, 6))
                    pr = " ".join(f(np.nanmean(_H["prem"][h:h + 6, j]), 2) for h in range(end - 72, end, 6))
            lines.append(f"{r.sym} | dd90={f(r.deep_days90,0)} since={f(r.days_since_deep,0)} age={f(r.age_d,0)} mcap={f(r.mcap_m,0)} oi/mc={f(r.oi_mc,1)} "
                         f"ret3/7/30={f(r.ret3,0)}/{f(r.ret7,0)}/{f(r.ret30,0)} pv/sv={f(r.pv_sv3,1)} volx={f(r.pvol_surge,1)} oi3={f(r.oi3,0)} "
                         f"byb={f(r.bybit_now8,3)} hl={f(r.hl_now8,3)} ann={an.get(r.sym, '-')} | pred6h: {pp} | prem6h: {pr}")
        return _j({"as_of": str(self.ts.date()), "page": page, "pages": pages, "quiet_coins": len(q), "pages_seen": sorted(self.board_seen),
                   "legend": "dd90=deep_days90, since=days_since_deep, ann=announcement types in last 30d; pred6h = min predicted funding (8h-eq %) per 6h bucket over the last 72h, oldest first; prem6h = mean perp-vs-spot premium % per 6h bucket",
                   "lines": lines})

    def chronic_rule(self, n: int = 40):
        """The mechanical baseline list the agent must beat: negative coins by m7, then quiet coins by deep_days90, oi_mc."""
        x = self.screen; neg = (x.min7 < -0.1) | (x.r_pred8 < -0.1)
        L = pd.concat([x[neg].sort_values("m7"), x[~neg].sort_values(["deep_days90", "oi_mc"], ascending=False)])
        return L.sym.head(n).tolist()

TOOL_SPECS = [
    {"type": "function", "function": {"name": "market_screen", "description": "Cross-section of all Binance USDT perps known at the decision time. Columns: " + "; ".join(f"{k}={v}" for k, v in COL_DOC.items()),
     "parameters": {"type": "object", "properties": {
        "filters": {"type": "object", "description": "{'col__op': number}, op in lt/le/gt/ge/eq/ne. Example {'min7__lt': -0.1} or {'quiet__eq': true}"},
        "sort_by": {"type": "string"}, "ascending": {"type": "boolean"}, "limit": {"type": "integer", "description": "max 120"},
        "columns": {"type": "array", "items": {"type": "string"}}}}}},
    {"type": "function", "function": {"name": "coin_detail", "description": "Daily history (funding, price, OI, volumes, other venues, mcap/supply) of one coin before the decision time, plus its past deep negative-funding episodes.",
     "parameters": {"type": "object", "properties": {"sym": {"type": "string"}, "syms": {"type": "array", "items": {"type": "string"}, "description": "up to 6 coins at once instead of sym"}, "days": {"type": "integer", "description": "5-120, default 45"}}}}},
    {"type": "function", "function": {"name": "quiet_board", "description": "The entire quiet (not-yet-negative) universe in pages, one compact line per coin with key features and its last-72h path of predicted funding and perp premium. Read every page so no candidate is missed.",
     "parameters": {"type": "object", "properties": {"page": {"type": "integer"}, "per_page": {"type": "integer", "description": "20-100, default 70"}}}}},
    {"type": "function", "function": {"name": "coin_hourly", "description": "Hour-level path (bucketed) of up to 8 coins before the decision time: settled and predicted funding, perp-vs-spot premium, price, OI, perp and spot volume. Use it to see whether a quiet coin is starting to turn.",
     "parameters": {"type": "object", "properties": {"syms": {"type": "array", "items": {"type": "string"}}, "hours": {"type": "integer", "description": "6-240, default 72"}, "step": {"type": "integer", "description": "bucket size in hours 1-12, default 2"}}, "required": ["syms"]}}},
    {"type": "function", "function": {"name": "past_onsets", "description": "Recent fully-matured cases where a quiet (not yet negative) coin went deeply negative in the following window: features at decision time for the biggest ones, plus a median feature profile of onsets vs all quiet coins.",
     "parameters": {"type": "object", "properties": {"lookback_days": {"type": "integer", "description": "14-240, default 60"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "announcements", "description": "Binance announcements before the decision time (new listings, spot/margin listing or removal, delistings, monitoring tags, HODLer airdrops, launchpool, funding-interval changes).",
     "parameters": {"type": "object", "properties": {"sym": {"type": "string"}, "days": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "base_rates", "description": "Historical hit rates and depth for typical setups, computed only from history that had fully played out before the decision time.",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "submit_list", "description": "Submit the final ranked borrow list. Call exactly once at the end.",
     "parameters": {"type": "object", "properties": {"picks": {"type": "array", "items": {"type": "object", "properties": {
        "rank": {"type": "integer"}, "sym": {"type": "string"}, "p_hit": {"type": "number"}, "archetype": {"type": "string", "enum": ["A", "B", "C", "D", "none"]},
        "reason": {"type": "string"}}, "required": ["rank", "sym", "p_hit", "archetype", "reason"]}}}, "required": ["picks"]}}},
]
