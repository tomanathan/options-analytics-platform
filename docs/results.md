# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-21 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-21 | 1,204 | 3,803 | 3,715 | 47,027 |
| AMD | 2020-01-06 | 2026-10-21 | 1,201 | 3,797 | 3,708 | 47,069 |
| AMZN | 2020-01-06 | 2026-10-21 | 1,200 | 3,792 | 3,704 | 46,718 |
| DIA | 2020-01-06 | 2026-10-21 | 1,202 | 3,809 | 3,704 | 46,474 |
| GOOGL | 2020-01-06 | 2026-10-21 | 1,195 | 3,778 | 3,690 | 46,584 |
| META | 2022-07-01 | 2026-10-21 | 835 | 2,696 | 2,607 | 32,856 |
| MSFT | 2020-01-06 | 2026-10-21 | 1,190 | 3,758 | 3,670 | 46,329 |
| NVDA | 2020-01-06 | 2026-10-21 | 1,199 | 3,781 | 3,697 | 46,204 |
| SPY | 2020-01-06 | 2026-10-21 | 1,192 | 3,805 | 3,706 | 45,979 |
| TSLA | 2021-01-04 | 2026-10-21 | 1,050 | 3,335 | 3,247 | 41,049 |
| XLF | 2020-01-06 | 2026-10-21 | 1,192 | 3,778 | 3,689 | 46,675 |

In total: 1,838,047 quotes on 526,177 contracts, in 40,132 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 38,902 | 96.9% | enters the calibration sample |
| `unsettled` | 995 | 2.5% | the expiration is after the last priced session, so there is no outcome yet |
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

