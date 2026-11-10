"""Per-coin hourly simulator for the spot->perp negative-funding loop (numba), with signal / entry / exit / OI-cap /
self-impact switches and per-episode attribution.  All decisions at bar t use information known at the start of bar t
(closes of t-1, funding settled at the start of t, premium of closed bars); fills at the VWAP of bar t."""
import numpy as np, pandas as pd
from numba import njit
from pathlib import Path
B = Path(__file__).resolve().parent

PN = ["sig", "entry_thr", "exit_thr", "basis_thr", "wait_max", "wait_cap", "cap", "pov", "dfrac", "vol_frac", "oi_frac",
      "k_imp", "impact", "depth_k", "fee_s", "fee_f", "exit_confirm", "min_r8s_entry", "trim"]
DEF = dict(sig=0, entry_thr=0.001, exit_thr=0.0, basis_thr=-0.0038, wait_max=168, wait_cap=0.003, cap=1e4, pov=0.20,
           dfrac=0.75, vol_frac=0.10, oi_frac=0.0, k_imp=0.0, impact=0.0002, depth_k=0.005, fee_s=0.001, fee_f=0.0005,
           exit_confirm=1, min_r8s_entry=-1.0, trim=0)
def mkp(**kw):
    d = dict(DEF); bad = set(kw) - set(PN); assert not bad, bad; d.update(kw); return np.array([d[k] for k in PN], np.float64)

