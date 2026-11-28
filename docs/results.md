# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-27 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-27 | 1,230 | 3,905 | 3,822 | 48,414 |
| AMD | 2020-01-06 | 2026-11-27 | 1,227 | 3,899 | 3,815 | 48,410 |
| AMZN | 2020-01-06 | 2026-11-27 | 1,226 | 3,894 | 3,810 | 48,096 |
| DIA | 2020-01-06 | 2026-11-27 | 1,228 | 3,913 | 3,812 | 47,817 |
| GOOGL | 2020-01-06 | 2026-11-27 | 1,221 | 3,880 | 3,796 | 47,959 |
| META | 2022-07-01 | 2026-11-25 | 860 | 2,794 | 2,714 | 34,183 |
| MSFT | 2020-01-06 | 2026-11-25 | 1,215 | 3,855 | 3,776 | 47,666 |
| NVDA | 2020-01-06 | 2026-11-27 | 1,225 | 3,882 | 3,800 | 47,543 |
| SPY | 2020-01-06 | 2026-11-27 | 1,218 | 3,909 | 3,809 | 47,295 |
| TSLA | 2021-01-04 | 2026-11-27 | 1,076 | 3,437 | 3,353 | 42,409 |
| XLF | 2020-01-06 | 2026-11-27 | 1,218 | 3,882 | 3,796 | 48,050 |

In total: 1,891,853 quotes on 541,562 contracts, in 41,250 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 40,068 | 97.1% | enters the calibration sample |
| `unsettled` | 947 | 2.3% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1277 | 0.1306 | +0.0030 |
| Log loss (nats) | 0.3950 | 0.4007 | +0.0057 |
| Expected calibration error | 0.0295 | 0.0219 | -0.0076 |

Brier change +0.0030 (95% cluster-bootstrap interval +0.0005 to +0.0070, resampling expiration dates; negative means calibration helped) over 460,309 predictions, 36,153 snapshots and 900 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 145,438 | 0.1023 | 0.1051 | 0.0169 | 0.0241 |
| 21-35d | 146,066 | 0.1283 | 0.1318 | 0.0274 | 0.0256 |
| 36-50d | 88,366 | 0.1498 | 0.1523 | 0.0377 | 0.0215 |
| >50d | 80,439 | 0.1481 | 0.1510 | 0.0476 | 0.0172 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 43,428 | 0.1180 | 0.1188 | 0.0430 | 0.0137 |
| AMD | 42,984 | 0.1835 | 0.1889 | 0.0311 | 0.0478 |
| AMZN | 42,734 | 0.1342 | 0.1393 | 0.0274 | 0.0284 |
| DIA | 42,422 | 0.0634 | 0.0642 | 0.0238 | 0.0169 |
| GOOGL | 42,679 | 0.1361 | 0.1369 | 0.0415 | 0.0206 |
| META | 34,183 | 0.1557 | 0.1591 | 0.0342 | 0.0223 |
| MSFT | 42,558 | 0.1188 | 0.1228 | 0.0181 | 0.0303 |
| NVDA | 42,139 | 0.1627 | 0.1633 | 0.0640 | 0.0218 |
| SPY | 42,010 | 0.0704 | 0.0717 | 0.0233 | 0.0112 |
| TSLA | 42,409 | 0.1809 | 0.1905 | 0.0089 | 0.0642 |
| XLF | 42,763 | 0.0853 | 0.0867 | 0.0224 | 0.0209 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 108,716 | 0.1311 | 0.1330 | 0.0089 | 0.0359 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 139,625 | 0.0364 | 0.0208 | 171,019 | 0.0316 | 0.0413 |
| 0.1-0.2 | 57,185 | 0.1468 | 0.1181 | 63,809 | 0.1481 | 0.1978 |
| 0.2-0.3 | 41,242 | 0.2471 | 0.2132 | 40,179 | 0.2568 | 0.2887 |
| 0.3-0.4 | 33,708 | 0.3502 | 0.3054 | 31,199 | 0.3607 | 0.4108 |
| 0.4-0.5 | 36,226 | 0.4516 | 0.4105 | 25,465 | 0.4465 | 0.4771 |
| 0.5-0.6 | 28,231 | 0.5529 | 0.5080 | 29,172 | 0.5470 | 0.5749 |
| 0.6-0.7 | 33,889 | 0.6504 | 0.6027 | 33,190 | 0.6544 | 0.6666 |
| 0.7-0.8 | 31,564 | 0.7481 | 0.6974 | 21,409 | 0.7503 | 0.7565 |
| 0.8-0.9 | 25,384 | 0.8481 | 0.8206 | 16,874 | 0.8509 | 0.8655 |
| 0.9-1.0 | 33,255 | 0.9619 | 0.9568 | 27,993 | 0.9673 | 0.9680 |