## Top 10 to enter (2026-10-21)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-10-21 | 2026-12-18 | 58 | 773/758 | 4.47 | 4.54 | 75.0% | 9.21% | 74.1% | 19.9% | 0.15 | 20.8% |
| 2 | NVDA | 2026-10-21 | 2026-12-18 | 58 | 220/205 | 5.24 | 5.39 | 70.0% | 10.70% | 89.6% | 18.0% | 0.15 | 20.6% |
| 3 | MSFT | 2026-10-21 | 2026-12-18 | 58 | 530/500 | 10.55 | 10.98 | 70.2% | 10.61% | 88.6% | 17.4% | 0.15 | 20.6% |
| 4 | AMZN | 2026-10-21 | 2026-12-18 | 58 | 260/240 | 7.00 | 7.25 | 70.0% | 10.65% | 89.1% | 17.7% | 0.16 | 19.8% |
| 5 | NVDA | 2026-10-21 | 2026-12-18 | 58 | 220/210 | 3.69 | 3.87 | 68.3% | 11.45% | 97.8% | 17.2% | 0.15 | 18.1% |
| 6 | MSFT | 2026-10-21 | 2026-12-18 | 58 | 530/490 | 13.25 | 13.58 | 70.8% | 9.91% | 81.2% | 18.2% | 0.15 | 15.7% |
| 7 | MSFT | 2026-10-21 | 2026-12-18 | 58 | 530/510 | 7.40 | 7.88 | 68.2% | 11.43% | 97.7% | 16.7% | 0.15 | 14.9% |
| 8 | NVDA | 2026-10-21 | 2026-12-18 | 58 | 218/210 | 2.80 | 2.98 | 70.0% | 11.56% | 99.1% | 18.6% | 0.16 | 14.6% |
| 9 | SPY | 2026-10-21 | 2026-12-18 | 58 | 765/750 | 3.54 | 3.61 | 80.0% | 7.13% | 54.3% | 20.8% | 0.13 | 14.0% |
| 10 | NVDA | 2026-10-21 | 2026-12-18 | 58 | 218/205 | 4.35 | 4.50 | 70.2% | 10.67% | 89.3% | 19.1% | 0.16 | 12.4% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-10-21)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-11-27 (37d) | long call `+1 C 370`, +362.2% | bull call spread `+1 C 350 / -1 C 370`, +119.3% | iron condor `-1 P 340 / +1 P 330 / -1 C 360 / +1 C 370`, +75.6% | iron condor `-1 P 330 / +1 P 315 / -1 C 345 / +1 C 360`, +117.5% | bear put spread `+1 P 335 / -1 P 315`, +193.6% | long call `+1 C 370`, +343.5% |
| AMD | 2026-11-27 (37d) | bull call spread `+1 C 635 / -1 C 690`, +362.5% | bull put spread `-1 P 585 / +1 P 555`, +128.3% | iron condor `-1 P 545 / +1 P 495 / -1 C 570 / +1 C 620`, +91.7% | iron condor `-1 P 485 / +1 P 455 / -1 C 555 / +1 C 585`, +108.3% | bear put spread `+1 P 510 / -1 P 470`, +201.3% | long call `+1 C 690`, +417.4% |
| AMZN | 2026-11-27 (37d) | long call `+1 C 285`, +326.1% | bull call spread `+1 C 270 / -1 C 290`, +122.4% | iron condor `-1 P 260 / +1 P 245 / -1 C 280 / +1 C 295`, +76.0% | iron condor `-1 P 240 / +1 P 230 / -1 C 265 / +1 C 275`, +97.3% | bear put spread `+1 P 250 / -1 P 230`, +192.5% | long strangle `+1 P 230 / +1 C 295`, +245.4% |
| DIA | 2026-11-27 (37d) | long call `+1 C 549`, +361.8% | bull put spread `-1 P 544 / +1 P 533`, +120.8% | bull put spread `-1 P 528 / +1 P 517`, +33.2% | iron condor `-1 P 517 / +1 P 507 / -1 C 528 / +1 C 538`, +120.1% | bear put spread `+1 P 522.5 / -1 P 507`, +187.5% | long call `+1 C 549`, +340.0% |
| GOOGL | 2026-11-27 (37d) | long call `+1 C 360`, +363.2% | bull call spread `+1 C 340 / -1 C 360`, +118.9% | iron condor `-1 P 330 / +1 P 310 / -1 C 350 / +1 C 370`, +69.0% | iron condor `-1 P 315 / +1 P 300 / -1 C 335 / +1 C 350`, +98.9% | bear put spread `+1 P 315 / -1 P 295`, +181.7% | long strangle `+1 P 300 / +1 C 375`, +246.7% |
| META | 2026-11-27 (37d) | long call `+1 C 755`, +343.6% | bull call spread `+1 C 710 / -1 C 755`, +114.6% | iron condor `-1 P 685 / +1 P 640 / -1 C 755 / +1 C 800`, +76.5% | iron condor `-1 P 640 / +1 P 595 / -1 C 710 / +1 C 755`, +80.5% | bear put spread `+1 P 655 / -1 P 595`, +179.3% | long strangle `+1 P 595 / +1 C 800`, +263.1% |
| MSFT | 2026-11-27 (37d) | long call `+1 C 575`, +350.4% | bull call spread `+1 C 540 / -1 C 565`, +121.8% | iron condor `-1 P 530 / +1 P 500 / -1 C 555 / +1 C 585`, +59.9% | iron condor `-1 P 500 / +1 P 480 / -1 C 535 / +1 C 555`, +106.9% | bear put spread `+1 P 515 / -1 P 465`, +176.4% | long strangle `+1 P 465 / +1 C 585`, +245.1% |
| NVDA | 2026-11-27 (37d) | bull call spread `+1 C 245 / -1 C 265`, +369.3% | bull call spread `+1 C 225 / -1 C 235`, +131.7% | iron condor `-1 P 220 / +1 P 210 / -1 C 235 / +1 C 245`, +85.3% | iron condor `-1 P 205 / +1 P 200 / -1 C 225 / +1 C 230`, +128.3% | bear put spread `+1 P 215 / -1 P 195`, +198.9% | long strangle `+1 P 190 / +1 C 250`, +246.9% |
| SPY | 2026-11-20 (30d) | long call `+1 C 804`, +596.8% | bull call spread `+1 C 781 / -1 C 796`, +131.3% | iron condor `-1 P 773 / +1 P 765 / -1 C 796 / +1 C 804`, +91.2% | iron condor `-1 P 758 / +1 P 750 / -1 C 781 / +1 C 789`, +143.3% | bear put spread `+1 P 765 / -1 P 758`, +208.1% | long call `+1 C 804`, +669.6% |
| TSLA | 2026-11-27 (37d) | bull call spread `+1 C 425 / -1 C 455`, +359.6% | bull call spread `+1 C 395 / -1 C 415`, +133.3% | iron condor `-1 P 385 / +1 P 355 / -1 C 415 / +1 C 445`, +79.1% | iron condor `-1 P 355 / +1 P 330 / -1 C 390 / +1 C 415`, +95.0% | bear put spread `+1 P 365 / -1 P 330`, +197.6% | long strangle `+1 P 330 / +1 C 435`, +246.0% |
| XLF | 2026-11-27 (37d) | long call `+1 C 57.5`, +180.7% | bull call spread `+1 C 55.5 / -1 C 58.5`, +74.3% | bull call spread `+1 C 54 / -1 C 55.5`, +14.2% | bear call spread `-1 C 55.5 / +1 C 57.5`, +64.0% | long put `+1 P 57`, +141.0% | long strangle `+1 P 54 / +1 C 58.5`, +225.3% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-10-21)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMD | 2026-10-21 | 2026-11-27 | 37 | 545/540 | 3.48 | 1.60 | 56.4% | 49.9% | 85.66% | 44669.0% |
| 2 | MSFT | 2026-10-21 | 2026-11-04 | 14 | 532.5/527.5 | 2.47 | 0.25 | 60.8% | 55.3% | 20.71% | 13411.4% |
| 3 | AMZN | 2026-10-21 | 2026-11-04 | 14 | 257.5/252.5 | 2.05 | 0.15 | 70.9% | 64.6% | 20.33% | 12363.7% |
| 4 | AMD | 2026-10-21 | 2026-11-04 | 14 | 552.5/542.5 | 4.88 | 0.20 | 59.4% | 52.1% | 17.12% | 6050.1% |
| 5 | META | 2026-10-21 | 2026-11-27 | 37 | 690/685 | 2.95 | 0.10 | 60.8% | 53.6% | 48.71% | 4912.1% |
| 6 | MSFT | 2026-10-21 | 2026-11-04 | 14 | 532.5/522.5 | 4.60 | 2.75 | 61.0% | 56.2% | 16.18% | 4893.9% |
| 7 | AMZN | 2026-10-21 | 2026-11-04 | 14 | 257.5/247.5 | 3.68 | 1.95 | 70.9% | 64.6% | 15.85% | 4532.0% |
| 8 | META | 2026-10-21 | 2026-11-04 | 14 | 697.5/682.5 | 7.34 | 1.50 | 58.1% | 51.0% | 14.88% | 3624.5% |
| 9 | META | 2026-10-21 | 2026-11-04 | 14 | 670/655 | 5.55 | 0.05 | 70.8% | 64.3% | 14.46% | 3278.3% |
| 10 | AAPL | 2026-10-21 | 2026-11-04 | 14 | 337.5/332.5 | 1.68 | 0.70 | 75.0% | 68.3% | 14.23% | 3110.6% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-10-21)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | NVDA | 2026-11-04 | 195/180 | 0.27 | 0.16 | 0.04 | +0.23 | 86.4% | 99.7% | 98.2% | 98.2% | +1.5 pp | 0.34 |
| 2 | MSFT | 2026-11-27 | 425/400 | 0.38 | 0.24 | 0.05 | +0.33 | 85.8% | 99.8% | 98.3% | 98.5% | +1.3 pp | 0.29 |
| 3 | MSFT | 2026-11-20 | 425/400 | 0.30 | 0.17 | 0.05 | +0.25 | 84.5% | 99.8% | 98.5% | 98.8% | +1.0 pp | 0.25 |
| 4 | SPY | 2026-12-18 | 620/580 | 0.43 | 0.41 | 0.07 | +0.36 | 84.2% | 99.8% | 98.6% | 98.9% | +0.8 pp | 0.23 |
| 5 | SPY | 2026-12-18 | 640/580 | 0.74 | 0.72 | 0.12 | +0.62 | 84.1% | 99.7% | 98.2% | 98.8% | +0.9 pp | 0.25 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,508, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,512 eligible spreads of the latest session the median annualised return is 1.2% under the risk-neutral CDF and 82.0% after calibration, against a cash rate of 3.6%.

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
