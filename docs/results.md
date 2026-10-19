# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-16 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-16 | 1,201 | 3,791 | 3,715 | 47,027 |
| AMD | 2020-01-06 | 2026-10-16 | 1,198 | 3,785 | 3,708 | 47,069 |
| AMZN | 2020-01-06 | 2026-10-16 | 1,197 | 3,780 | 3,704 | 46,718 |
| DIA | 2020-01-06 | 2026-10-16 | 1,199 | 3,797 | 3,704 | 46,474 |
| GOOGL | 2020-01-06 | 2026-10-16 | 1,192 | 3,766 | 3,690 | 46,584 |
| META | 2022-07-01 | 2026-10-16 | 832 | 2,684 | 2,607 | 32,856 |
| MSFT | 2020-01-06 | 2026-10-16 | 1,187 | 3,746 | 3,670 | 46,329 |
| NVDA | 2020-01-06 | 2026-10-16 | 1,196 | 3,769 | 3,697 | 46,204 |
| SPY | 2020-01-06 | 2026-10-16 | 1,189 | 3,793 | 3,706 | 45,979 |
| TSLA | 2021-01-04 | 2026-10-16 | 1,047 | 3,323 | 3,247 | 41,049 |
| XLF | 2020-01-06 | 2026-10-16 | 1,189 | 3,766 | 3,689 | 46,675 |

In total: 1,831,506 quotes on 524,421 contracts, in 40,000 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 38,902 | 97.3% | enters the calibration sample |
| `unsettled` | 863 | 2.2% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1264 | 0.1288 | +0.0024 |
| Log loss (nats) | 0.3911 | 0.3952 | +0.0041 |
| Expected calibration error | 0.0356 | 0.0160 | -0.0196 |

Brier change +0.0024 (95% cluster-bootstrap interval -0.0007 to +0.0064, resampling expiration dates; negative means calibration helped) over 445,431 predictions, 34,988 snapshots and 879 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 141,452 | 0.1016 | 0.1040 | 0.0205 | 0.0208 |
| 21-35d | 141,677 | 0.1270 | 0.1300 | 0.0333 | 0.0206 |
| 36-50d | 83,513 | 0.1482 | 0.1497 | 0.0485 | 0.0148 |
| >50d | 78,789 | 0.1468 | 0.1490 | 0.0541 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,041 | 0.1197 | 0.1208 | 0.0417 | 0.0179 |
| AMD | 41,643 | 0.1802 | 0.1842 | 0.0437 | 0.0389 |
| AMZN | 41,356 | 0.1356 | 0.1405 | 0.0289 | 0.0270 |
| DIA | 41,079 | 0.0630 | 0.0634 | 0.0266 | 0.0154 |
| GOOGL | 41,304 | 0.1301 | 0.1293 | 0.0572 | 0.0126 |
| META | 32,856 | 0.1521 | 0.1538 | 0.0488 | 0.0177 |
| MSFT | 41,221 | 0.1192 | 0.1230 | 0.0208 | 0.0277 |
| NVDA | 40,800 | 0.1571 | 0.1561 | 0.0810 | 0.0181 |
| SPY | 40,694 | 0.0691 | 0.0698 | 0.0283 | 0.0093 |
| TSLA | 41,049 | 0.1827 | 0.1928 | 0.0077 | 0.0668 |
| XLF | 41,388 | 0.0861 | 0.0876 | 0.0218 | 0.0215 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 93,838 | 0.1257 | 0.1247 | 0.0346 | 0.0156 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 135,022 | 0.0363 | 0.0179 | 165,820 | 0.0318 | 0.0386 |
| 0.1-0.2 | 55,416 | 0.1469 | 0.1105 | 61,611 | 0.1480 | 0.1904 |
| 0.2-0.3 | 39,969 | 0.2472 | 0.2058 | 38,914 | 0.2567 | 0.2797 |
| 0.3-0.4 | 32,571 | 0.3501 | 0.2953 | 30,109 | 0.3605 | 0.4019 |
| 0.4-0.5 | 35,144 | 0.4517 | 0.4030 | 24,673 | 0.4464 | 0.4674 |
| 0.5-0.6 | 27,224 | 0.5529 | 0.4973 | 28,096 | 0.5472 | 0.5645 |
| 0.6-0.7 | 32,752 | 0.6504 | 0.5932 | 31,870 | 0.6544 | 0.6557 |
| 0.7-0.8 | 30,408 | 0.7481 | 0.6881 | 20,770 | 0.7503 | 0.7499 |
| 0.8-0.9 | 24,617 | 0.8482 | 0.8157 | 16,411 | 0.8509 | 0.8624 |
| 0.9-1.0 | 32,308 | 0.9619 | 0.9559 | 27,157 | 0.9674 | 0.9673 |

## Top put credit spreads (2026-10-16)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | XLF | 2026-10-16 | 2026-11-13 | 28 | 55/54.5 | 0.30 | 0.04 | 60.8% | 54.4% | 56.47% | 34139.2% |
| 2 | GOOGL | 2026-10-16 | 2026-10-30 | 14 | 340/337.5 | 1.17 | 0.09 | 61.3% | 56.7% | 16.97% | 5860.0% |
| 3 | GOOGL | 2026-10-16 | 2026-10-30 | 14 | 340/335 | 2.20 | 1.34 | 63.2% | 57.5% | 14.46% | 3279.1% |
| 4 | AMD | 2026-10-16 | 2026-10-30 | 14 | 520/515 | 1.70 | 1.05 | 74.3% | 65.9% | 13.32% | 2505.1% |
| 5 | AMZN | 2026-10-16 | 2026-10-30 | 14 | 247.5/245 | 0.95 | 0.60 | 70.0% | 61.6% | 13.32% | 2502.5% |
| 6 | AMD | 2026-10-16 | 2026-10-30 | 14 | 525/515 | 3.40 | 2.75 | 74.3% | 65.9% | 11.99% | 1816.8% |
| 7 | AMZN | 2026-10-16 | 2026-10-30 | 14 | 247.5/242.5 | 1.78 | 1.45 | 70.8% | 63.0% | 11.80% | 1731.5% |
| 8 | AAPL | 2026-10-16 | 2026-10-30 | 14 | 342.5/340 | 1.00 | 0.60 | 64.1% | 59.3% | 11.80% | 1731.5% |
| 9 | AAPL | 2026-10-16 | 2026-10-30 | 14 | 342.5/337.5 | 1.85 | 1.40 | 70.0% | 61.4% | 11.29% | 1525.0% |
| 10 | GOOGL | 2026-10-16 | 2026-10-30 | 14 | 340/330 | 3.79 | 3.04 | 64.1% | 59.0% | 11.12% | 1463.9% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,459 eligible spreads of the latest session the median annualised return is 1.3% under the risk-neutral CDF and 62.9% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.5 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.2%, right tail uncovered 15.2%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
