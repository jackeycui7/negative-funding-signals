# Onset scorecard: tag=v2_onset, set=dev, dates=13

Universe: quiet coins only (min7 >= -0.1 and r_pred8 >= -0.1 at decision time). quiet_depth = share of all quiet-coin depth in the window captured by the top-K.

## Mean over dates
|                       |   hit_rate |   hits_caught |   quiet_depth |
|:----------------------|-----------:|--------------:|--------------:|
| (5, 'agent')          |      0.338 |         0.056 |         0.034 |
| (5, 'chronic_quiet')  |      0.292 |         0.049 |         0.062 |
| (5, 'oracle')         |      1     |         0.185 |         0.75  |
| (5, 'random')         |      0.118 |         0.02  |         0.022 |
| (5, 'warm_score')     |      0.385 |         0.07  |         0.052 |
| (10, 'agent')         |      0.377 |         0.126 |         0.128 |
| (10, 'chronic_quiet') |      0.315 |         0.105 |         0.124 |
| (10, 'oracle')        |      1     |         0.371 |         0.91  |
| (10, 'random')        |      0.115 |         0.039 |         0.043 |
| (10, 'warm_score')    |      0.377 |         0.13  |         0.094 |
| (15, 'agent')         |      0.323 |         0.164 |         0.147 |
| (15, 'chronic_quiet') |      0.313 |         0.157 |         0.15  |
| (15, 'oracle')        |      1     |         0.556 |         0.965 |
| (15, 'random')        |      0.114 |         0.058 |         0.062 |
| (15, 'warm_score')    |      0.379 |         0.196 |         0.195 |

## Per date, top-10 quiet-depth share
| date       |   agent |   chronic_quiet |   oracle |   random |   warm_score |
|:-----------|--------:|----------------:|---------:|---------:|-------------:|
| 2026-01-05 |   0.036 |           0.035 |    0.891 |    0.046 |        0.076 |
| 2026-01-19 |   0.169 |           0.079 |    0.819 |    0.042 |        0.164 |
| 2026-02-02 |   0.313 |           0.204 |    0.986 |    0.061 |        0.308 |
| 2026-02-16 |   0.615 |           0.598 |    0.909 |    0.035 |        0.008 |
| 2026-03-02 |   0.03  |           0.016 |    0.924 |    0.054 |        0.036 |
| 2026-03-16 |   0.075 |           0.028 |    0.971 |    0.036 |        0.016 |
| 2026-03-30 |   0.059 |           0.058 |    0.828 |    0.035 |        0.16  |
| 2026-04-13 |   0.076 |           0.095 |    0.809 |    0.045 |        0.052 |
| 2026-04-27 |   0.007 |           0.026 |    0.943 |    0.041 |        0.007 |
| 2026-05-11 |   0.133 |           0.001 |    0.973 |    0.046 |        0.215 |
| 2026-05-25 |   0.087 |           0.02  |    0.97  |    0.032 |        0.097 |
| 2026-06-08 |   0.034 |           0.287 |    0.949 |    0.045 |        0.053 |
| 2026-06-22 |   0.033 |           0.165 |    0.864 |    0.047 |        0.033 |

## Paired (top-10 quiet-depth share)

- agent vs chronic_quiet: mean +0.004, wins 7 / ties 2 / losses 4, bootstrap 90% CI [-0.040, +0.047]
- agent vs warm_score: mean +0.034, wins 3 / ties 6 / losses 4, bootstrap 90% CI [-0.027, +0.125]
- agent vs random: mean +0.085, wins 8 / ties 0 / losses 5, bootstrap 90% CI [+0.021, +0.166]
- hit rate top-10: agent 0.377, chronic_quiet 0.315, warm 0.377, random 0.115

## Combined 40-coin list (share of ALL depth): negatives from the rule + K onset picks
|   K |   chronic40 |   negs_plus_agent |   negs_plus_warm |   quiet_share |   n_neg |
|----:|------------:|------------------:|-----------------:|--------------:|--------:|
|   5 |       0.505 |             0.501 |            0.509 |         0.428 |  67.615 |
|  10 |       0.505 |             0.525 |            0.511 |         0.428 |  67.615 |
- K=5, rule-negatives+agent vs chronic40: mean -0.004, wins 1 / ties 9 / losses 3, bootstrap 90% CI [-0.019, +0.012]
- K=10, rule-negatives+agent vs chronic40: mean +0.020, wins 6 / ties 3 / losses 4, bootstrap 90% CI [-0.012, +0.061]

## Calibration (onset picks)
| bin         |   n |   predicted |   actual |
|:------------|----:|------------:|---------:|
| (0.2, 0.35] |  76 |       0.312 |    0.224 |
| (0.35, 0.5] | 118 |       0.405 |    0.39  |
| (0.5, 0.7]  |   1 |       0.55  |    0     |
Brier 0.2123

## Top-5 quiet onsets per date and whether the agent had them

- 2026-01-05: BREVUSDT 11.7, HYPERUSDT 3.4, DASHUSDT 2.9, DOLOUSDT 2.2, IDUSDT 2.2
- 2026-01-19: ENSOUSDT 19.8, NOMUSDT 7.3, AUCTIONUSDT 7.2 (rank 10), ZKCUSDT 5.8, GUSDT 4.9
- 2026-02-02: ZILUSDT 8.3, API3USDT 4.8 (rank 8), SIGNUSDT 3.6, WCTUSDT 2.5 (rank 1), PROVEUSDT 1.6
- 2026-02-16: AWEUSDT 24.6 (rank 9), ORCAUSDT 15.2 (rank 6), YGGUSDT 4.6, INJUSDT 3.7, BIOUSDT 3.1
- 2026-03-02: KITEUSDT 12.1, PIXELUSDT 7.2, KAVAUSDT 4.0, HUMAUSDT 3.5, BABYUSDT 3.1
- 2026-03-16: ENJUSDT 10.0, ANKRUSDT 2.6, JTOUSDT 1.9, FFUSDT 0.9, KATUSDT 0.6 (rank 9)
- 2026-03-30: REDUSDT 16.8, KERNELUSDT 7.7 (rank 14), CTSIUSDT 3.8, SOLVUSDT 3.2, MMTUSDT 2.5
- 2026-04-13: SIGNUSDT 7.2, API3USDT 2.9, EDUUSDT 1.8, MOVEUSDT 1.6 (rank 6), ALICEUSDT 1.3
- 2026-04-27: KNCUSDT 4.1, HIVEUSDT 3.5, KAVAUSDT 0.7, MEGAUSDT 0.6, DOGSUSDT 0.6
- 2026-05-11: RONINUSDT 5.9, FIDAUSDT 5.0, SIGNUSDT 2.5 (rank 4), POLYXUSDT 2.4, EDENUSDT 0.9
- 2026-05-25: IDUSDT 15.5, PUNDIXUSDT 4.5, VTHOUSDT 4.0, GUNUSDT 2.9 (rank 8), PORTALUSDT 1.9
- 2026-06-08: SAHARAUSDT 6.7, ZKCUSDT 4.9, SPELLUSDT 3.0, ASTRUSDT 2.6, SOPHUSDT 2.1
- 2026-06-22: POWRUSDT 12.6, ONGUSDT 5.5, AGLDUSDT 3.3, ACTUSDT 2.9, GLMUSDT 2.2