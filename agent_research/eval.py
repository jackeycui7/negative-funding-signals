"""Run the agent over historical decision dates and score it against baselines.

  python3 eval.py run   --tag v1 --set dev  [--workers 3] [--mode scratch|swap] [--model gpt-6-astra]
  python3 eval.py score --tag v1 [--set dev|holdout|all]

Date sets (Mondays). gpt-6-astra's knowledge ends around Oct/Nov 2025, so every date from 2026-01 on is out of its memory.
  dev     : 2026-01-05 .. 2026-06-29, every 2nd week   (for improving prompts / tools)
  holdout : 2026-07-06 .. 2026-10-12, every week        (report only; never tune on it)
Outcome: hit = any settled 8h-eq print < -0.10% in [d+3, d+10); depth = sum max(0, -r8-0.1)/8 per hour (%).
"""
import argparse, json, sys, numpy as np, pandas as pd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
A = Path(__file__).resolve().parent; sys.path.insert(0, str(A))
T0 = pd.Timestamp("2025-04-01")
DEV = [str(d.date()) for d in pd.date_range("2026-01-05", "2026-06-29", freq="14D")]
HOLD = [str(d.date()) for d in pd.date_range("2026-07-06", "2026-10-12", freq="7D")]
SETS = {"dev": DEV, "holdout": HOLD, "all": DEV + HOLD}

def cmd_run(a):
    from agent import run
    out = A / "runs" / a.tag; out.mkdir(parents=True, exist_ok=True)
    todo = [d for d in SETS[a.set] if not (out / f"{d}.json").exists()]
    def one(d):
        try:
            L = run(d, model=a.model, mode=a.mode, out=str(out)); print(d, len(L["picks"] or []), "picks", L["seconds"], "s", L["usage"], flush=True)
        except Exception as e: print(d, "FAILED", repr(e)[:200], flush=True)
    with ThreadPoolExecutor(a.workers) as ex: list(ex.map(one, todo))

def lists_for(d, picks):
    from tools import _F, _Y
    di = (pd.Timestamp(d) - T0).days
    F = _F[_F.d == di].merge(_Y[_Y.d == di], on=["d", "sym"], how="inner")
    neg = (F.min7 < -0.1) | (F.r_pred8 < -0.1)
    L = {"agent": [p["sym"] for p in sorted(picks, key=lambda p: p["rank"])],
         "chronic_rule": pd.concat([F[neg].sort_values("m7"), F[~neg].sort_values(["deep_days90", "oi_mc"], ascending=False)]).sym.tolist(),
         "m7_rank": F.sort_values("m7").sym.tolist(), "oracle": F.sort_values("mag", ascending=False).sym.tolist()}
    return F.assign(neg=neg), L

def warm_score(q):
    """Mechanical onset baseline: equal-weight ranks of repeat-offender history, perp discount, intraday predicted dip, OI/mcap."""
    return q.deep_days90.rank(pct=True) + (-q.prem24).rank(pct=True) + (-q.pred_24min).rank(pct=True) + q.oi_mc.rank(pct=True)

def _boot(dlt):
    bs = [dlt.sample(len(dlt), replace=True, random_state=i).mean() for i in range(2000)]
    return f"mean {dlt.mean():+.3f}, wins {(dlt > .01).sum()} / ties {(dlt.abs() <= .01).sum()} / losses {(dlt < -.01).sum()}, bootstrap 90% CI [{np.percentile(bs, 5):+.3f}, {np.percentile(bs, 95):+.3f}]"

