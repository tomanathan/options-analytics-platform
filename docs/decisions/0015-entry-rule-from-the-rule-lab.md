# 0015. The Top 10 to enter uses the rule that held up on the rule lab hold-out

Status: Accepted (Phase 3)
Date: 2026-10-20

## Context

The "Top 10 to enter" ranking (`rank_entry`, ADR 0013) took every spread that passes the entry guards and ordered it by annualised return on max loss at the mid credit, at any days to expiry and any moneyness. The one-time backtest of that rule (`docs/backtest-entry-rule.md`, run on 2026-10-19) lost money out of sample: 10,458 trades from 2021 to 2026 won 64.1% against 73.0% predicted and returned -2.04% on capital at risk.

The rule lab (`docs/rule-lab.md`) scored every eligible spread of every session once with the walk-forward map of its year, swept 1,600 selection rules, ranked them on 2021-2024 by Sharpe per trade and reported them on a 2025-2026 hold-out that no choice looked at. The best dev rule, `ps-d45_70-m95_100-all-calm-e0-n10`, needs a regime feature (the five-session change of the near-the-money IV); the second, `ps-d45_70-m95_100-all-any-e0-n10`, is the same rule without it. On the hold-out the second made 4,053 trades, won 73.0% against 74.9% predicted, returned +7.53% per trade (95% interval -7.29% to +21.10%) and +3.02% on capital at risk, with a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss. The old rule, on the same hold-out, returned -1.83% per trade and -2.07% on capital at risk.

## Decision

From 2026-10-20 `rank_entry` follows `ps-d45_70-m95_100-all-any-e0-n10`: every entry guard, then 45 to 69 days to expiry and a short strike from 95% to below 100% of the close, ordered by `score_entry`, the annualised two-outcome return at the natural credit with the calibrated probability of profit shrunk halfway toward the price-implied one (`q = 0.5 p + 0.5 pop_implied`, `b = c_n / (W - c_n)`, score `annualise(q b - (1 - q), years)`). Ties break by the old order (annualised return at the mid, then reward to risk). The bands and the ranking are `AnalyticsConfig` fields (`entry_dte_band`, `entry_moneyness_band`, `entry_rank`).

- One implementation. The rankings live in `oap.analytics.ranking`, which both `oap.analytics.scoring` and the rule lab import; the guard (`entry_guard`) and the tie-break (`entry_tiebreak`) live in `scoring` and the lab uses them. A test scores synthetic sessions and checks that `rank_entry` reproduces the lab's selection of the same rule for several top-N.
- The lab no longer reads `rank_entry`. It used `rank_entry` as the guard and the tie-break; now that `rank_entry` carries the bands, the lab computes both from the scored columns, so a rule's candidates do not depend on the live rule. On the existing score cache the sweep reproduces the previous `sweep.csv` to 1e-12 for all 1,600 rules.
- The lab's baseline is the live rule (`live_rule(DEFAULT_CONFIG)`), and the previous rule is reported next to it.
- The rule without the regime gate was chosen over the best dev rule because the product ranks one session at a time from gold and has no regime feature there; the two differ by 0.008 in dev Sharpe and by 0.006 in hold-out Sharpe, in favour of the ungated rule on the hold-out.
- The product states the rule (`ENTRY_RULE`) and its hold-out evidence (`ENTRY_EVIDENCE`, one sentence with the date measured and a pointer to `docs/rule-lab.md`); the API returns both and the Spreads tab and the report print both.

## Consequences

- The backtest of the product's rule changes with it. Re-run on 2026-10-20 over 2021-2026, `entry_top10` made 9,842 out-of-sample trades in 991 of 1,047 sessions, won 76.2% (70.2% to 82.0%) against 77.5% predicted, with a mean realised return of +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, and 15.6% of trades at the maximum loss. The per-trade mean and the dollar total disagree because the total weights each trade by its maximum loss in dollars, so the large-dollar losses dominate it: AMZN returned -24.4% on capital at risk and GOOGL -13.0% (against a +12.0% mean per trade), and the year 2022 -36.3%. The hold-out figures in `ENTRY_EVIDENCE` are the ones no choice looked at; the full-period total is the warning that the dollar result depends on position sizing.
- Some sessions have no spread in the bands, so the Top 10 can be shorter than ten or empty (56 of 1,047 historical sessions had none).
- `spread_scores` gains `score_entry`. A gold file built before the change has no such column, so the API answers `503 gold_missing` on the spread routes until a nightly run built from the new code is pulled; the runbook says so.
- The rule was chosen out of 1,600 on the same history, with one hold-out of under two years, and the hold-out interval of the mean includes zero. It is a measured selection rule, not trade advice, and it needs measuring again as the hold-out grows.
