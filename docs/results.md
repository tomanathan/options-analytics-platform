# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-02 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-02 | 1,191 | 3,755 | 3,675 | 46,507 |
| AMD | 2020-01-06 | 2026-10-02 | 1,188 | 3,748 | 3,668 | 46,558 |
| AMZN | 2020-01-06 | 2026-10-02 | 1,187 | 3,744 | 3,663 | 46,185 |
| DIA | 2020-01-06 | 2026-10-02 | 1,189 | 3,760 | 3,667 | 46,002 |
| GOOGL | 2020-01-06 | 2026-10-02 | 1,182 | 3,730 | 3,649 | 46,051 |
| META | 2022-07-01 | 2026-10-02 | 822 | 2,647 | 2,566 | 32,332 |
| MSFT | 2020-01-06 | 2026-10-02 | 1,177 | 3,710 | 3,629 | 45,804 |
| NVDA | 2020-01-06 | 2026-10-02 | 1,186 | 3,733 | 3,658 | 45,697 |
| SPY | 2020-01-06 | 2026-10-02 | 1,180 | 3,757 | 3,672 | 45,537 |
| TSLA | 2021-01-04 | 2026-10-02 | 1,037 | 3,287 | 3,205 | 40,506 |
| XLF | 2020-01-06 | 2026-10-02 | 1,179 | 3,729 | 3,650 | 46,173 |

In total: 1,811,734 quotes on 518,579 contracts, in 39,600 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 38,467 | 97.1% | enters the calibration sample |
| `unsettled` | 898 | 2.3% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1267 | 0.1293 | +0.0025 |
| Log loss (nats) | 0.3920 | 0.3964 | +0.0044 |
| Expected calibration error | 0.0352 | 0.0167 | -0.0185 |

Brier change +0.0025 (95% cluster-bootstrap interval -0.0008 to +0.0061, resampling expiration dates; negative means calibration helped) over 439,819 predictions, 34,553 snapshots and 876 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 140,080 | 0.1019 | 0.1043 | 0.0207 | 0.0208 |
| 21-35d | 140,247 | 0.1274 | 0.1305 | 0.0328 | 0.0213 |
| 36-50d | 82,172 | 0.1488 | 0.1505 | 0.0479 | 0.0157 |
| >50d | 77,320 | 0.1472 | 0.1496 | 0.0530 | 0.0145 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 41,521 | 0.1199 | 0.1212 | 0.0401 | 0.0189 |
| AMD | 41,132 | 0.1800 | 0.1844 | 0.0416 | 0.0405 |
| AMZN | 40,823 | 0.1363 | 0.1411 | 0.0296 | 0.0273 |
| DIA | 40,607 | 0.0631 | 0.0635 | 0.0272 | 0.0152 |
| GOOGL | 40,771 | 0.1308 | 0.1300 | 0.0577 | 0.0144 |
| META | 32,332 | 0.1520 | 0.1542 | 0.0457 | 0.0168 |
| MSFT | 40,696 | 0.1193 | 0.1234 | 0.0186 | 0.0301 |
| NVDA | 40,293 | 0.1578 | 0.1567 | 0.0822 | 0.0186 |
| SPY | 40,252 | 0.0695 | 0.0702 | 0.0285 | 0.0092 |
| TSLA | 40,506 | 0.1838 | 0.1941 | 0.0081 | 0.0681 |
| XLF | 40,886 | 0.0862 | 0.0876 | 0.0229 | 0.0205 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 88,226 | 0.1273 | 0.1266 | 0.0324 | 0.0174 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 133,172 | 0.0364 | 0.0181 | 163,751 | 0.0319 | 0.0390 |
| 0.1-0.2 | 54,779 | 0.1469 | 0.1115 | 60,823 | 0.1480 | 0.1921 |
| 0.2-0.3 | 39,513 | 0.2472 | 0.2070 | 38,495 | 0.2566 | 0.2814 |
| 0.3-0.4 | 32,197 | 0.3501 | 0.2970 | 29,700 | 0.3604 | 0.4029 |
| 0.4-0.5 | 34,735 | 0.4517 | 0.4039 | 24,414 | 0.4464 | 0.4680 |
| 0.5-0.6 | 26,913 | 0.5529 | 0.4982 | 27,718 | 0.5472 | 0.5651 |
| 0.6-0.7 | 32,320 | 0.6503 | 0.5934 | 31,378 | 0.6544 | 0.6560 |
| 0.7-0.8 | 29,977 | 0.7481 | 0.6881 | 20,506 | 0.7502 | 0.7485 |
| 0.8-0.9 | 24,286 | 0.8482 | 0.8145 | 16,209 | 0.8509 | 0.8612 |
| 0.9-1.0 | 31,927 | 0.9619 | 0.9554 | 26,825 | 0.9674 | 0.9669 |

## Top put credit spreads (2026-10-02)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected ROC | Annualised ROC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | TSLA | 2026-10-02 | 2026-10-16 | 14 | 370/367.5 | 1.22 | 1.00 | 58.1% | 51.1% | 14.38% | 3224.0% |
| 2 | MSFT | 2026-10-02 | 2026-10-16 | 14 | 512.5/507.5 | 1.90 | 1.15 | 70.0% | 61.5% | 12.90% | 2264.2% |
| 3 | TSLA | 2026-10-02 | 2026-10-16 | 14 | 370/362.5 | 3.34 | 3.15 | 60.7% | 54.6% | 12.72% | 2169.0% |
| 4 | GOOGL | 2026-10-02 | 2026-10-16 | 14 | 340/337.5 | 0.85 | 0.35 | 74.1% | 66.4% | 12.66% | 2136.9% |
| 5 | AMD | 2026-10-02 | 2026-10-16 | 14 | 630/620 | 4.55 | 3.90 | 60.7% | 54.1% | 12.25% | 1936.6% |
| 6 | AMD | 2026-10-02 | 2026-10-16 | 14 | 630/615 | 6.53 | 5.90 | 60.7% | 55.6% | 12.21% | 1917.8% |
| 7 | AMD | 2026-10-02 | 2026-10-16 | 14 | 620/615 | 1.97 | 1.45 | 68.1% | 60.0% | 12.14% | 1884.3% |
| 8 | TSLA | 2026-10-02 | 2026-10-16 | 14 | 370/360 | 4.19 | 4.00 | 61.0% | 56.1% | 12.00% | 1820.5% |
| 9 | TSLA | 2026-10-02 | 2026-10-16 | 14 | 367.5/362.5 | 2.12 | 1.90 | 63.2% | 56.8% | 11.98% | 1810.8% |
| 10 | AMD | 2026-10-02 | 2026-10-16 | 14 | 630/610 | 8.32 | 7.70 | 63.2% | 57.1% | 11.88% | 1765.4% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; ROC is the return on the collateral (maximum loss) over the trade, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on collateral is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,141 eligible spreads of the latest session the median annualised return is 0.7% under the risk-neutral CDF and 75.5% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.2 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.3%, right tail uncovered 15.2%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