## Top 10 to enter (2026-11-27)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-27 | 2027-01-29 | 63 | 728/706 | 6.55 | 6.79 | 73.5% | 8.59% | 61.2% | 17.9% | 0.13 | 9.4% |
| 2 | SPY | 2026-11-27 | 2027-01-29 | 63 | 728/699 | 8.19 | 8.42 | 74.1% | 7.71% | 53.8% | 17.4% | 0.13 | 6.5% |
| 3 | SPY | 2026-11-27 | 2027-01-29 | 63 | 721/699 | 5.72 | 5.95 | 75.2% | 7.02% | 48.2% | 17.3% | 0.12 | 0.7% |
| 4 | AMZN | 2026-11-27 | 2027-01-15 | 49 | 250/230 | 5.60 | 6.00 | 74.1% | 7.36% | 69.7% | 16.1% | 0.12 | 0.6% |
| 5 | SPY | 2026-11-27 | 2027-01-29 | 63 | 714/699 | 3.45 | 3.77 | 79.3% | 6.43% | 43.4% | 17.3% | 0.11 | 0.6% |
| 6 | SPY | 2026-11-27 | 2027-01-29 | 63 | 721/685 | 8.42 | 8.64 | 77.2% | 6.37% | 43.0% | 18.2% | 0.12 | -0.1% |
| 7 | SPY | 2026-11-27 | 2027-01-29 | 63 | 699/685 | 2.50 | 2.70 | 83.4% | 5.43% | 35.9% | 20.2% | 0.11 | -0.4% |
| 8 | SPY | 2026-11-27 | 2027-01-29 | 63 | 721/706 | 4.08 | 4.31 | 74.1% | 7.92% | 55.5% | 18.1% | 0.13 | -0.8% |
| 9 | SPY | 2026-11-27 | 2027-01-29 | 63 | 721/670 | 10.65 | 10.86 | 79.3% | 5.56% | 36.8% | 18.3% | 0.11 | -0.8% |
| 10 | SPY | 2026-11-27 | 2027-01-29 | 63 | 699/670 | 4.73 | 4.91 | 84.0% | 4.58% | 29.6% | 19.5% | 0.10 | -1.1% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-27)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2027-01-08 (42d) | long call `+1 C 380`, +325.8% | bull call spread `+1 C 365 / -1 C 380`, +97.8% | iron condor `-1 P 355 / +1 P 330 / -1 C 370 / +1 C 395`, +43.9% | iron condor `-1 P 345 / +1 P 330 / -1 C 360 / +1 C 375`, +84.3% | bear put spread `+1 P 355 / -1 P 330`, +190.9% | long strangle `+1 P 330 / +1 C 385`, +221.7% |
| AMD | 2027-01-08 (42d) | long call `+1 C 500`, +266.5% | bull call spread `+1 C 460 / -1 C 500`, +71.0% | iron condor `-1 P 380 / +1 P 350 / -1 C 500 / +1 C 530`, +34.0% | iron condor `-1 P 360 / +1 P 320 / -1 C 425 / +1 C 465`, +58.9% | long put `+1 P 360`, +174.0% | long call `+1 C 530`, +293.3% |
| AMZN | 2027-01-08 (42d) | long call `+1 C 280`, +315.7% | bull call spread `+1 C 260 / -1 C 280`, +98.7% | iron condor `-1 P 250 / +1 P 230 / -1 C 270 / +1 C 290`, +54.0% | iron condor `-1 P 235 / +1 P 220 / -1 C 255 / +1 C 270`, +84.9% | bear put spread `+1 P 245 / -1 P 220`, +179.2% | long call `+1 C 290`, +322.0% |
| DIA | 2027-01-08 (42d) | long call `+1 C 528`, +339.9% | bull put spread `-1 P 528 / +1 P 513`, +110.6% | iron condor `-1 P 497 / +1 P 487 / -1 C 528 / +1 C 538`, +40.9% | iron condor `-1 P 497 / +1 P 487 / -1 C 508 / +1 C 518`, +106.7% | bear put spread `+1 P 503 / -1 P 465`, +196.1% | long call `+1 C 538`, +373.6% |
| GOOGL | 2027-01-08 (42d) | long call `+1 C 300`, +354.7% | bull put spread `-1 P 300 / +1 P 275`, +98.1% | iron condor `-1 P 270 / +1 P 245 / -1 C 290 / +1 C 315`, +56.4% | iron condor `-1 P 255 / +1 P 235 / -1 C 275 / +1 C 295`, +79.0% | bear put spread `+1 P 260 / -1 P 235`, +181.4% | long call `+1 C 315`, +391.2% |
| NVDA | 2027-01-08 (42d) | long call `+1 C 175`, +370.5% | bull call spread `+1 C 155 / -1 C 170`, +117.6% | iron condor `-1 P 150 / +1 P 135 / -1 C 160 / +1 C 175`, +55.5% | iron condor `-1 P 130 / +1 P 120 / -1 C 155 / +1 C 165`, +77.5% | long put `+1 P 140`, +186.2% | long strangle `+1 P 130 / +1 C 170`, +233.1% |
| SPY | 2027-01-08 (42d) | long call `+1 C 770`, +491.1% | bull call spread `+1 C 750 / -1 C 755`, +131.0% | iron condor `-1 P 721 / +1 P 706 / -1 C 755 / +1 C 770`, +78.9% | iron condor `-1 P 699 / +1 P 685 / -1 C 736 / +1 C 750`, +154.9% | bear put spread `+1 P 721 / -1 P 670`, +216.3% | long strangle `+1 P 620 / +1 C 770`, +275.2% |
| TSLA | 2027-01-08 (42d) | long call `+1 C 450`, +352.1% | bull call spread `+1 C 410 / -1 C 450`, +96.9% | iron condor `-1 P 390 / +1 P 350 / -1 C 430 / +1 C 470`, +58.1% | iron condor `-1 P 350 / +1 P 330 / -1 C 405 / +1 C 425`, +89.4% | bear put spread `+1 P 370 / -1 P 330`, +193.0% | long strangle `+1 P 340 / +1 C 460`, +242.5% |
| XLF | 2027-01-08 (42d) | long call `+1 C 58.5`, +154.9% | bull put spread `-1 P 58.5 / +1 P 55`, +36.9% | bull put spread `-1 P 57.5 / +1 P 55`, +20.2% | bear call spread `-1 C 57.5 / +1 C 63`, +9.8% | long put `+1 P 57`, +147.8% | long strangle `+1 P 55 / +1 C 59`, +169.4% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-27)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | TSLA | 2026-11-27 | 2026-12-11 | 14 | 387.5/385 | 1.13 | 0.41 | 70.0% | 64.9% | 29.61% | 86380.5% |
| 2 | GOOGL | 2026-11-27 | 2026-12-11 | 14 | 272.5/270 | 1.05 | 0.40 | 67.1% | 59.9% | 17.16% | 6114.4% |
| 3 | XLF | 2026-11-27 | 2026-12-11 | 14 | 56.5/55.5 | 0.29 | 0.02 | 80.5% | 77.0% | 15.22% | 3922.9% |
| 4 | AMD | 2026-11-27 | 2026-12-24 | 27 | 410/400 | 5.48 | 2.60 | 58.6% | 51.2% | 29.73% | 3272.3% |
| 5 | AMD | 2026-11-27 | 2026-12-11 | 14 | 412.5/400 | 5.23 | 2.50 | 63.3% | 59.4% | 12.81% | 2217.0% |
| 6 | GOOGL | 2026-11-27 | 2026-12-11 | 14 | 272.5/267.5 | 1.88 | 1.20 | 68.9% | 61.7% | 12.73% | 2172.5% |
| 7 | NVDA | 2026-11-27 | 2026-12-11 | 14 | 150/149 | 0.49 | 0.35 | 56.7% | 50.4% | 12.15% | 1887.5% |
| 8 | NVDA | 2026-11-27 | 2026-12-11 | 14 | 150/147 | 1.42 | 1.30 | 60.3% | 52.4% | 11.87% | 1763.0% |
| 9 | NVDA | 2026-11-27 | 2026-12-11 | 14 | 149/147 | 0.93 | 0.75 | 60.3% | 53.5% | 11.74% | 1707.1% |
| 10 | XLF | 2026-11-27 | 2026-12-11 | 14 | 56.5/55 | 0.38 | 0.11 | 80.5% | 77.0% | 11.10% | 1456.4% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-27)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-24 | 585/545 | 0.31 | 0.29 | 0.06 | +0.26 | 81.5% | 99.9% | 98.9% | 99.2% | +0.6 pp | 0.17 |
| 2 | SPY | 2026-12-24 | 600/545 | 0.49 | 0.47 | 0.10 | +0.40 | 80.1% | 99.7% | 98.6% | 99.1% | +0.6 pp | 0.18 |
| 3 | SPY | 2026-12-11 | 635/600 | 0.31 | 0.28 | 0.06 | +0.24 | 80.0% | 99.7% | 98.6% | 99.1% | +0.6 pp | 0.18 |
| 4 | AAPL | 2026-12-11 | 312.5/285 | 0.31 | 0.16 | 0.06 | +0.24 | 79.9% | 99.5% | 98.2% | 98.9% | +0.6 pp | 0.22 |
| 5 | SPY | 2026-12-11 | 635/585 | 0.38 | 0.36 | 0.08 | +0.30 | 78.2% | 99.7% | 98.6% | 99.2% | +0.5 pp | 0.15 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 76 breaches in 54,252, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,097 eligible spreads of the latest session the median annualised return is 0.8% under the risk-neutral CDF and 66.8% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.9 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.0%, right tail uncovered 15.1%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