def cmd_score_onset(a, run_dir):
    rows = []; cal = []; comb = []
    for d in SETS[a.set]:
        p = run_dir / f"{d}.json"
        if not p.exists(): continue
        log = json.loads(p.read_text())
        if not log.get("picks"): continue
        F, L = lists_for(d, log["picks"]); q = F[~F.neg].copy(); qi = q.set_index("sym"); qtot = q.mag.sum(); qh = q.hit.sum(); tot = F.mag.sum()
        q["w"] = warm_score(q)
        agent = [x for x in L["agent"] if x in qi.index]
        lists = {"agent": agent, "chronic_quiet": q.sort_values(["deep_days90", "oi_mc"], ascending=False).sym.tolist(),
                 "warm_score": q.sort_values("w", ascending=False).sym.tolist(), "oracle": q.sort_values("mag", ascending=False).sym.tolist()}
        for K in (5, 10, 15):
            for k, l in lists.items():
                s_ = qi.loc[l[:K]]
                rows.append(dict(date=d, K=K, method=k, quiet_depth=s_.mag.sum() / qtot, hit_rate=s_.hit.mean(), hits_caught=s_.hit.sum() / qh))
            rnd = [qi.sample(K, random_state=i) for i in range(200)]
            rows.append(dict(date=d, K=K, method="random", quiet_depth=np.mean([r.mag.sum() for r in rnd]) / qtot, hit_rate=np.mean([r.hit.mean() for r in rnd]), hits_caught=np.mean([r.hit.sum() for r in rnd]) / qh))
        Fi = F.set_index("sym"); ch = L["chronic_rule"]; negs = [x for x in ch if Fi.neg.get(x, False)]
        for K in (5, 10):
            def total(l): return Fi.reindex(l).mag.sum() / tot
            comb.append(dict(date=d, K=K, chronic40=total(ch[:40]), negs_plus_agent=total(negs[:40 - K] + agent[:K]),
                             negs_plus_warm=total(negs[:40 - K] + lists["warm_score"][:K]), quiet_share=qtot / tot, n_neg=len(negs)))
        pk = pd.DataFrame(log["picks"]).merge(F[["sym", "hit", "mag"]], on="sym", how="left"); pk["date"] = d; cal.append(pk)
    R = pd.DataFrame(rows); C = pd.concat(cal); M = pd.DataFrame(comb)
    out = [f"# Onset scorecard: tag={a.tag}, set={a.set}, dates={R.date.nunique()}\n",
           "Universe: quiet coins only (min7 >= -0.1 and r_pred8 >= -0.1 at decision time). quiet_depth = share of all quiet-coin depth in the window captured by the top-K.\n"]
    t = R.pivot_table(index=["K", "method"], values=["quiet_depth", "hit_rate", "hits_caught"], aggfunc="mean").round(3)
    out.append("## Mean over dates\n" + t.to_markdown() + "\n")
    W = R[R.K == 10].pivot(index="date", columns="method", values="quiet_depth")
    out.append("## Per date, top-10 quiet-depth share\n" + W.round(3).to_markdown() + "\n")
    out.append("## Paired (top-10 quiet-depth share)\n")
    for b in ("chronic_quiet", "warm_score", "random"): out.append(f"- agent vs {b}: " + _boot(W.agent - W[b]))
    Wh = R[R.K == 10].pivot(index="date", columns="method", values="hit_rate")
    out.append(f"- hit rate top-10: agent {Wh.agent.mean():.3f}, chronic_quiet {Wh.chronic_quiet.mean():.3f}, warm {Wh.warm_score.mean():.3f}, random {Wh.random.mean():.3f}")
    out.append("\n## Combined 40-coin list (share of ALL depth): negatives from the rule + K onset picks\n" + M.groupby("K").mean(numeric_only=True).round(3).to_markdown())
    for K in (5, 10): out.append(f"- K={K}, rule-negatives+agent vs chronic40: " + _boot(M[M.K == K].set_index("date").negs_plus_agent - M[M.K == K].set_index("date").chronic40))
    C["bin"] = pd.cut(C.p_hit, [0, .1, .2, .35, .5, .7, 1.0001], include_lowest=True)
    cb = C.groupby("bin", observed=True).agg(n=("hit", "size"), predicted=("p_hit", "mean"), actual=("hit", "mean")).round(3)
    out.append("\n## Calibration (onset picks)\n" + cb.to_markdown() + f"\nBrier {((C.p_hit - C.hit.astype(float)) ** 2).mean():.4f}\n")
    out.append("## Top-5 quiet onsets per date and whether the agent had them\n")
    for d in R.date.unique():
        log = json.loads((run_dir / f"{d}.json").read_text()); F, _ = lists_for(d, log["picks"]); q = F[~F.neg]
        ag = {p["sym"]: p["rank"] for p in log["picks"]}
        out.append(f"- {d}: " + ", ".join(f"{r.sym} {r.mag:.1f}" + (f" (rank {ag[r.sym]})" if r.sym in ag else "") for r in q.nlargest(5, "mag").itertuples()))
    txt = "\n".join(out); print(txt); (run_dir / f"SCORE_{a.set}.md").write_text(txt); R.to_csv(run_dir / f"scores_{a.set}.csv", index=False)

