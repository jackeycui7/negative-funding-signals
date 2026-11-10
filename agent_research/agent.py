"""Negative-funding research agent: one decision date -> ranked borrow list.

  python3 agent.py 2026-08-17 [--model gpt-6-astra] [--mode scratch|swap] [--out runs/x]

Model access: any OpenAI-compatible chat/completions endpoint with tool calling.
Config from env: LLM_API_KEY, LLM_BASE (default http://127.0.0.1:8317/v1).
"""
import json, os, sys, time, argparse, hashlib, urllib.request, urllib.error
from pathlib import Path
import pandas as pd
A = Path(__file__).resolve().parent
sys.path.insert(0, str(A))
from tools import Tools, TOOL_SPECS

def _key():
    k = os.environ.get("LLM_API_KEY")
    if not k: raise RuntimeError("set LLM_API_KEY (and LLM_BASE) for an OpenAI-compatible chat/completions endpoint")
    return k

BASE = os.environ.get("LLM_BASE", "http://127.0.0.1:8317/v1")

def chat(model, messages, tools, retries=5):
    body = json.dumps({"model": model, "messages": messages, "tools": tools}).encode()
    for i in range(retries):
        try:
            r = urllib.request.Request(BASE + "/chat/completions", data=body, headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(r, timeout=300))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if i == retries - 1: raise
            time.sleep([5, 15, 30, 60, 90][i])

PROMPTS = {"scratch": "system.md", "swap": "system.md", "onset": "onset.md"}

def task_text(as_of, mode, n, chronic):
    w0 = (pd.Timestamp(as_of) + pd.Timedelta(days=3)).date(); w1 = (pd.Timestamp(as_of) + pd.Timedelta(days=10)).date()
    if mode == "onset":
        return (f"Decision time: {as_of} 00:00 UTC. Spot borrowed now becomes sellable 3 days later, so the target window is [{w0}, {w1}) UTC.\n"
                f"Goal: a ranked list of exactly {n} QUIET Binance USDT-perp coins (quiet__eq true) most likely to START deeply negative funding in that window "
                "(hit = any settled 8h-equivalent print below -0.10%), ranked by probability x expected depth.\n"
                "Use the tools thoroughly, then call submit_list once. p_hit must be calibrated probabilities for the hit definition.")
    t = (f"Decision time: {as_of} 00:00 UTC. Spot borrowed now becomes sellable 3 days later, so the target window is [{w0}, {w1}) UTC.\n"
         f"Goal: a ranked list of exactly {n} Binance USDT-perp coins most likely to have deeply negative funding in that window "
         f"(hit = any settled 8h-equivalent print below -0.10%), ranked by expected value = probability x expected depth.\n")
    if mode == "swap":
        t += (f"Start from this mechanical baseline list (already-negative coins by 7d mean, then chronic offenders):\n{', '.join(chronic)}\n"
              "Keep what you agree with; replace coins only where your research says another coin is clearly better. Your final list is still exactly "
              f"{n} coins, ranked.\n")
    t += "Use the tools, then call submit_list once. p_hit must be calibrated probabilities for the hit definition."
    return t

def run(as_of, model="gpt-6-astra", mode="scratch", n=None, max_turns=None, out=None):
    n = n or (15 if mode == "onset" else 40); max_turns = max_turns or (60 if mode == "onset" else 24)
    T = Tools(as_of); chronic = T.chronic_rule(40)
    quiet = set(T.screen[T.screen.quiet].sym)
    msgs = [{"role": "system", "content": (A / "prompts" / PROMPTS[mode]).read_text()}, {"role": "user", "content": task_text(as_of, mode, n, chronic)}]
    code_hash = hashlib.sha256(b"".join((A / f).read_bytes() for f in ("agent.py", "tools.py", "prompts/" + PROMPTS[mode], "data/features.parquet"))).hexdigest()[:12]
    log = {"as_of": as_of, "model": model, "mode": mode, "code_hash": code_hash, "turns": [], "usage": {"prompt": 0, "completion": 0}}
    picks = None; t0 = time.time()
    for turn in range(max_turns):
        r = chat(model, msgs, TOOL_SPECS)
        u = r.get("usage") or {}; log["usage"]["prompt"] += u.get("prompt_tokens", 0); log["usage"]["completion"] += u.get("completion_tokens", 0)
        m = r["choices"][0]["message"]; msgs.append({k: v for k, v in m.items() if k in ("role", "content", "tool_calls")})
        calls = m.get("tool_calls") or []
        log["turns"].append({"content": (m.get("content") or "")[:2000], "calls": [c["function"]["name"] + " " + c["function"]["arguments"][:300] for c in calls]})
        if not calls:
            msgs.append({"role": "user", "content": "Please continue and finish by calling submit_list."}); continue
        for c in calls:
            name = c["function"]["name"]
            try: args = json.loads(c["function"]["arguments"] or "{}")
            except json.JSONDecodeError: args = {}
            if name == "submit_list":
                pk = args.get("picks", []); bad = [p.get("sym") for p in pk if mode == "onset" and p.get("sym") not in quiet]
                q_pages = max(1, -(-len(quiet) // 70)); unseen = q_pages - len(getattr(T, "board_seen", set())) if mode == "onset" else 0
                if unseen > 0 and log.get("rejected_submits", 0) < 2:
                    res = json.dumps({"ok": False, "error": f"you have not read all quiet_board pages yet ({unseen} unread). Review the whole quiet universe first, then resubmit."})
                    log["rejected_submits"] = log.get("rejected_submits", 0) + 1
                elif bad or len(pk) < n:
                    res = json.dumps({"ok": False, "error": f"need exactly {n} picks, all quiet coins; not quiet or unknown: {bad}; got {len(pk)}. Fix and call submit_list again."})
                    log["rejected_submits"] = log.get("rejected_submits", 0) + 1
                    if log["rejected_submits"] >= 3: picks = [p for p in pk if p.get("sym") not in bad]
                else: picks = pk[:n]; res = json.dumps({"ok": True, "n": len(picks)})
            elif name in ("market_screen", "coin_detail", "announcements", "base_rates", "coin_hourly", "past_onsets", "quiet_board"):
                try: res = getattr(T, name)(**args)
                except TypeError as e: res = json.dumps({"error": str(e)})
            else: res = json.dumps({"error": f"unknown tool {name}"})
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": res})
        if picks is not None: break
    log["seconds"] = round(time.time() - t0, 1); log["picks"] = picks; log["chronic_rule"] = chronic
    if out:
        Path(out).mkdir(parents=True, exist_ok=True); (Path(out) / f"{as_of}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
    return log

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("as_of"); ap.add_argument("--model", default="gpt-6-astra"); ap.add_argument("--mode", default="scratch")
    ap.add_argument("--n", type=int, default=None); ap.add_argument("--out", default=str(A / "runs" / "manual")); a = ap.parse_args()
    L = run(a.as_of, a.model, a.mode, a.n, out=a.out)
    print(f"{a.as_of}: {len(L['picks'] or [])} picks, {len(L['turns'])} turns, {L['seconds']}s, tokens {L['usage']}")
