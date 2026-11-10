# Holdout protocol (written 2026-11-09, before any holdout agent run)

Primary configuration ("final"): the full-list agent.
- `mode=scratch`, prompt `prompts/system.md`, 40 picks, model `gpt-6-astra`, current tool set (tools.py incl. coin_hourly / past_onsets / quiet_board).
- Code frozen in `frozen/final/` (SHA256SUMS lists the hashes); every run log carries `code_hash`.
- Primary metric: top-40 share of all next-week negative-funding depth, paired against the chronic rule (bootstrap 90% CI, win/tie/loss).

Procedure:
1. Run `final` on the dev set (13 dates) with the current code (dev numbers for this exact configuration).
2. Run `final` once on the holdout set (2026-07-06 .. 2026-10-12, 15 weekly dates). No change to prompts, tools or data after seeing holdout results; the result is reported as-is.

Not carried to holdout: the onset-only agent (v2/v3). On dev it did not beat the simple repeat-offender sort, and a trained GBM on the same features did not beat it on holdout either; documented as a finding in README.
