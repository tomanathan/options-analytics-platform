# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-23 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-23 | 1,206 | 3,811 | 3,732 | 47,248 |
| AMD | 2020-01-06 | 2026-10-23 | 1,203 | 3,805 | 3,724 | 47,275 |
| AMZN | 2020-01-06 | 2026-10-23 | 1,202 | 3,800 | 3,720 | 46,926 |
| DIA | 2020-01-06 | 2026-10-23 | 1,204 | 3,817 | 3,721 | 46,688 |
| GOOGL | 2020-01-06 | 2026-10-23 | 1,197 | 3,786 | 3,706 | 46,792 |
| META | 2022-07-01 | 2026-10-23 | 837 | 2,704 | 2,623 | 33,060 |
| MSFT | 2020-01-06 | 2026-10-23 | 1,192 | 3,766 | 3,686 | 46,535 |
| NVDA | 2020-01-06 | 2026-10-23 | 1,201 | 3,789 | 3,711 | 46,386 |
| SPY | 2020-01-06 | 2026-10-23 | 1,194 | 3,813 | 3,720 | 46,161 |
| TSLA | 2021-01-04 | 2026-10-23 | 1,052 | 3,343 | 3,263 | 41,257 |
| XLF | 2020-01-06 | 2026-10-23 | 1,194 | 3,786 | 3,705 | 46,878 |

In total: 1,842,415 quotes on 527,481 contracts, in 40,220 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,076 | 97.2% | enters the calibration sample |
| `unsettled` | 909 | 2.3% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1263 | 0.1288 | +0.0024 |
| Log loss (nats) | 0.3909 | 0.3950 | +0.0042 |
| Expected calibration error | 0.0352 | 0.0164 | -0.0188 |

Brier change +0.0024 (95% cluster-bootstrap interval -0.0011 to +0.0064, resampling expiration dates; negative means calibration helped) over 447,673 predictions, 35,162 snapshots and 880 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 142,050 | 0.1017 | 0.1042 | 0.0198 | 0.0214 |
| 21-35d | 142,379 | 0.1269 | 0.1300 | 0.0326 | 0.0211 |
| 36-50d | 84,455 | 0.1477 | 0.1492 | 0.0482 | 0.0141 |
| >50d | 78,789 | 0.1468 | 0.1490 | 0.0541 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,262 | 0.1195 | 0.1205 | 0.0422 | 0.0173 |
| AMD | 41,849 | 0.1806 | 0.1847 | 0.0425 | 0.0395 |
| AMZN | 41,564 | 0.1353 | 0.1402 | 0.0286 | 0.0272 |
| DIA | 41,293 | 0.0628 | 0.0632 | 0.0265 | 0.0155 |
| GOOGL | 41,512 | 0.1301 | 0.1295 | 0.0559 | 0.0123 |
| META | 33,060 | 0.1524 | 0.1542 | 0.0473 | 0.0176 |
| MSFT | 41,427 | 0.1190 | 0.1227 | 0.0212 | 0.0273 |
| NVDA | 40,982 | 0.1571 | 0.1562 | 0.0797 | 0.0174 |
| SPY | 40,876 | 0.0690 | 0.0697 | 0.0281 | 0.0095 |
| TSLA | 41,257 | 0.1823 | 0.1923 | 0.0075 | 0.0664 |
| XLF | 41,591 | 0.0859 | 0.0874 | 0.0219 | 0.0216 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 96,080 | 0.1253 | 0.1246 | 0.0325 | 0.0167 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 135,806 | 0.0363 | 0.0180 | 166,687 | 0.0318 | 0.0386 |
| 0.1-0.2 | 55,660 | 0.1469 | 0.1108 | 61,895 | 0.1480 | 0.1906 |
| 0.2-0.3 | 40,125 | 0.2472 | 0.2060 | 39,078 | 0.2567 | 0.2801 |
| 0.3-0.4 | 32,726 | 0.3501 | 0.2959 | 30,268 | 0.3605 | 0.4022 |
| 0.4-0.5 | 35,299 | 0.4517 | 0.4033 | 24,774 | 0.4464 | 0.4683 |
| 0.5-0.6 | 27,340 | 0.5529 | 0.4981 | 28,234 | 0.5472 | 0.5655 |
| 0.6-0.7 | 32,905 | 0.6504 | 0.5943 | 32,064 | 0.6544 | 0.6571 |
| 0.7-0.8 | 30,583 | 0.7481 | 0.6892 | 20,872 | 0.7503 | 0.7510 |
| 0.8-0.9 | 24,759 | 0.8482 | 0.8168 | 16,497 | 0.8509 | 0.8631 |
| 0.9-1.0 | 32,470 | 0.9619 | 0.9561 | 27,304 | 0.9674 | 0.9675 |