def cmd_score(a):
    run_dir = A / "runs" / a.tag; rows = []; cal = []
    first = next((run_dir / f"{d}.json" for d in SETS[a.set] if (run_dir / f"{d}.json").exists()), None)
    if first and json.loads(first.read_text()).get("mode") == "onset": return cmd_score_onset(a, run_dir)
    for d in SETS[a.set]:
        p = run_dir / f"{d}.json"
        if not p.exists(): continue
        log = json.loads(p.read_text())
        if not log.get("picks"): continue
        F, L = lists_for(d, log["picks"]); tot = F.mag.sum(); nh = F.hit.sum(); Fi = F.set_index("sym")
        for N in (20, 40):
            for k, l in L.items():
                s = Fi.reindex([x for x in l if x in Fi.index][:N])
                rows.append(dict(date=d, N=N, method=k, depth=s.mag.sum() / tot, hit_rate=s.hit.mean(), hits_caught=s.hit.sum() / nh,
                                 onset_n=int((~s.neg).sum()), onset_hit=s[~s.neg].hit.mean() if (~s.neg).any() else np.nan))
        pk = pd.DataFrame(log["picks"]).merge(F[["sym", "hit", "mag", "neg"]], on="sym", how="left"); pk["date"] = d; cal.append(pk)
    if not rows: print("no runs"); return
    R = pd.DataFrame(rows); C = pd.concat(cal)
    out = [f"# Scorecard: tag={a.tag}, set={a.set}, dates={R.date.nunique()}\n"]
    t = R.pivot_table(index=["N", "method"], values=["depth", "hit_rate", "hits_caught", "onset_n", "onset_hit"], aggfunc="mean").round(3)
    out.append("## Mean over dates\n" + t.to_markdown() + "\n")
    W = R[R.N == 40].pivot(index="date", columns="method", values="depth")
    out.append("## Per date, top-40 depth share\n" + W.round(3).to_markdown() + "\n")
    out.append("## Paired comparison (top-40 depth share)\n")
    for b in ("chronic_rule", "m7_rank"):
        dlt = W.agent - W[b]; bs = [dlt.sample(len(dlt), replace=True, random_state=i).mean() for i in range(2000)]
        out.append(f"- agent vs {b}: mean {dlt.mean():+.3f}, wins {(dlt > .01).sum()} / ties {(dlt.abs() <= .01).sum()} / losses {(dlt < -.01).sum()}, bootstrap 90% CI [{np.percentile(bs, 5):+.3f}, {np.percentile(bs, 95):+.3f}]")
    C["bin"] = pd.cut(C.p_hit, [0, .1, .2, .35, .5, .7, 1.0001], include_lowest=True)
    cb = C.groupby("bin", observed=True).agg(n=("hit", "size"), predicted=("p_hit", "mean"), actual=("hit", "mean")).round(3)
    out.append("\n## Calibration\n" + cb.to_markdown() + f"\nBrier {((C.p_hit - C.hit.astype(float)) ** 2).mean():.4f}\n")
    txt = "\n".join(out); print(txt); (run_dir / f"SCORE_{a.set}.md").write_text(txt); R.to_csv(run_dir / f"scores_{a.set}.csv", index=False)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["run", "score"]); ap.add_argument("--tag", required=True)
    ap.add_argument("--set", default="dev", choices=list(SETS)); ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--mode", default="scratch", choices=["scratch", "swap", "onset"]); ap.add_argument("--model", default="gpt-6-astra"); a = ap.parse_args()
    cmd_run(a) if a.cmd == "run" else cmd_score(a)
