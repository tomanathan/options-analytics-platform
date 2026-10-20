# Growth lab: regime-conditional calibration and growth-optimal single options

Status: specification for the `feat/growth-lab` branch. Written against `main` at `7f22370`.

## Question

For every call and put the market quotes, is it priced wrong for the current regime, and if a trader bought it, what fraction of capital maximises compounded growth? The study measures this with the same walk-forward, dev/hold-out protocol as the entry-rule backtest and the rule lab, and publishes the answer as a report whether it is positive or negative. Nothing here advises a trade.

Three steps, each a script with a document, each gated by the previous one's result:

1. **Regime-conditional calibration.** Does a calibration map fitted per regime beat the single map out of sample?
2. **Single-option scoring.** Under the better map, the calibrated expected payoff of every usable long call and put at the natural fill, its edge as a share of the premium, and its growth-optimal fraction and growth rate.
3. **Growth backtest.** Rules that pick the top options by growth rate each session, sized by that fraction, held to expiry, measured on dev years and reported on the hold-out.

## Step 1: `src/oap/analytics/regime_calibration.py`, `scripts/regime_calibration.py`

Regime of an (underlying, trade date), from the rule lab's `regime_features` (do not re-derive them; import `oap.analytics.rulelab` as it is and do not edit it):

| feature | buckets |
| --- | --- |
| `iv_rank_120` | `low` (< 1/3), `mid`, `high` (>= 2/3); `unknown` when nan |
| `ret_20` | `down` (<= 0), `up` (> 0); `unknown` when nan |

A regime is the pair, six named regimes plus the unknowns. `regime_of(features) -> pd.Series` of labels; `attach_regime(predictions, features)` joins by underlying and trade date.

