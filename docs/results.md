# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of no spread scores yet.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-30 | 1,211 | 3,831 | 3,734 | 47,274 |
| AMD | 2020-01-06 | 2026-10-30 | 1,208 | 3,825 | 3,728 | 47,319 |
| AMZN | 2020-01-06 | 2026-10-30 | 1,207 | 3,820 | 3,723 | 46,965 |
| DIA | 2020-01-06 | 2026-10-30 | 1,209 | 3,837 | 3,721 | 46,688 |
| GOOGL | 2020-01-06 | 2026-10-30 | 1,202 | 3,806 | 3,708 | 46,817 |
| META | 2022-07-01 | 2026-10-30 | 842 | 2,724 | 2,627 | 33,101 |
| MSFT | 2020-01-06 | 2026-10-30 | 1,197 | 3,786 | 3,689 | 46,571 |
| NVDA | 2020-01-06 | 2026-10-30 | 1,206 | 3,809 | 3,714 | 46,425 |
| SPY | 2020-01-06 | 2026-10-30 | 1,199 | 3,833 | 3,722 | 46,187 |
| TSLA | 2021-01-04 | 2026-10-30 | 1,057 | 3,363 | 3,266 | 41,293 |
| XLF | 2020-01-06 | 2026-10-30 | 1,199 | 3,806 | 3,709 | 46,930 |

In total: 1,852,845 quotes on 530,247 contracts, in 40,440 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,106 | 96.7% | enters the calibration sample |
| `unsettled` | 1,055 | 2.6% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 59 | 0.1% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1263 | 0.1288 | +0.0025 |
| Log loss (nats) | 0.3908 | 0.3951 | +0.0042 |
| Expected calibration error | 0.0350 | 0.0165 | -0.0186 |

Brier change +0.0025 (95% cluster-bootstrap interval -0.0006 to +0.0055, resampling expiration dates; negative means calibration helped) over 448,037 predictions, 35,192 snapshots and 883 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 142,414 | 0.1017 | 0.1042 | 0.0195 | 0.0216 |
| 21-35d | 142,379 | 0.1269 | 0.1300 | 0.0326 | 0.0211 |
| 36-50d | 84,455 | 0.1477 | 0.1492 | 0.0482 | 0.0141 |
| >50d | 78,789 | 0.1468 | 0.1490 | 0.0541 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,288 | 0.1195 | 0.1204 | 0.0422 | 0.0173 |
| AMD | 41,893 | 0.1806 | 0.1847 | 0.0423 | 0.0395 |
| AMZN | 41,603 | 0.1352 | 0.1402 | 0.0285 | 0.0272 |
| DIA | 41,293 | 0.0628 | 0.0632 | 0.0265 | 0.0155 |
| GOOGL | 41,537 | 0.1302 | 0.1296 | 0.0556 | 0.0124 |
| META | 33,101 | 0.1526 | 0.1545 | 0.0466 | 0.0176 |
| MSFT | 41,463 | 0.1190 | 0.1227 | 0.0211 | 0.0273 |
| NVDA | 41,021 | 0.1570 | 0.1562 | 0.0794 | 0.0172 |
| SPY | 40,902 | 0.0689 | 0.0697 | 0.0280 | 0.0096 |
| TSLA | 41,293 | 0.1822 | 0.1922 | 0.0076 | 0.0663 |
| XLF | 41,643 | 0.0858 | 0.0874 | 0.0219 | 0.0215 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 96,444 | 0.1253 | 0.1246 | 0.0320 | 0.0169 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 135,962 | 0.0363 | 0.0181 | 166,848 | 0.0317 | 0.0386 |
| 0.1-0.2 | 55,688 | 0.1469 | 0.1109 | 61,935 | 0.1480 | 0.1907 |
| 0.2-0.3 | 40,146 | 0.2472 | 0.2062 | 39,101 | 0.2567 | 0.2803 |
| 0.3-0.4 | 32,746 | 0.3501 | 0.2960 | 30,281 | 0.3605 | 0.4023 |
| 0.4-0.5 | 35,314 | 0.4517 | 0.4034 | 24,791 | 0.4464 | 0.4686 |
| 0.5-0.6 | 27,357 | 0.5529 | 0.4983 | 28,253 | 0.5472 | 0.5657 |
| 0.6-0.7 | 32,925 | 0.6504 | 0.5945 | 32,080 | 0.6544 | 0.6572 |
| 0.7-0.8 | 30,602 | 0.7481 | 0.6893 | 20,895 | 0.7503 | 0.7513 |
| 0.8-0.9 | 24,786 | 0.8482 | 0.8169 | 16,512 | 0.8509 | 0.8631 |
| 0.9-1.0 | 32,511 | 0.9619 | 0.9561 | 27,341 | 0.9673 | 0.9676 |

## Top 10 to enter (no session)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

No spread passes the entry guards on the latest session.

## Which structure serves each outcome (2026-10-30)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | none | n/a | n/a | n/a | n/a | n/a | n/a |
| AMD | none | n/a | n/a | n/a | n/a | n/a | n/a |
| AMZN | none | n/a | n/a | n/a | n/a | n/a | n/a |
| DIA | none | n/a | n/a | n/a | n/a | n/a | n/a |
| GOOGL | none | n/a | n/a | n/a | n/a | n/a | n/a |
| META | none | n/a | n/a | n/a | n/a | n/a | n/a |
| MSFT | none | n/a | n/a | n/a | n/a | n/a | n/a |
| NVDA | none | n/a | n/a | n/a | n/a | n/a | n/a |
| SPY | none | n/a | n/a | n/a | n/a | n/a | n/a |
| TSLA | none | n/a | n/a | n/a | n/a | n/a | n/a |
| XLF | none | n/a | n/a | n/a | n/a | n/a | n/a |

Unavailable: AAPL (no_distribution: no expiration with at least 7 days to expiry has a distribution); AMD (no_distribution: no expiration with at least 7 days to expiry has a distribution); AMZN (no_distribution: no expiration with at least 7 days to expiry has a distribution); DIA (no_distribution: no expiration with at least 7 days to expiry has a distribution); GOOGL (no_distribution: no expiration with at least 7 days to expiry has a distribution); META (no_distribution: no expiration with at least 7 days to expiry has a distribution); MSFT (no_distribution: no expiration with at least 7 days to expiry has a distribution); NVDA (no_distribution: no expiration with at least 7 days to expiry has a distribution); SPY (no_distribution: no expiration with at least 7 days to expiry has a distribution); TSLA (no_distribution: no expiration with at least 7 days to expiry has a distribution); XLF (no_distribution: no expiration with at least 7 days to expiry has a distribution).

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (no session)

No spread is eligible on the latest session.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (no session)

No spread passes the edge guards on the latest session.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.6 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.2%, right tail uncovered 15.2%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