@njit(cache=True)
def run_coin(sv, sc, sq, fv, fc, fq, ev, ivh, r8s, r8p, oi, hs_s, hs_f, r2, h0, h1, P, ep):
    sig = P[0]; ent = P[1]; ext = P[2]; bthr = P[3]; wmax = P[4]; wcap = P[5]; cap = P[6]; pov = P[7]; dfrac = P[8]
    vfrac = P[9]; oifrac = P[10]; kimp = P[11]; imp = P[12]; dk = P[13]; fee_s = P[14]; fee_f = P[15]; conf = P[16]
    minr8s = P[17]; trim = P[18]
    T = sv.shape[0]
    # causal depth proxy (trailing 24h median of min(spot,perp) hourly quote volume, up to t-1) and yesterday's volume
    mv = np.minimum(sq, fq); d1 = np.zeros(T); buf = np.zeros(24)
    for t in range(1, T):
        n = 0
        for j in range(max(0, t - 24), t):
            if mv[j] > 0: buf[n] = mv[j]; n += 1
        d1[t] = 2.4 * (np.median(buf[:n]) if n >= 6 else 0.0)
    D2 = d1 * max(r2, 1.05)
    dv = np.zeros(T)
    for t in range(24, T):
        day0 = (t // 24) * 24
        if day0 >= 24:
            s1 = 0.0; s2 = 0.0
            for j in range(day0 - 24, day0): s1 += sq[j]; s2 += fq[j]
            dv[t] = min(s1, s2)
    pos = 0.0; spa = 0.0; fpa = 0.0; fees_acc = 0.0; fund_acc = 0.0; used = 0.0; ent_not = 0.0
    wait = 0; wait_h = 0; wait_paid = 0.0; exiting = 0; cnt_exit = 0
    lsc = np.nan; lfc = np.nan; ne = 0
    e_t0 = 0; e_fund = 0.0; e_price = 0.0; e_fees = 0.0; e_cost = 0.0; e_max = 0.0; e_sig = 0.0; e_basis = 0.0; e_iv = 0.0; e_hc = 0.0; e_paid = 0.0
    out = np.zeros(8)   # fund, price, fees, cost, hours_in, used_hours, eps, haircut_lost
    for t in range(max(h0, 1), h1):
        last = t == h1 - 1
        psc = lsc; pfc = lfc
        if sc[t] > 0: lsc = sc[t]
        if fc[t] > 0: lfc = fc[t]
        o = oi[t - 1]
        share = (pos * pfc / o) if (pos > 0 and o > 0 and pfc > 0) else 0.0
        d8 = kimp * 1e-4 * share * 100.0            # our own lift of the 8h-equivalent rate
        s_set = r8s[t]; s_pre = r8p[t]
        bothok = np.isfinite(s_set) and np.isfinite(s_pre)
        smax = max(s_set, s_pre) if bothok else np.nan
        smin = min(s_set, s_pre) if bothok else (s_set if np.isfinite(s_set) else s_pre)
        if sig == 0: s = s_set; sx = s_set
        elif sig == 1: s = s_pre; sx = s_pre
        elif sig == 2: s = smax; sx = smax
        elif sig == 3: s = smin; sx = smin
        elif sig == 4: s = smax; sx = s_set          # stricter entry, Leslie exit
        elif sig == 5: s = s_set; sx = smin          # Leslie entry, hold while either says negative
        elif sig == 6: s = s_set; sx = s_pre if np.isfinite(s_pre) else s_set   # Leslie entry, exit on prediction
        else: s = smax; sx = smin                    # strict entry, patient exit
        if np.isfinite(s) and s < 0: s = min(s + d8, 0.0)
        if np.isfinite(sx) and sx < 0: sx = min(sx + d8, 0.0)
        if pos > 0:
            out[4] += 1; out[5] += used
            if ev[t] != 0.0:
                iv = ivh[t] if ivh[t] > 0 else 8.0
                rate = ev[t]
                if rate < 0:
                    adj = min(rate + d8 * iv / 8.0, 0.0); out[7] += -(adj - rate) * (pfc if pfc > 0 else psc) * pos; e_hc += -(adj - rate) * (pfc if pfc > 0 else psc) * pos; rate = adj
                f = -rate * (pfc if pfc > 0 else psc) * pos
                fund_acc += f; out[0] += f; e_fund += f
                if wait > 0 and f < 0: wait_paid += -f
                if f < 0: e_paid += -f
            have = sv[t] > 0 and fv[t] > 0
            if have or last:
                do = exiting > 0
                if not do and np.isfinite(sx):
                    if sx > -ext:
                        cnt_exit += 1
                        if cnt_exit >= conf:
                            if wmax <= 0: do = True
                            else:
                                spx = psc * (1 + hs_s + imp); fpx = pfc * (1 - hs_f - imp)
                                est = pos * (spa - spx) + pos * (fpx - fpa) + fund_acc - fees_acc - pos * (spx * fee_s + fpx * fee_f)
                                if est >= 0: do = True
                                else:
                                    if wait == 0: wait = 1; wait_h = 0; wait_paid = 0.0
                                    wait_h += 1
                                    if wait_h >= wmax or wait_paid >= wcap * ent_not: do = True
                    else:
                        cnt_exit = 0; wait = 0; wait_h = 0; wait_paid = 0.0
                if last: do = True
                tq = 0.0
                if (not do) and trim > 0 and oifrac > 0 and o > 0 and pos * pfc > 1.5 * oifrac * o: tq = pos * pfc - oifrac * o
                if do or tq > 0:
                    if do: exiting = 1
                    smid = sv[t] if sv[t] > 0 else lsc; fmid = fv[t] if fv[t] > 0 else lfc
                    Qpos = pos * smid if do else min(tq, pos * smid)
                    lim = max(0.0, min(pov * mv[t], dfrac * D2[t]))
                    Q = Qpos if (last or not have) else min(Qpos, lim)
                    if Q > 0:
                        x = min(Q / smid, pos)
                        ie = imp + (dk * Q / d1[t] if (dk > 0 and d1[t] > 0) else 0.0)
                        spx = smid * (1 + hs_s + ie); fpx = fmid * (1 - hs_f - ie)
                        pr = x * (fpx - fpa) + x * (spa - spx); fe = x * fpx * fee_f + x * spx * fee_s
                        cst = x * smid * (hs_s + ie) + x * fmid * (hs_f + ie)
                        out[1] += pr; out[2] += fe; out[3] += cst; e_price += pr; e_fees += fe; e_cost += cst
                        frac = x / pos; fees_acc -= fees_acc * frac; used *= (1 - frac); pos -= x
                        if pos <= 1e-12 or pos * smid < 1e-6:
                            if ne < ep.shape[0]:
                                ep[ne, 0] = e_t0; ep[ne, 1] = t; ep[ne, 2] = e_fund; ep[ne, 3] = e_price; ep[ne, 4] = e_fees
                                ep[ne, 5] = e_cost; ep[ne, 6] = e_max; ep[ne, 7] = e_sig; ep[ne, 8] = e_basis; ep[ne, 9] = e_iv
                                ep[ne, 10] = e_hc; ep[ne, 11] = e_paid
                            ne += 1; out[6] += 1
                            pos = 0.0; used = 0.0; exiting = 0; wait = 0; wait_h = 0; wait_paid = 0.0; fund_acc = 0.0; cnt_exit = 0
        # entries / adds
        if t < h1 - 24 and exiting == 0 and sv[t] > 0 and fv[t] > 0 and np.isfinite(s):
            s1 = sc[t - 1]; f1 = fc[t - 1]
            if s1 > 0 and f1 > 0 and s < -ent and (f1 - s1) / s1 <= bthr and (not (minr8s > -1.0) or (np.isfinite(s_set) and s_set < minr8s)):
                Q = min(pov * mv[t], dfrac * D2[t], cap - used)
                if vfrac > 0 and dv[t] > 0: Q = min(Q, vfrac * dv[t] - used)
                if vfrac > 0 and dv[t] <= 0: Q = 0.0
                if oifrac > 0:
                    if o > 0: Q = min(Q, oifrac * o - pos * (pfc if pfc > 0 else fv[t]))
                    else: Q = 0.0
                if Q > 1.0:
                    ie = imp + (dk * Q / d1[t] if (dk > 0 and d1[t] > 0) else 0.0)
                    x = Q / sv[t]; spe = sv[t] * (1 - hs_s - ie); fpe = fv[t] * (1 + hs_f + ie)
                    fe = x * fpe * fee_f + x * spe * fee_s; cst = x * sv[t] * (hs_s + ie) + x * fv[t] * (hs_f + ie)
                    if pos == 0:
                        spa = spe; fpa = fpe; ent_not = Q; fund_acc = 0.0; wait = 0; wait_h = 0; wait_paid = 0.0; cnt_exit = 0
                        e_t0 = t; e_fund = 0.0; e_price = 0.0; e_fees = 0.0; e_cost = 0.0; e_max = 0.0; e_sig = s; e_basis = (f1 - s1) / s1
                        e_iv = ivh[t] if ivh[t] > 0 else 0.0; e_hc = 0.0; e_paid = 0.0
                    else:
                        spa = (spa * pos + spe * x) / (pos + x); fpa = (fpa * pos + fpe * x) / (pos + x); ent_not += Q
                    pos += x; fees_acc += fe; out[2] += fe; out[3] += cst; e_fees += fe; e_cost += cst; used += Q
                    if used > e_max: e_max = used
    return out, ne

class Data:
    def __init__(self, spread="spread_all.csv", cache="cache2.npz"):
        z = np.load(B / cache); self.a = {k: z[k] for k in z.files}; self.meta = pd.read_csv(B / "meta2.csv")
        self.N = len(self.meta); self.T0 = pd.Timestamp("2025-04-01", tz="UTC")
        sp = pd.read_csv(B / spread).set_index("sym") if (B / spread).exists() else pd.DataFrame(columns=["hs_s","hs_f"]); L = pd.read_csv("/tmp/claude-0/-root-celueyanjiu/192bae5e-ba9e-4e6e-a633-2ab87bd4f441/scratchpad/leslie_repo/spread_by_symbol.csv")
        ls = L[L.market == "spot"].set_index("symbol").half_spread_med; lf = L[L.market == "fut"].set_index("symbol").half_spread_med
        hs_s = []; hs_f = []
        for r in self.meta.itertuples():
            a = sp.hs_s.get(r.fut, np.nan); b = sp.hs_f.get(r.fut, np.nan)
            a = max(a, ls.get(r.spot, 0)) if np.isfinite(a) else ls.get(r.spot, np.nan)   # the larger of our and Leslie's estimate
            b = max(b, lf.get(r.fut, 0)) if np.isfinite(b) else lf.get(r.fut, np.nan)
            hs_s.append(a); hs_f.append(b)
        hs_s = np.array(hs_s); hs_f = np.array(hs_f)
        self.hs_s = np.where(np.isfinite(hs_s), hs_s, np.nanpercentile(hs_s, 75)); self.hs_f = np.where(np.isfinite(hs_f), hs_f, np.nanpercentile(hs_f, 75))
        tr = pd.read_csv("/tmp/claude-0/-root-celueyanjiu/192bae5e-ba9e-4e6e-a633-2ab87bd4f441/scratchpad/leslie_repo/tier_ratios.csv").set_index("symbol")
        self.r2 = np.array([float(tr.r2.get(f, tr.r2.median())) for f in self.meta.fut])
    def h(self, d): return int((pd.Timestamp(d, tz="UTC") - self.T0).total_seconds() // 3600)
    def run(self, w0, w1, cols=None, caps=None, **kw):
        P = mkp(**kw); h0, h1 = self.h(w0), self.h(w1); a = self.a
        cols = range(self.N) if cols is None else cols
        rows = []; eps = []
        for n in cols:
            if caps is not None: P[PN.index("cap")] = caps[n]
            ep = np.zeros((3000, 12))
            out, ne = run_coin(a["sv"][:, n], a["sc"][:, n], a["sq"][:, n], a["fv"][:, n], a["fc"][:, n], a["fq"][:, n], a["ev"][:, n],
                               a["ivh"][:, n], a["r8s"][:, n], a["r8p"][:, n], a["oi"][:, n], self.hs_s[n], self.hs_f[n], self.r2[n], h0, h1, P, ep)
            rows.append((self.meta.fut[n], *out))
            if ne: e = pd.DataFrame(ep[:min(ne, 3000)], columns=["t0", "t1", "fund", "price", "fees", "cost", "maxu", "sig", "basis", "iv", "hc", "paid"]); e["sym"] = self.meta.fut[n]; eps.append(e)
        df = pd.DataFrame(rows, columns=["sym", "fund", "price", "fees", "cost", "hours_in", "used_h", "eps", "hc_lost"]); df["net"] = df.fund + df.price - df.fees
        E = pd.concat(eps) if eps else pd.DataFrame(); 
        if len(E): E["net"] = E.fund + E.price - E.fees; E["basis_pnl"] = E.price + E.cost; E["dur_h"] = E.t1 - E.t0
        return df, E, (h1 - h0) / 24 / 365