Maps: `walk_forward_regime_maps(predictions, features, config)` fits, per fold year and per regime, an isotonic map on the training rows of that regime (the fold's `training_mask` is reused), with the existing `min_fit_samples` rule; a regime below it in a fold uses the pooled fold map (record which). `apply_regime_maps` applies each row's regime map. Everything is `FittedMap`-shaped so `maps_to_frame`/`maps_from_frame` round-trip with a `regime` column added.

Evaluation: out-of-sample 2021 onward, pooled map against regime maps, for Brier score, log loss and ECE, with the existing cluster bootstrap over expiration dates on the paired difference (regime minus pooled), overall and per regime, per DTE bucket and per year. The reliability diagram for both variants.

Decision rule, applied by the script and written into the report: the regime maps win when the overall out-of-sample Brier difference is negative and its 95% interval excludes zero. Otherwise the pooled map is used downstream and the report says so in its first paragraph.

Output: `docs/regime-calibration.md` with the difference table, the per-regime table (sample sizes, which folds fell back), the diagram `docs/img/regime_calibration.png`, the decision, and caveats (fewer samples per bucket; the regime is known at the close of the trade date; the IV rank needs 120 sessions of history so 2020 is thin).

## Step 2: `src/oap/analytics/growth.py` (pure), `scripts/growth_lab.py --score`

For every `ok` snapshot from 2021-01-04 on, every expiration with a curve and at least `min_dte_days`, every usable call and put whose strike lies inside the CDF knots and whose ask is positive: a `Position` of kind `long_call` or `long_put` with one leg filled at the ask (reuse `oap.engine.positions` and the tail completion exactly as the structures API does, with `tail_sigmas` from `oap.analytics.views`), under the map chosen in step 1 (walk-forward: the map of the trade date's year and regime).

Per option, with `R = payoff / ask - 1` the return on premium at expiry:

- `prob_profit = P(R > 0)`.
- `expected_return = E[R]` (the calibrated expected payoff over the ask, minus one); `edge_pct` is the same number, and it is negative when the option is expensive.
- `return_std` from the second moment.
- `kelly_fraction` f* in `[0, f_max]` and `growth_rate` g* = max over f of `E[log(1 + f R)]`: evaluate `E[log(1 + f R)]` exactly enough by integrating over the distribution's segments (the payoff is affine on each knot interval and in each tail; integrate `log(1 + f R(s))` with Gauss-Legendre of order 8 per segment, the tails on a transformed grid out to the 99.99% quantile, and check against a 20,000-point Monte Carlo in the tests) and maximise with golden-section search on `[0, f_max]`, `f_max = 0.25`. `R >= -1` always holds for a long option, so the log is defined for `f <= 1`. g* is 0 when f* is 0 (the option is not worth buying at any size).
- `growth_rate_market`: the same g* under the raw risk-neutral distribution, so the gap between the two is the regime-calibrated mispricing in growth terms.
- `tail_share` as in the structures engine; `regime`; `dte_days`; `moneyness`; `right`; `ask`, `bid`, `mid`; `settlement_close` and the realised `R` from `fct_expiration_outcome`.

Cache: `.dbt-local/growth-lab/scored_options.parquet` (about 2021–2026 × 1,000 sessions × 11 underlyings × expirations × strikes; expect a few million rows, so write per-year parquet parts and read them lazily). Score in one pass per session like the rule lab; keep the wall time under 15 minutes on the M1 Air (vectorise: score every strike of one expiration against one distribution at once; the growth maximisation is the expensive part, so evaluate g on a shared grid of 64 fractions per option in numpy and refine the best cell with golden section only for options whose coarse maximum is positive).

## Step 3: `scripts/growth_lab.py --sweep`

Rules, a grid like the rule lab's: ranking (`growth_rate`, `growth_gap` = calibrated minus market g*, `expected_return`), right (`call`, `put`, `both`), DTE band (`any`, 7–21, 21–45, 45–70), moneyness band of the strike over the close (`any`, 0.90–0.97, 0.97–1.03, 1.03–1.10), regime gate (`any`, `calm`, `trend_up`, `high_iv_rank`, `low_iv_rank`), one per underlying and expiry or all, minimum `prob_profit` (0, 0.25, 0.4), top N per session (3, 5, 10), and two sizings: equal weight (one dollar of premium per session split across picks) and Kelly (each pick gets f* of the session's equity, capped so the session's total is at most `f_max`, measured as growth of a one-dollar equity line). A rule is skipped when it would select fewer than 400 dev trades.

Per rule and period (dev 2021–2024, hold-out 2025–2026): trades, win rate, mean R, mean predicted probability of profit against the realised win rate, mean growth per session of the equity line (the headline), total growth, max drawdown, Sharpe per session, and the 95% cluster bootstrap interval on mean R by expiration date. Ranked on dev by growth per session; reported on the hold-out. Picks: best growth, and best growth among rules with a hold-out drawdown under the median. Baselines: equal-weight random eligible option (seeded), and the pooled-map version of each pick when the regime maps were chosen, so the regime's contribution is visible. Multiple-comparison sanity counts as in the rule lab.

Output: `docs/growth-lab.md` (headline table, top 10 dev rules with hold-out columns, the baselines, the regime-contribution rows, protocol, caveats including that long premium loses on average, that the tails drive singles and `tail_share` is reported, that fills are at the ask with no commissions, that settlement is at expiry with no early management, and that the hold-out is short) and `docs/img/growth_lab_holdout.png` (hold-out equity of the picks and the baseline, log scale).

## Ownership and rules

Branch `feat/growth-lab` from `origin/main`. New files only, plus links from `README.md` (one sentence under the backtest paragraph) and `CLAUDE.md` (scripts and docs lines) in a final separate commit. Do not edit `src/oap/analytics/scoring.py`, `src/oap/analytics/rulelab.py`, `scripts/make_report.py`, `scripts/rule_lab.py`, `scripts/backtest_entry_rule.py` or `apps/web/**`: another branch is changing them. Import what you need from them as they are on `main`.

The real gold file is `/Users/mackbook/Documents/options-analytics-platform/.dbt-local/oap.duckdb`: open it read-only only (the explorer serves it); never write to it. The rule lab's regime cache at `/Users/mackbook/Documents/options-analytics-platform/.dbt-local/rule-lab/regime.parquet` may be copied into your worktree's `.dbt-local/rule-lab/` and read.

Tests at the mirrored paths: regime labelling, fallback to the pooled map, the paired-difference bootstrap, the growth integrand against Monte Carlo, f* = 0 for an option priced above its calibrated value, g* monotone in the edge, selection equivalence with a slow per-row implementation (hypothesis), and the scripts end to end on a tiny gold schema (reuse `tests/scripts/test_rule_lab.py`'s fixture approach). `make check` green before each commit. Push the branch; no PR; no merge.

Report: commits; test counts; the step-1 decision with its numbers; step-2 runtime and row counts and the distribution of `expected_return` and `growth_rate` (what share of options have g* > 0, by right and regime); the step-3 headline table verbatim; deviations and judgement calls.
