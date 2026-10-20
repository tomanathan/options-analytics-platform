# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-19 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-19 | 1,202 | 3,795 | 3,715 | 47,027 |
| AMD | 2020-01-06 | 2026-10-19 | 1,199 | 3,789 | 3,708 | 47,069 |
| AMZN | 2020-01-06 | 2026-10-19 | 1,198 | 3,784 | 3,704 | 46,718 |
| DIA | 2020-01-06 | 2026-10-19 | 1,200 | 3,801 | 3,704 | 46,474 |
| GOOGL | 2020-01-06 | 2026-10-19 | 1,193 | 3,770 | 3,690 | 46,584 |
| META | 2022-07-01 | 2026-10-19 | 833 | 2,688 | 2,607 | 32,856 |
| MSFT | 2020-01-06 | 2026-10-19 | 1,188 | 3,750 | 3,670 | 46,329 |
| NVDA | 2020-01-06 | 2026-10-19 | 1,197 | 3,773 | 3,697 | 46,204 |
| SPY | 2020-01-06 | 2026-10-19 | 1,190 | 3,797 | 3,706 | 45,979 |
| TSLA | 2021-01-04 | 2026-10-19 | 1,048 | 3,327 | 3,247 | 41,049 |
| XLF | 2020-01-06 | 2026-10-19 | 1,190 | 3,770 | 3,689 | 46,675 |

In total: 1,833,610 quotes on 524,915 contracts, in 40,044 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 38,902 | 97.1% | enters the calibration sample |
| `unsettled` | 907 | 2.3% | the expiration is after the last priced session, so there is no outcome yet |
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