## Top 10 to enter (2026-10-23)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | MSFT | 2026-10-23 | 2026-12-18 | 56 | 520/485 | 11.39 | 12.45 | 74.9% | 11.90% | 108.1% | 20.6% | 0.18 | 23.6% |
| 2 | TSLA | 2026-10-23 | 2026-12-18 | 56 | 365/350 | 5.54 | 5.82 | 68.4% | 11.15% | 99.1% | 16.7% | 0.15 | 19.4% |
| 3 | NVDA | 2026-10-23 | 2026-12-18 | 56 | 210/194 | 5.70 | 5.85 | 68.8% | 10.29% | 89.3% | 16.9% | 0.15 | 18.8% |
| 4 | TSLA | 2026-10-23 | 2026-12-18 | 56 | 370/335 | 12.09 | 12.42 | 69.9% | 10.19% | 88.3% | 17.5% | 0.15 | 18.8% |
| 5 | TSLA | 2026-10-23 | 2026-12-18 | 56 | 370/340 | 10.79 | 11.12 | 68.4% | 10.49% | 91.6% | 16.9% | 0.15 | 18.0% |
| 6 | MSFT | 2026-10-23 | 2026-12-18 | 56 | 515/485 | 9.30 | 10.02 | 74.9% | 11.06% | 98.1% | 20.9% | 0.17 | 17.8% |
| 7 | TSLA | 2026-10-23 | 2026-12-18 | 56 | 365/340 | 8.54 | 8.82 | 70.2% | 10.11% | 87.4% | 17.6% | 0.15 | 17.3% |
| 8 | MSFT | 2026-10-23 | 2026-12-18 | 56 | 515/495 | 6.45 | 7.25 | 74.9% | 12.37% | 113.8% | 20.8% | 0.18 | 16.3% |
| 9 | GOOGL | 2026-10-23 | 2026-12-18 | 56 | 315/300 | 5.25 | 5.57 | 69.9% | 10.97% | 97.1% | 17.6% | 0.15 | 14.5% |
| 10 | META | 2026-10-23 | 2026-12-18 | 56 | 635/590 | 15.50 | 16.23 | 69.9% | 10.18% | 88.1% | 17.1% | 0.15 | 14.4% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-10-23)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-11-20 (28d) | long call `+1 C 375`, +384.9% | bull call spread `+1 C 355 / -1 C 367.5`, +129.9% | iron condor `-1 P 347.5 / +1 P 335 / -1 C 362.5 / +1 C 375`, +79.9% | iron condor `-1 P 327.5 / +1 P 320 / -1 C 350 / +1 C 357.5`, +122.6% | bear put spread `+1 P 340 / -1 P 320`, +204.9% | long call `+1 C 380`, +506.4% |
| AMD | 2026-11-20 (28d) | long call `+1 C 590`, +358.9% | bull call spread `+1 C 522.5 / -1 C 570`, +123.6% | iron condor `-1 P 510 / +1 P 470 / -1 C 570 / +1 C 610`, +81.7% | iron condor `-1 P 470 / +1 P 440 / -1 C 517.5 / +1 C 547.5`, +126.5% | bear put spread `+1 P 480 / -1 P 430`, +197.8% | long strangle `+1 P 440 / +1 C 590`, +262.7% |
| AMZN | 2026-11-20 (28d) | bull call spread `+1 C 272.5 / -1 C 290`, +370.0% | bull call spread `+1 C 255 / -1 C 262.5`, +138.9% | iron condor `-1 P 247.5 / +1 P 232.5 / -1 C 257.5 / +1 C 272.5`, +92.0% | iron condor `-1 P 230 / +1 P 225 / -1 C 250 / +1 C 255`, +129.6% | bear put spread `+1 P 237.5 / -1 P 215`, +201.3% | bull call spread `+1 C 290 / -1 C 300`, +442.0% |
| DIA | 2026-11-20 (28d) | bull put spread `-1 P 575 / +1 P 537`, +514.9% | bull put spread `-1 P 542 / +1 P 527`, +122.0% | iron condor `-1 P 521 / +1 P 511 / -1 C 532 / +1 C 542`, +66.7% | iron condor `-1 P 511 / +1 P 501 / -1 C 527 / +1 C 537`, +92.2% | bear put spread `+1 P 516 / -1 P 490`, +188.0% | long strangle `+1 P 445 / +1 C 542`, +328.7% |
| GOOGL | 2026-11-20 (28d) | bull call spread `+1 C 345 / -1 C 375`, +357.7% | bull call spread `+1 C 330 / -1 C 340`, +124.9% | iron condor `-1 P 320 / +1 P 305 / -1 C 330 / +1 C 345`, +86.0% | iron condor `-1 P 300 / +1 P 290 / -1 C 322.5 / +1 C 332.5`, +114.3% | bear put spread `+1 P 305 / -1 P 290`, +202.1% | bull call spread `+1 C 360 / -1 C 385`, +409.7% |
| META | 2026-11-20 (28d) | bull call spread `+1 C 695 / -1 C 740`, +386.3% | bull call spread `+1 C 660 / -1 C 670`, +145.7% | iron condor `-1 P 625 / +1 P 615 / -1 C 670 / +1 C 680`, +95.4% | iron condor `-1 P 605 / +1 P 590 / -1 C 645 / +1 C 660`, +155.9% | bear put spread `+1 P 615 / -1 P 590`, +211.7% | bull call spread `+1 C 722.5 / -1 C 770`, +427.3% |
| MSFT | 2026-11-20 (28d) | long call `+1 C 565`, +358.6% | bull call spread `+1 C 525 / -1 C 555`, +122.6% | iron condor `-1 P 515 / +1 P 495 / -1 C 555 / +1 C 575`, +72.1% | iron condor `-1 P 505 / +1 P 485 / -1 C 525 / +1 C 545`, +113.1% | bear put spread `+1 P 510 / -1 P 470`, +199.2% | long call `+1 C 575`, +397.0% |
| NVDA | 2026-11-20 (28d) | bull call spread `+1 C 232.5 / -1 C 245`, +391.6% | bull call spread `+1 C 217.5 / -1 C 222.5`, +142.9% | iron condor `-1 P 207.5 / +1 P 197.5 / -1 C 222.5 / +1 C 232.5`, +96.4% | iron condor `-1 P 197.5 / +1 P 195 / -1 C 212.5 / +1 C 215`, +165.8% | bear put spread `+1 P 202.5 / -1 P 185`, +208.5% | bull call spread `+1 C 237.5 / -1 C 255`, +384.4% |
| SPY | 2026-11-20 (28d) | long call `+1 C 790`, +580.3% | bull put spread `-1 P 790 / +1 P 775`, +147.2% | iron condor `-1 P 752 / +1 P 745 / -1 C 783 / +1 C 790`, +65.9% | iron condor `-1 P 752 / +1 P 737 / -1 C 760 / +1 C 775`, +174.1% | bear put spread `+1 P 752 / -1 P 730`, +205.1% | long call `+1 C 790`, +593.1% |
| TSLA | 2026-11-20 (28d) | bull call spread `+1 C 410 / -1 C 430`, +369.9% | bull call spread `+1 C 380 / -1 C 395`, +136.2% | iron condor `-1 P 365 / +1 P 350 / -1 C 395 / +1 C 410`, +88.6% | iron condor `-1 P 350 / +1 P 342.5 / -1 C 372.5 / +1 C 380`, +149.3% | bear put spread `+1 P 357.5 / -1 P 335`, +203.7% | bull call spread `+1 C 420 / -1 C 445`, +400.1% |
| XLF | 2026-11-20 (28d) | long call `+1 C 59.5`, +1299.2% | bull call spread `+1 C 56 / -1 C 58`, +85.8% | iron condor `-1 P 55.5 / +1 P 53.5 / -1 C 57.5 / +1 C 59.5`, +43.8% | iron condor `-1 P 55 / +1 P 53.5 / -1 C 56 / +1 C 57.5`, +96.2% | long put `+1 P 55`, +244.7% | long strangle `+1 P 48 / +1 C 60.5`, +1484.8% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-10-23)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | GOOGL | 2026-10-23 | 2026-11-06 | 14 | 317.5/315 | 1.30 | 0.06 | 60.8% | 53.9% | 27.39% | 54963.1% |
| 2 | AMD | 2026-10-23 | 2026-11-06 | 14 | 507.5/502.5 | 2.45 | 1.40 | 60.8% | 54.2% | 19.60% | 10525.5% |
| 3 | GOOGL | 2026-10-23 | 2026-11-06 | 14 | 317.5/310 | 3.30 | 2.00 | 63.1% | 57.2% | 16.88% | 5733.5% |
| 4 | AMZN | 2026-10-23 | 2026-12-04 | 42 | 245/240 | 2.97 | 0.15 | 60.8% | 55.4% | 55.06% | 4422.9% |
| 5 | AMZN | 2026-10-23 | 2026-11-06 | 14 | 247.5/245 | 1.19 | 0.89 | 59.3% | 52.1% | 15.06% | 3775.0% |
| 6 | AMD | 2026-10-23 | 2026-12-04 | 42 | 510/505 | 2.96 | 0.21 | 60.8% | 53.4% | 49.11% | 3120.6% |
| 7 | AAPL | 2026-10-23 | 2026-11-06 | 14 | 345/340 | 1.92 | 1.65 | 69.9% | 61.1% | 14.13% | 3039.1% |
| 8 | AMD | 2026-10-23 | 2026-11-06 | 14 | 507.5/495 | 5.38 | 4.45 | 63.1% | 57.3% | 14.06% | 2985.5% |
| 9 | AMD | 2026-10-23 | 2026-11-06 | 14 | 507.5/485 | 9.15 | 7.90 | 69.9% | 61.0% | 13.75% | 2773.0% |
| 10 | AMD | 2026-10-23 | 2026-11-06 | 14 | 495/485 | 3.77 | 2.40 | 70.2% | 62.0% | 13.39% | 2547.0% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-10-23)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-20 | 645/610 | 0.35 | 0.32 | 0.05 | +0.29 | 84.8% | 99.8% | 98.7% | 99.0% | +0.8 pp | 0.23 |
| 2 | SPY | 2026-12-04 | 610/570 | 0.37 | 0.33 | 0.06 | +0.31 | 84.7% | 99.8% | 98.8% | 99.1% | +0.7 pp | 0.22 |
| 3 | DIA | 2026-12-18 | 430/390 | 0.40 | 0.21 | 0.06 | +0.33 | 84.1% | 99.8% | 98.5% | 99.0% | +0.8 pp | 0.22 |
| 4 | SPY | 2026-12-04 | 625/570 | 0.57 | 0.53 | 0.09 | +0.48 | 84.1% | 99.8% | 98.5% | 99.0% | +0.8 pp | 0.23 |
| 5 | SPY | 2026-11-20 | 665/610 | 0.66 | 0.63 | 0.11 | +0.55 | 83.9% | 99.6% | 98.0% | 98.8% | +0.8 pp | 0.25 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,848, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,536 eligible spreads of the latest session the median annualised return is 0.9% under the risk-neutral CDF and 83.7% after calibration, against a cash rate of 3.6%.

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
