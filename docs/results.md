# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-04 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-04 | 1,214 | 3,841 | 3,759 | 47,598 |
| AMD | 2020-01-06 | 2026-11-04 | 1,211 | 3,835 | 3,751 | 47,609 |
| AMZN | 2020-01-06 | 2026-11-04 | 1,210 | 3,830 | 3,749 | 47,303 |
| DIA | 2020-01-06 | 2026-11-04 | 1,212 | 3,849 | 3,745 | 46,989 |
| GOOGL | 2020-01-06 | 2026-11-04 | 1,205 | 3,816 | 3,734 | 47,153 |
| META | 2022-07-01 | 2026-11-04 | 845 | 2,734 | 2,650 | 33,389 |
| MSFT | 2020-01-06 | 2026-11-04 | 1,200 | 3,796 | 3,714 | 46,885 |
| NVDA | 2020-01-06 | 2026-11-04 | 1,209 | 3,819 | 3,739 | 46,750 |
| SPY | 2020-01-06 | 2026-11-04 | 1,202 | 3,845 | 3,754 | 46,603 |
| TSLA | 2021-01-04 | 2026-11-04 | 1,060 | 3,373 | 3,291 | 41,612 |
| XLF | 2020-01-06 | 2026-11-04 | 1,202 | 3,818 | 3,733 | 47,237 |

In total: 1,858,329 quotes on 531,956 contracts, in 40,556 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,384 | 97.1% | enters the calibration sample |
| `unsettled` | 937 | 2.3% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1265 | 0.1290 | +0.0026 |
| Log loss (nats) | 0.3914 | 0.3959 | +0.0045 |
| Expected calibration error | 0.0339 | 0.0175 | -0.0164 |