## Top 10 to enter (2026-10-19)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-10-19 | 2026-12-18 | 60 | 766/759 | 2.19 | 2.24 | 74.3% | 9.69% | 75.5% | 19.3% | 0.14 | 23.6% |
| 2 | NVDA | 2026-10-19 | 2026-12-18 | 60 | 213/200 | 4.60 | 4.75 | 70.0% | 10.72% | 85.8% | 17.6% | 0.15 | 21.8% |
| 3 | NVDA | 2026-10-19 | 2026-12-18 | 60 | 215/200 | 5.50 | 5.65 | 68.5% | 10.77% | 86.4% | 16.9% | 0.15 | 21.8% |
| 4 | NVDA | 2026-10-19 | 2026-12-18 | 60 | 215/195 | 6.85 | 6.97 | 70.0% | 10.03% | 78.8% | 17.6% | 0.15 | 18.2% |
| 5 | SPY | 2026-10-19 | 2026-12-18 | 60 | 766/751 | 4.28 | 4.32 | 75.0% | 8.60% | 65.2% | 19.8% | 0.14 | 14.3% |
| 6 | SPY | 2026-10-19 | 2026-12-18 | 60 | 759/743 | 3.72 | 3.77 | 80.0% | 7.08% | 51.6% | 21.1% | 0.13 | 12.6% |
| 7 | NVDA | 2026-10-19 | 2026-12-18 | 60 | 213/195 | 5.95 | 6.08 | 70.2% | 9.92% | 77.8% | 18.3% | 0.15 | 12.1% |
| 8 | AMZN | 2026-10-19 | 2026-12-18 | 60 | 255/235 | 6.85 | 7.22 | 70.0% | 10.62% | 84.8% | 17.7% | 0.15 | 11.7% |
| 9 | SPY | 2026-10-19 | 2026-12-18 | 60 | 759/751 | 2.04 | 2.09 | 77.6% | 7.72% | 57.2% | 20.3% | 0.13 | 10.8% |
| 10 | NVDA | 2026-10-19 | 2026-12-18 | 60 | 210/200 | 3.30 | 3.48 | 70.8% | 10.97% | 88.4% | 19.5% | 0.16 | 9.8% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-10-19)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-11-27 (39d) | long call `+1 C 370`, +367.0% | bull call spread `+1 C 355 / -1 C 370`, +113.2% | iron condor `-1 P 340 / +1 P 320 / -1 C 355 / +1 C 375`, +59.8% | iron condor `-1 P 340 / +1 P 320 / -1 C 345 / +1 C 365`, +101.4% | bear put spread `+1 P 335 / -1 P 310`, +190.5% | long strangle `+1 P 300 / +1 C 375`, +256.8% |
| AMD | 2026-11-27 (39d) | long call `+1 C 620`, +364.6% | bull call spread `+1 C 560 / -1 C 590`, +131.2% | iron condor `-1 P 535 / +1 P 485 / -1 C 580 / +1 C 630`, +83.6% | iron condor `-1 P 485 / +1 P 455 / -1 C 540 / +1 C 570`, +127.2% | bear put spread `+1 P 505 / -1 P 455`, +195.0% | long strangle `+1 P 470 / +1 C 605`, +236.3% |
| AMZN | 2026-11-27 (39d) | bull call spread `+1 C 285 / -1 C 310`, +332.0% | bull call spread `+1 C 260 / -1 C 275`, +121.7% | iron condor `-1 P 255 / +1 P 235 / -1 C 275 / +1 C 295`, +71.3% | iron condor `-1 P 235 / +1 P 225 / -1 C 265 / +1 C 275`, +65.3% | bear put spread `+1 P 250 / -1 P 225`, +185.6% | long strangle `+1 P 225 / +1 C 290`, +254.0% |
| DIA | 2026-11-27 (39d) | long call `+1 C 540`, +379.4% | bull put spread `-1 P 534 / +1 P 524`, +123.3% | iron condor `-1 P 514 / +1 P 503 / -1 C 529 / +1 C 540`, +56.3% | iron condor `-1 P 503 / +1 P 498 / -1 C 519 / +1 C 524`, +105.2% | bear put spread `+1 P 514 / -1 P 498`, +192.9% | long strangle `+1 P 455 / +1 C 540`, +251.1% |
| GOOGL | 2026-11-27 (39d) | bull call spread `+1 C 380 / -1 C 405`, +321.7% | bull call spread `+1 C 350 / -1 C 380`, +107.8% | iron condor `-1 P 340 / +1 P 315 / -1 C 360 / +1 C 385`, +61.6% | iron condor `-1 P 325 / +1 P 310 / -1 C 345 / +1 C 360`, +89.1% | bear put spread `+1 P 325 / -1 P 295`, +182.5% | long strangle `+1 P 310 / +1 C 380`, +249.8% |
| META | 2026-11-27 (39d) | long call `+1 C 775`, +277.0% | bull call spread `+1 C 700 / -1 C 760`, +102.3% | iron condor `-1 P 700 / +1 P 635 / -1 C 710 / +1 C 775`, +62.5% | iron condor `-1 P 650 / +1 P 600 / -1 C 710 / +1 C 760`, +64.8% | bear put spread `+1 P 650 / -1 P 600`, +169.3% | long strangle `+1 P 600 / +1 C 775`, +174.9% |
| MSFT | 2026-11-27 (39d) | long call `+1 C 575`, +335.5% | bull call spread `+1 C 540 / -1 C 575`, +110.5% | iron condor `-1 P 530 / +1 P 500 / -1 C 555 / +1 C 585`, +68.3% | iron condor `-1 P 500 / +1 P 480 / -1 C 535 / +1 C 555`, +86.0% | bear put spread `+1 P 525 / -1 P 480`, +167.9% | long strangle `+1 P 480 / +1 C 585`, +245.0% |
| NVDA | 2026-11-27 (39d) | bull call spread `+1 C 240 / -1 C 260`, +361.0% | bull put spread `-1 P 235 / +1 P 220`, +130.3% | iron condor `-1 P 215 / +1 P 205 / -1 C 230 / +1 C 240`, +80.8% | iron condor `-1 P 200 / +1 P 190 / -1 C 220 / +1 C 230`, +102.1% | bear put spread `+1 P 205 / -1 P 195`, +199.6% | bull call spread `+1 C 250 / -1 C 270`, +422.7% |
| SPY | 2026-11-30 (42d) | bull put spread `-1 P 860 / +1 P 789`, +540.9% | bull call spread `+1 C 782 / -1 C 789`, +145.9% | iron condor `-1 P 766 / +1 P 759 / -1 C 782 / +1 C 789`, +84.1% | iron condor `-1 P 759 / +1 P 751 / -1 C 774 / +1 C 782`, +181.0% | bear put spread `+1 P 766 / -1 P 751`, +212.8% | long call `+1 C 812`, +755.4% |
| TSLA | 2026-11-27 (39d) | bull call spread `+1 C 405 / -1 C 440`, +374.4% | bull call spread `+1 C 370 / -1 C 385`, +138.5% | iron condor `-1 P 360 / +1 P 330 / -1 C 385 / +1 C 415`, +90.9% | iron condor `-1 P 330 / +1 P 315 / -1 C 370 / +1 C 385`, +110.0% | bear put spread `+1 P 340 / -1 P 320`, +202.1% | long strangle `+1 P 315 / +1 C 415`, +273.7% |
| XLF | 2026-11-27 (39d) | long call `+1 C 56`, +227.6% | bull call spread `+1 C 55 / -1 C 56`, +56.2% | bull call spread `+1 C 55 / -1 C 56`, +34.9% | bear call spread `-1 C 56 / +1 C 58.5`, +4.6% | bear put spread `+1 P 55.5 / -1 P 54.5`, +107.8% | long call `+1 C 56`, +116.9% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-10-19)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | TSLA | 2026-10-19 | 2026-11-02 | 14 | 365/360 | 3.50 | 1.20 | 56.4% | 49.6% | 88.36% | 1477865704.2% |
| 2 | TSLA | 2026-10-19 | 2026-11-02 | 14 | 365/355 | 5.42 | 3.20 | 60.8% | 54.5% | 33.16% | 174758.7% |
| 3 | META | 2026-10-19 | 2026-11-02 | 14 | 700/690 | 5.28 | 3.45 | 59.3% | 51.4% | 26.90% | 49713.8% |
| 4 | TSLA | 2026-10-19 | 2026-11-02 | 14 | 365/345 | 9.53 | 7.51 | 68.2% | 59.7% | 25.16% | 34694.7% |
| 5 | XLF | 2026-10-19 | 2026-11-13 | 25 | 55/54 | 0.48 | 0.23 | 75.0% | 66.9% | 43.45% | 19301.4% |
| 6 | TSLA | 2026-10-19 | 2026-11-02 | 14 | 365/340 | 10.82 | 8.90 | 68.2% | 59.7% | 20.29% | 12262.1% |
| 7 | META | 2026-10-19 | 2026-11-02 | 14 | 705/690 | 7.60 | 5.80 | 59.3% | 51.1% | 20.09% | 11717.6% |
| 8 | META | 2026-10-19 | 2026-11-02 | 14 | 700/685 | 7.32 | 4.85 | 60.8% | 53.6% | 19.69% | 10732.6% |
| 9 | TSLA | 2026-10-19 | 2026-11-02 | 14 | 355/345 | 4.11 | 2.76 | 68.2% | 59.7% | 18.96% | 9141.6% |
| 10 | META | 2026-10-19 | 2026-11-02 | 14 | 705/685 | 9.65 | 7.20 | 59.3% | 51.1% | 16.68% | 5480.1% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-10-19)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-30 | 652/613 | 0.50 | 0.48 | 0.08 | +0.42 | 84.3% | 99.7% | 98.3% | 98.7% | +0.9 pp | 0.26 |
| 2 | DIA | 2026-12-18 | 430/390 | 0.43 | 0.27 | 0.07 | +0.37 | 84.2% | 99.8% | 98.4% | 98.9% | +0.9 pp | 0.24 |
| 3 | DIA | 2026-11-13 | 465/440 | 0.25 | 0.14 | 0.04 | +0.21 | 84.0% | 99.8% | 98.4% | 99.0% | +0.8 pp | 0.23 |
| 4 | SPY | 2026-11-30 | 652/632 | 0.29 | 0.27 | 0.05 | +0.24 | 83.9% | 99.7% | 98.3% | 98.6% | +1.1 pp | 0.26 |
| 5 | SPY | 2026-11-30 | 632/575 | 0.50 | 0.48 | 0.08 | +0.41 | 83.7% | 99.8% | 98.7% | 99.1% | +0.6 pp | 0.20 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,508, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,354 eligible spreads of the latest session the median annualised return is 1.1% under the risk-neutral CDF and 81.0% after calibration, against a cash rate of 3.6%.

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
