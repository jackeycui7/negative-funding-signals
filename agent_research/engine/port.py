"""Portfolio version of sim2.run_coin: all coins advance hour by hour and share one capital budget S.
Same rules, costs, self-impact and exits as sim2 (settled-funding signal); when several coins qualify in the same hour,
the deepest funding is filled first. Used capital = entry notional of open positions (the spot sold)."""
import numpy as np, pandas as pd
from numba import njit
from sim2 import Data, mkp, PN

@njit(cache=True)
def prep(sq, fq, r2):
    T, N = sq.shape; d1 = np.zeros((T, N)); D2 = np.zeros((T, N)); dv = np.zeros((T, N)); buf = np.zeros(24)
    for n in range(N):
        for t in range(1, T):
            k = 0
            for j in range(max(0, t - 24), t):
                m = min(sq[j, n], fq[j, n])
                if m > 0: buf[k] = m; k += 1
            d1[t, n] = 2.4 * (np.median(buf[:k]) if k >= 6 else 0.0)
            D2[t, n] = d1[t, n] * max(r2[n], 1.05)
        for t in range(48, T):
            day0 = (t // 24) * 24; s1 = 0.0; s2 = 0.0
            for j in range(day0 - 24, day0): s1 += sq[j, n]; s2 += fq[j, n]
            dv[t, n] = min(s1, s2)
    return d1, D2, dv

@njit(cache=True)
def run_port(sv, sc, sq, fv, fc, fq, ev, ivh, r8s, oi, hs_s, hs_f, d1, D2, dv, caps, S, h0, h1, P, ok):
    ent = P[1]; ext = P[2]; bthr = P[3]; wmax = P[4]; wcap = P[5]; pov = P[7]; dfrac = P[8]
    vfrac = P[9]; oifrac = P[10]; kimp = P[11]; imp = P[12]; dk = P[13]; fee_s = P[14]; fee_f = P[15]; conf = P[16]
    T, N = sv.shape
    pos = np.zeros(N); spa = np.zeros(N); fpa = np.zeros(N); fees_acc = np.zeros(N); fund_acc = np.zeros(N); used = np.zeros(N); ent_not = np.zeros(N)
    wait = np.zeros(N); wait_h = np.zeros(N); wait_paid = np.zeros(N); exiting = np.zeros(N); cnt = np.zeros(N)
    lsc = np.full(N, np.nan); lfc = np.full(N, np.nan); psc = np.full(N, np.nan); pfc = np.full(N, np.nan)
    tot = np.zeros(6)   # fund, price, fees, used_hours, max_used, episodes
    used_total = 0.0
    cand = np.zeros(N, np.int64); key = np.zeros(N)
    for t in range(max(h0, 1), h1):
        last = t == h1 - 1
        for n in range(N):
            psc[n] = lsc[n]; pfc[n] = lfc[n]
            if sc[t, n] > 0: lsc[n] = sc[t, n]
            if fc[t, n] > 0: lfc[n] = fc[t, n]
        # exits and funding
        for n in range(N):
            if pos[n] <= 0: continue
            o = oi[t - 1, n]; share = (pos[n] * pfc[n] / o) if (o > 0 and pfc[n] > 0) else 0.0
            d8 = kimp * 1e-4 * share * 100.0
            s = r8s[t, n]
            if np.isfinite(s) and s < 0: s = min(s + d8, 0.0)
            if ev[t, n] != 0.0:
                iv = ivh[t, n] if ivh[t, n] > 0 else 8.0; rate = ev[t, n]
                if rate < 0: rate = min(rate + d8 * iv / 8.0, 0.0)
                px = pfc[n] if pfc[n] > 0 else psc[n]; f = -rate * px * pos[n]
                fund_acc[n] += f; tot[0] += f
                if wait[n] > 0 and f < 0: wait_paid[n] += -f
            have = sv[t, n] > 0 and fv[t, n] > 0
            if not (have or last): continue
            do = exiting[n] > 0
            if not do and np.isfinite(s):
                if s > -ext:
                    cnt[n] += 1
                    if cnt[n] >= conf:
                        spx = psc[n] * (1 + hs_s[n] + imp); fpx = pfc[n] * (1 - hs_f[n] - imp)
                        est = pos[n] * (spa[n] - spx) + pos[n] * (fpx - fpa[n]) + fund_acc[n] - fees_acc[n] - pos[n] * (spx * fee_s + fpx * fee_f)
                        if est >= 0: do = True
                        else:
                            if wait[n] == 0: wait[n] = 1; wait_h[n] = 0; wait_paid[n] = 0.0
                            wait_h[n] += 1
                            if wait_h[n] >= wmax or wait_paid[n] >= wcap * ent_not[n]: do = True
                else:
                    cnt[n] = 0; wait[n] = 0; wait_h[n] = 0; wait_paid[n] = 0.0
            if last: do = True
            if not do: continue
            exiting[n] = 1
            smid = sv[t, n] if sv[t, n] > 0 else lsc[n]; fmid = fv[t, n] if fv[t, n] > 0 else lfc[n]
            Qpos = pos[n] * smid
            lim = max(0.0, min(pov * min(sq[t, n], fq[t, n]), dfrac * D2[t, n]))
            Q = Qpos if (last or not have) else min(Qpos, lim)
            if Q <= 0: continue
            x = min(Q / smid, pos[n]); ie = imp + (dk * Q / d1[t, n] if (dk > 0 and d1[t, n] > 0) else 0.0)
            spx = smid * (1 + hs_s[n] + ie); fpx = fmid * (1 - hs_f[n] - ie)
            tot[1] += x * (fpx - fpa[n]) + x * (spa[n] - spx); tot[2] += x * fpx * fee_f + x * spx * fee_s
            frac = x / pos[n]; fees_acc[n] -= fees_acc[n] * frac; rel = used[n] * frac; used[n] -= rel; used_total -= rel; pos[n] -= x
            if pos[n] <= 1e-12 or pos[n] * smid < 1e-6:
                used_total -= used[n]; used[n] = 0.0; pos[n] = 0.0; exiting[n] = 0; wait[n] = 0; wait_h[n] = 0; wait_paid[n] = 0.0; fund_acc[n] = 0.0; cnt[n] = 0; tot[5] += 1
        # entries: deepest funding first, shared budget S
        if t < h1 - 24:
            nc = 0
            for n in range(N):
                if exiting[n] > 0 or ok[t, n] == 0 or not (sv[t, n] > 0 and fv[t, n] > 0): continue
                s = r8s[t, n]
                if not np.isfinite(s): continue
                o = oi[t - 1, n]
                if pos[n] > 0:
                    share = (pos[n] * pfc[n] / o) if (o > 0 and pfc[n] > 0) else 0.0
                    if s < 0: s = min(s + kimp * 1e-4 * share * 100.0, 0.0)
                s1 = sc[t - 1, n]; f1 = fc[t - 1, n]
                if s1 > 0 and f1 > 0 and s < -ent and (f1 - s1) / s1 <= bthr:
                    cand[nc] = n; key[nc] = s; nc += 1
            if nc > 0:
                order = np.argsort(key[:nc])
                for oi_ in range(nc):
                    n = cand[order[oi_]]
                    room = S - used_total
                    if room <= 1.0: break
                    Q = min(pov * min(sq[t, n], fq[t, n]), dfrac * D2[t, n], caps[n] - used[n], room)
                    if vfrac > 0: Q = min(Q, vfrac * dv[t, n] - used[n]) if dv[t, n] > 0 else 0.0
                    if oifrac > 0:
                        o = oi[t - 1, n]; Q = min(Q, oifrac * o - pos[n] * (pfc[n] if pfc[n] > 0 else fv[t, n])) if o > 0 else 0.0
                    if Q <= 1.0: continue
                    ie = imp + (dk * Q / d1[t, n] if (dk > 0 and d1[t, n] > 0) else 0.0)
                    x = Q / sv[t, n]; spe = sv[t, n] * (1 - hs_s[n] - ie); fpe = fv[t, n] * (1 + hs_f[n] + ie)
                    fe = x * fpe * fee_f + x * spe * fee_s
                    if pos[n] == 0:
                        spa[n] = spe; fpa[n] = fpe; ent_not[n] = Q; fund_acc[n] = 0.0; wait[n] = 0; wait_h[n] = 0; wait_paid[n] = 0.0; cnt[n] = 0
                    else:
                        spa[n] = (spa[n] * pos[n] + spe * x) / (pos[n] + x); fpa[n] = (fpa[n] * pos[n] + fpe * x) / (pos[n] + x); ent_not[n] += Q
                    pos[n] += x; fees_acc[n] += fe; tot[2] += fe; used[n] += Q; used_total += Q
        tot[3] += used_total
        if used_total > tot[4]: tot[4] = used_total
    return tot

class Port:
    def __init__(self, d=None):
        self.d = d or Data(); a = self.d.a
        self.d1, self.D2, self.dv = prep(a["sq"], a["fq"], self.d.r2)
    def run(self, w0, w1, S, caps, ok=None, **kw):
        d = self.d; a = d.a; P = mkp(**kw); h0, h1 = d.h(w0), d.h(w1)
        tot = run_port(a["sv"], a["sc"], a["sq"], a["fv"], a["fc"], a["fq"], a["ev"], a["ivh"], a["r8s"], a["oi"], d.hs_s, d.hs_f,
                       self.d1, self.D2, self.dv, caps, S, h0, h1, P, np.ones(a["sv"].shape, np.uint8) if ok is None else ok.astype(np.uint8))
        y = (h1 - h0) / 24 / 365
        return dict(net=tot[0] + tot[1] - tot[2], fund=tot[0], price=tot[1], fees=tot[2], avg_used=tot[3] / (h1 - h0), max_used=tot[4], eps=int(tot[5]), years=y, ann=(tot[0] + tot[1] - tot[2]) / S / y * 100)