Brier change +0.0026 (95% cluster-bootstrap interval -0.0009 to +0.0061, resampling expiration dates; negative means calibration helped) over 451,595 predictions, 35,470 snapshots and 887 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 143,117 | 0.1019 | 0.1045 | 0.0189 | 0.0222 |
| 21-35d | 143,601 | 0.1273 | 0.1305 | 0.0311 | 0.0223 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,612 | 0.1191 | 0.1199 | 0.0425 | 0.0162 |
| AMD | 42,183 | 0.1812 | 0.1856 | 0.0397 | 0.0412 |
| AMZN | 41,941 | 0.1350 | 0.1400 | 0.0277 | 0.0281 |
| DIA | 41,594 | 0.0626 | 0.0630 | 0.0265 | 0.0156 |
| GOOGL | 41,873 | 0.1325 | 0.1323 | 0.0507 | 0.0152 |
| META | 33,389 | 0.1535 | 0.1559 | 0.0430 | 0.0181 |
| MSFT | 41,777 | 0.1187 | 0.1223 | 0.0215 | 0.0270 |
| NVDA | 41,346 | 0.1573 | 0.1567 | 0.0767 | 0.0163 |
| SPY | 41,318 | 0.0687 | 0.0696 | 0.0273 | 0.0103 |
| TSLA | 41,612 | 0.1820 | 0.1916 | 0.0092 | 0.0640 |
| XLF | 41,950 | 0.0857 | 0.0871 | 0.0223 | 0.0210 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 100,002 | 0.1261 | 0.1260 | 0.0271 | 0.0198 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,076 | 0.0363 | 0.0186 | 168,095 | 0.0317 | 0.0391 |
| 0.1-0.2 | 56,092 | 0.1468 | 0.1121 | 62,453 | 0.1481 | 0.1917 |
| 0.2-0.3 | 40,449 | 0.2471 | 0.2072 | 39,404 | 0.2567 | 0.2821 |
| 0.3-0.4 | 33,019 | 0.3502 | 0.2982 | 30,537 | 0.3605 | 0.4039 |
| 0.4-0.5 | 35,566 | 0.4517 | 0.4046 | 24,971 | 0.4464 | 0.4699 |
| 0.5-0.6 | 27,600 | 0.5529 | 0.4999 | 28,517 | 0.5471 | 0.5675 |
| 0.6-0.7 | 33,215 | 0.6504 | 0.5964 | 32,400 | 0.6544 | 0.6596 |
| 0.7-0.8 | 30,869 | 0.7481 | 0.6914 | 21,070 | 0.7503 | 0.7529 |
| 0.8-0.9 | 24,979 | 0.8481 | 0.8180 | 16,613 | 0.8508 | 0.8638 |
| 0.9-1.0 | 32,730 | 0.9619 | 0.9563 | 27,535 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-04)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-04 | 2026-12-31 | 57 | 759/744 | 3.51 | 3.59 | 79.9% | 6.91% | 53.4% | 20.2% | 0.13 | 12.0% |
| 2 | SPY | 2026-11-04 | 2026-12-31 | 57 | 744/736 | 1.33 | 1.40 | 86.1% | 5.53% | 41.2% | 23.5% | 0.12 | 7.4% |
| 3 | SPY | 2026-11-04 | 2026-12-31 | 57 | 759/751 | 2.01 | 2.10 | 77.5% | 7.53% | 59.2% | 19.6% | 0.13 | 6.6% |
| 4 | SPY | 2026-11-04 | 2026-12-31 | 57 | 751/736 | 2.81 | 2.89 | 82.9% | 5.86% | 44.0% | 22.2% | 0.13 | 4.5% |
| 5 | SPY | 2026-11-04 | 2026-12-31 | 57 | 759/736 | 4.91 | 4.99 | 79.9% | 6.40% | 48.8% | 21.1% | 0.13 | 3.8% |
| 6 | SPY | 2026-11-04 | 2026-12-31 | 57 | 736/721 | 1.88 | 1.94 | 88.7% | 4.23% | 30.3% | 24.6% | 0.11 | 2.8% |
| 7 | SPY | 2026-11-04 | 2026-12-31 | 57 | 751/744 | 1.41 | 1.49 | 81.3% | 6.25% | 47.4% | 21.1% | 0.12 | 1.2% |
| 8 | SPY | 2026-11-04 | 2026-12-31 | 57 | 744/721 | 3.28 | 3.35 | 86.1% | 4.66% | 33.9% | 24.2% | 0.12 | 0.4% |
| 9 | SPY | 2026-11-04 | 2026-12-31 | 57 | 751/721 | 4.76 | 4.83 | 84.0% | 5.01% | 36.8% | 23.2% | 0.12 | -1.4% |
| 10 | SPY | 2026-11-04 | 2026-12-31 | 57 | 736/705 | 3.30 | 3.35 | 88.7% | 3.92% | 27.9% | 27.7% | 0.12 | -3.1% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-04)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-04 (30d) | long call `+1 C 370`, +352.2% | bull call spread `+1 C 355 / -1 C 365`, +115.3% | iron condor `-1 P 345 / +1 P 330 / -1 C 360 / +1 C 375`, +57.7% | iron condor `-1 P 340 / +1 P 330 / -1 C 350 / +1 C 360`, +99.1% | bear put spread `+1 P 340 / -1 P 320`, +186.5% | long strangle `+1 P 320 / +1 C 370`, +242.0% |
| AMD | 2026-12-04 (30d) | long call `+1 C 560`, +341.6% | bull put spread `-1 P 530 / +1 P 490`, +121.6% | iron condor `-1 P 475 / +1 P 430 / -1 C 530 / +1 C 575`, +79.7% | iron condor `-1 P 430 / +1 P 390 / -1 C 490 / +1 C 530`, +97.8% | bear put spread `+1 P 450 / -1 P 405`, +185.9% | long strangle `+1 P 430 / +1 C 560`, +244.6% |
| AMZN | 2026-12-04 (30d) | long call `+1 C 285`, +376.9% | bull call spread `+1 C 270 / -1 C 285`, +117.1% | iron condor `-1 P 265 / +1 P 245 / -1 C 275 / +1 C 295`, +60.7% | iron condor `-1 P 255 / +1 P 245 / -1 C 270 / +1 C 280`, +89.3% | bear put spread `+1 P 260 / -1 P 245`, +188.8% | long strangle `+1 P 245 / +1 C 295`, +271.4% |
| DIA | 2026-12-04 (30d) | bull call spread `+1 C 549 / -1 C 575`, +359.2% | bull put spread `-1 P 549 / +1 P 538`, +120.7% | iron condor `-1 P 533 / +1 P 517 / -1 C 549 / +1 C 565`, +53.5% | iron condor `-1 P 528 / +1 P 517 / -1 C 538 / +1 C 549`, +84.5% | bear put spread `+1 P 528 / -1 P 512`, +189.8% | long call `+1 C 555`, +368.1% |
| GOOGL | 2026-12-04 (30d) | bull call spread `+1 C 310 / -1 C 330`, +350.3% | bull call spread `+1 C 295 / -1 C 310`, +91.9% | iron condor `-1 P 285 / +1 P 265 / -1 C 300 / +1 C 320`, +47.9% | iron condor `-1 P 275 / +1 P 255 / -1 C 290 / +1 C 310`, +59.4% | bear put spread `+1 P 280 / -1 P 260`, +162.8% | long strangle `+1 P 255 / +1 C 320`, +271.8% |
| META | 2026-12-04 (30d) | bull call spread `+1 C 680 / -1 C 740`, +354.5% | bull call spread `+1 C 645 / -1 C 670`, +122.5% | iron condor `-1 P 615 / +1 P 590 / -1 C 670 / +1 C 695`, +77.6% | iron condor `-1 P 580 / +1 P 565 / -1 C 635 / +1 C 650`, +101.5% | bear put spread `+1 P 605 / -1 P 550`, +201.1% | bull call spread `+1 C 710 / -1 C 755`, +387.0% |
| MSFT | 2026-12-04 (30d) | long call `+1 C 590`, +347.0% | bull call spread `+1 C 565 / -1 C 590`, +112.2% | iron condor `-1 P 555 / +1 P 535 / -1 C 580 / +1 C 600`, +52.3% | iron condor `-1 P 540 / +1 P 510 / -1 C 560 / +1 C 590`, +73.1% | bear put spread `+1 P 545 / -1 P 500`, +179.4% | long strangle `+1 P 485 / +1 C 600`, +254.2% |
| NVDA | 2026-12-04 (30d) | bull call spread `+1 C 220 / -1 C 235`, +368.7% | bull call spread `+1 C 205 / -1 C 215`, +132.2% | iron condor `-1 P 200 / +1 P 185 / -1 C 210 / +1 C 225`, +88.1% | iron condor `-1 P 180 / +1 P 175 / -1 C 205 / +1 C 210`, +117.2% | bear put spread `+1 P 190 / -1 P 170`, +201.0% | bull call spread `+1 C 230 / -1 C 250`, +402.1% |
| SPY | 2026-11-30 (26d) | long call `+1 C 797`, +613.2% | bull call spread `+1 C 782 / -1 C 790`, +126.4% | iron condor `-1 P 759 / +1 P 751 / -1 C 782 / +1 C 790`, +58.0% | iron condor `-1 P 759 / +1 P 744 / -1 C 767 / +1 C 782`, +154.9% | bear put spread `+1 P 767 / -1 P 744`, +209.3% | long strangle `+1 P 652 / +1 C 797`, +533.6% |
| TSLA | 2026-12-04 (30d) | bull call spread `+1 C 425 / -1 C 455`, +369.4% | bull call spread `+1 C 395 / -1 C 410`, +134.7% | iron condor `-1 P 385 / +1 P 360 / -1 C 400 / +1 C 425`, +89.3% | iron condor `-1 P 355 / +1 P 345 / -1 C 390 / +1 C 400`, +128.1% | bear put spread `+1 P 370 / -1 P 335`, +203.3% | long strangle `+1 P 335 / +1 C 435`, +256.2% |
| XLF | 2026-12-04 (30d) | long call `+1 C 60`, +255.5% | bull call spread `+1 C 58.5 / -1 C 63`, +53.3% | iron condor `-1 P 59 / +1 P 55.5 / -1 C 60.5 / +1 C 64`, +15.6% | bear call spread `-1 C 58.5 / +1 C 63`, +31.0% | long put `+1 P 59`, +103.0% | long strangle `+1 P 57.5 / +1 C 63`, +116.4% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-04)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | NVDA | 2026-11-04 | 2026-11-18 | 14 | 187.5/185 | 1.09 | 0.25 | 74.7% | 69.3% | 34.99% | 249357.8% |
| 2 | GOOGL | 2026-11-04 | 2026-11-18 | 14 | 285/280 | 2.12 | 0.60 | 69.6% | 61.2% | 22.41% | 19356.3% |
| 3 | AMD | 2026-11-04 | 2026-11-18 | 14 | 460/450 | 4.20 | 0.70 | 70.9% | 65.0% | 22.35% | 19124.0% |
| 4 | GOOGL | 2026-11-04 | 2026-11-18 | 14 | 285/277.5 | 2.81 | 0.70 | 74.7% | 67.0% | 18.09% | 7531.0% |
| 5 | AMD | 2026-11-04 | 2026-11-18 | 14 | 460/440 | 7.68 | 2.80 | 70.9% | 65.1% | 17.58% | 6723.9% |
| 6 | AMD | 2026-11-04 | 2026-11-18 | 14 | 430/415 | 3.21 | 0.50 | 91.8% | 87.9% | 17.44% | 6515.9% |
| 7 | AMD | 2026-11-04 | 2026-12-04 | 30 | 475/470 | 2.82 | 0.75 | 60.7% | 52.8% | 39.94% | 5865.7% |
| 8 | TSLA | 2026-11-04 | 2026-11-18 | 14 | 385/382.5 | 1.20 | 0.90 | 59.1% | 52.0% | 15.24% | 3935.3% |
| 9 | AMZN | 2026-11-04 | 2026-11-18 | 14 | 260/255 | 1.58 | 0.40 | 74.7% | 68.9% | 13.56% | 2652.7% |
| 10 | NVDA | 2026-11-04 | 2026-11-18 | 14 | 192.5/185 | 2.51 | 1.70 | 74.7% | 69.3% | 13.23% | 2449.7% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-04)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMZN | 2026-12-04 | 215/200 | 0.25 | 0.13 | 0.03 | +0.22 | 87.2% | 99.8% | 98.3% | 98.3% | +1.4 pp | 0.33 |
| 2 | AMZN | 2026-12-04 | 220/200 | 0.33 | 0.23 | 0.05 | +0.28 | 84.6% | 99.1% | 97.5% | 98.4% | +0.7 pp | 0.31 |
| 3 | SPY | 2026-12-31 | 613/575 | 0.36 | 0.35 | 0.06 | +0.31 | 83.9% | 99.8% | 98.8% | 99.0% | +0.7 pp | 0.22 |
| 4 | SPY | 2026-12-18 | 650/615 | 0.42 | 0.41 | 0.07 | +0.35 | 83.8% | 99.8% | 98.3% | 98.8% | +1.0 pp | 0.24 |
| 5 | SPY | 2026-12-31 | 633/575 | 0.64 | 0.62 | 0.10 | +0.54 | 83.6% | 99.8% | 98.3% | 98.9% | +0.9 pp | 0.23 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 56 breaches in 53,338, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,119 eligible spreads of the latest session the median annualised return is 1.2% under the risk-neutral CDF and 71.7% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.7 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.1%, right tail uncovered 15.2%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
