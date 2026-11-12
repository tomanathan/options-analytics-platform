# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-11 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-11 | 1,219 | 3,861 | 3,766 | 47,688 |
| AMD | 2020-01-06 | 2026-11-11 | 1,216 | 3,855 | 3,759 | 47,708 |
| AMZN | 2020-01-06 | 2026-11-11 | 1,215 | 3,850 | 3,755 | 47,381 |
| DIA | 2020-01-06 | 2026-11-11 | 1,217 | 3,869 | 3,753 | 47,093 |
| GOOGL | 2020-01-06 | 2026-11-11 | 1,210 | 3,836 | 3,741 | 47,244 |
| META | 2022-07-01 | 2026-11-11 | 850 | 2,754 | 2,658 | 33,477 |
| MSFT | 2020-01-06 | 2026-11-11 | 1,205 | 3,815 | 3,721 | 46,968 |
| NVDA | 2020-01-06 | 2026-11-11 | 1,214 | 3,838 | 3,745 | 46,828 |
| SPY | 2020-01-06 | 2026-11-11 | 1,207 | 3,865 | 3,761 | 46,683 |
| TSLA | 2021-01-04 | 2026-11-11 | 1,065 | 3,393 | 3,298 | 41,694 |
| XLF | 2020-01-06 | 2026-11-11 | 1,207 | 3,838 | 3,741 | 47,341 |

In total: 1,868,846 quotes on 535,438 contracts, in 40,774 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,463 | 96.8% | enters the calibration sample |
| `unsettled` | 1,076 | 2.6% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1265 | 0.1291 | +0.0026 |
| Log loss (nats) | 0.3917 | 0.3962 | +0.0046 |
| Expected calibration error | 0.0336 | 0.0179 | -0.0157 |

Brier change +0.0026 (95% cluster-bootstrap interval -0.0004 to +0.0056, resampling expiration dates; negative means calibration helped) over 452,572 predictions, 35,549 snapshots and 891 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 143,756 | 0.1020 | 0.1046 | 0.0184 | 0.0227 |
| 21-35d | 143,939 | 0.1275 | 0.1307 | 0.0305 | 0.0229 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,702 | 0.1189 | 0.1198 | 0.0425 | 0.0160 |
| AMD | 42,282 | 0.1814 | 0.1859 | 0.0387 | 0.0419 |
| AMZN | 42,019 | 0.1349 | 0.1399 | 0.0279 | 0.0279 |
| DIA | 41,698 | 0.0626 | 0.0630 | 0.0263 | 0.0156 |
| GOOGL | 41,964 | 0.1327 | 0.1327 | 0.0497 | 0.0157 |
| META | 33,477 | 0.1536 | 0.1561 | 0.0422 | 0.0182 |
| MSFT | 41,860 | 0.1186 | 0.1222 | 0.0215 | 0.0270 |
| NVDA | 41,424 | 0.1578 | 0.1573 | 0.0756 | 0.0168 |
| SPY | 41,398 | 0.0688 | 0.0697 | 0.0270 | 0.0106 |
| TSLA | 41,694 | 0.1819 | 0.1915 | 0.0092 | 0.0642 |
| XLF | 42,054 | 0.0857 | 0.0871 | 0.0224 | 0.0208 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 100,979 | 0.1263 | 0.1264 | 0.0255 | 0.0207 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,424 | 0.0363 | 0.0188 | 168,474 | 0.0317 | 0.0392 |
| 0.1-0.2 | 56,194 | 0.1468 | 0.1125 | 62,584 | 0.1481 | 0.1922 |
| 0.2-0.3 | 40,516 | 0.2471 | 0.2076 | 39,472 | 0.2567 | 0.2826 |
| 0.3-0.4 | 33,087 | 0.3502 | 0.2988 | 30,595 | 0.3606 | 0.4043 |
| 0.4-0.5 | 35,621 | 0.4517 | 0.4050 | 25,010 | 0.4464 | 0.4705 |
| 0.5-0.6 | 27,652 | 0.5529 | 0.5005 | 28,576 | 0.5471 | 0.5681 |
| 0.6-0.7 | 33,278 | 0.6504 | 0.5969 | 32,486 | 0.6544 | 0.6603 |
| 0.7-0.8 | 30,946 | 0.7481 | 0.6921 | 21,113 | 0.7503 | 0.7533 |
| 0.8-0.9 | 25,039 | 0.8481 | 0.8184 | 16,654 | 0.8509 | 0.8641 |
| 0.9-1.0 | 32,815 | 0.9619 | 0.9564 | 27,608 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-11)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-11 | 2026-12-31 | 50 | 752/737 | 3.56 | 3.63 | 79.8% | 6.87% | 62.4% | 20.0% | 0.13 | 15.8% |
| 2 | AAPL | 2026-11-11 | 2027-01-15 | 65 | 355/340 | 5.05 | 5.25 | 69.9% | 9.59% | 67.2% | 16.6% | 0.14 | 10.0% |
| 3 | SPY | 2026-11-11 | 2026-12-31 | 50 | 737/729 | 1.33 | 1.38 | 86.1% | 5.29% | 45.7% | 23.0% | 0.12 | 9.6% |
| 4 | GOOGL | 2026-11-11 | 2027-01-15 | 65 | 290/275 | 5.15 | 5.45 | 69.5% | 11.15% | 81.0% | 18.4% | 0.15 | 8.0% |
| 5 | SPY | 2026-11-11 | 2026-12-31 | 50 | 745/737 | 1.69 | 1.74 | 81.0% | 6.11% | 54.2% | 20.2% | 0.12 | 6.8% |
| 6 | AMZN | 2026-11-11 | 2027-01-15 | 65 | 265/250 | 5.30 | 5.60 | 68.0% | 10.33% | 73.7% | 16.3% | 0.14 | 6.0% |
| 7 | GOOGL | 2026-11-11 | 2027-01-15 | 65 | 290/280 | 3.51 | 3.85 | 69.5% | 12.02% | 89.2% | 18.2% | 0.15 | 5.0% |
| 8 | AAPL | 2026-11-11 | 2027-01-15 | 65 | 355/345 | 3.55 | 3.80 | 68.1% | 10.79% | 77.7% | 16.6% | 0.14 | 4.8% |
| 9 | SPY | 2026-11-11 | 2026-12-31 | 50 | 752/729 | 4.94 | 5.01 | 79.8% | 6.29% | 56.1% | 20.8% | 0.13 | 4.8% |
| 10 | SPY | 2026-11-11 | 2026-12-31 | 50 | 752/745 | 1.81 | 1.88 | 76.2% | 7.80% | 73.0% | 19.8% | 0.13 | 4.7% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-11)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-11 (30d) | long call `+1 C 375`, +379.9% | bull call spread `+1 C 360 / -1 C 370`, +128.1% | iron condor `-1 P 355 / +1 P 345 / -1 C 365 / +1 C 375`, +67.0% | iron condor `-1 P 345 / +1 P 335 / -1 C 360 / +1 C 370`, +102.3% | bear put spread `+1 P 350 / -1 P 320`, +189.4% | long call `+1 C 385`, +474.5% |
| AMD | 2026-12-11 (30d) | long call `+1 C 665`, +427.5% | bull call spread `+1 C 565 / -1 C 620`, +116.5% | iron condor `-1 P 540 / +1 P 485 / -1 C 595 / +1 C 650`, +67.1% | iron condor `-1 P 485 / +1 P 455 / -1 C 555 / +1 C 585`, +90.9% | bear put spread `+1 P 510 / -1 P 455`, +199.5% | long call `+1 C 690`, +580.5% |
| AMZN | 2026-12-11 (30d) | bull call spread `+1 C 285 / -1 C 300`, +356.7% | bull call spread `+1 C 270 / -1 C 285`, +120.6% | iron condor `-1 P 265 / +1 P 250 / -1 C 280 / +1 C 295`, +63.9% | iron condor `-1 P 250 / +1 P 240 / -1 C 270 / +1 C 280`, +88.1% | bear put spread `+1 P 255 / -1 P 240`, +179.1% | long call `+1 C 295`, +390.1% |
| DIA | 2026-12-11 (30d) | long call `+1 C 540`, +374.2% | bull put spread `-1 P 540 / +1 P 530`, +126.0% | iron condor `-1 P 524 / +1 P 514 / -1 C 535 / +1 C 545`, +71.6% | iron condor `-1 P 514 / +1 P 509 / -1 C 530 / +1 C 535`, +89.6% | bear put spread `+1 P 519 / -1 P 503`, +196.6% | long strangle `+1 P 460 / +1 C 545`, +315.2% |
| GOOGL | 2026-12-11 (30d) | long call `+1 C 310`, +312.5% | bull call spread `+1 C 295 / -1 C 315`, +102.9% | iron condor `-1 P 290 / +1 P 270 / -1 C 305 / +1 C 325`, +61.1% | iron condor `-1 P 280 / +1 P 265 / -1 C 295 / +1 C 310`, +86.0% | bear put spread `+1 P 280 / -1 P 265`, +191.2% | long strangle `+1 P 250 / +1 C 325`, +284.5% |
| META | 2026-12-11 (30d) | bull call spread `+1 C 680 / -1 C 740`, +354.0% | bull call spread `+1 C 640 / -1 C 680`, +117.9% | iron condor `-1 P 615 / +1 P 590 / -1 C 665 / +1 C 690`, +75.7% | iron condor `-1 P 590 / +1 P 565 / -1 C 630 / +1 C 655`, +118.4% | bear put spread `+1 P 605 / -1 P 550`, +197.0% | long strangle `+1 P 535 / +1 C 705`, +276.9% |
| MSFT | 2026-12-11 (30d) | long call `+1 C 565`, +357.4% | bull call spread `+1 C 525 / -1 C 550`, +105.0% | iron condor `-1 P 520 / +1 P 490 / -1 C 535 / +1 C 565`, +63.9% | iron condor `-1 P 505 / +1 P 480 / -1 C 525 / +1 C 550`, +77.8% | bear put spread `+1 P 500 / -1 P 470`, +178.6% | long call `+1 C 565`, +403.4% |
| NVDA | 2026-12-11 (30d) | bull call spread `+1 C 195 / -1 C 210`, +363.9% | bull call spread `+1 C 180 / -1 C 185`, +131.9% | iron condor `-1 P 170 / +1 P 160 / -1 C 185 / +1 C 195`, +84.8% | iron condor `-1 P 155 / +1 P 150 / -1 C 175 / +1 C 180`, +133.5% | bear put spread `+1 P 160 / -1 P 145`, +203.7% | long strangle `+1 P 150 / +1 C 195`, +257.7% |
| SPY | 2026-12-11 (30d) | long call `+1 C 790`, +537.9% | bull call spread `+1 C 775 / -1 C 783`, +134.0% | iron condor `-1 P 752 / +1 P 745 / -1 C 783 / +1 C 790`, +69.1% | iron condor `-1 P 752 / +1 P 745 / -1 C 760 / +1 C 767`, +175.9% | bear put spread `+1 P 752 / -1 P 745`, +212.5% | long strangle `+1 P 665 / +1 C 790`, +384.7% |
| TSLA | 2026-12-11 (30d) | bull call spread `+1 C 430 / -1 C 460`, +353.1% | bull call spread `+1 C 400 / -1 C 420`, +117.5% | iron condor `-1 P 390 / +1 P 365 / -1 C 415 / +1 C 440`, +75.8% | iron condor `-1 P 360 / +1 P 350 / -1 C 395 / +1 C 405`, +103.9% | bear put spread `+1 P 375 / -1 P 340`, +188.5% | long call `+1 C 440`, +335.6% |
| XLF | 2026-12-11 (30d) | long call `+1 C 60.5`, +243.7% | bull call spread `+1 C 59 / -1 C 61`, +87.0% | iron condor `-1 P 58 / +1 P 55 / -1 C 60 / +1 C 63`, +21.8% | iron condor `-1 P 58 / +1 P 56.5 / -1 C 59 / +1 C 60.5`, +46.1% | long put `+1 P 58`, +224.0% | long strangle `+1 P 51.5 / +1 C 61`, +323.6% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-11)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | NVDA | 2026-11-11 | 2026-11-25 | 14 | 170/167.5 | 1.30 | 0.35 | 62.8% | 57.0% | 31.81% | 133813.0% |
| 2 | GOOGL | 2026-11-11 | 2026-11-25 | 14 | 287.5/282.5 | 2.27 | 0.35 | 69.5% | 60.9% | 28.48% | 68675.0% |
| 3 | TSLA | 2026-11-11 | 2026-11-25 | 14 | 390/382.5 | 3.65 | 2.20 | 63.9% | 59.2% | 26.33% | 44228.3% |
| 4 | AAPL | 2026-11-11 | 2026-11-25 | 14 | 355/352.5 | 1.38 | 0.50 | 55.0% | 47.9% | 26.04% | 41596.0% |
| 5 | TSLA | 2026-11-11 | 2026-11-25 | 14 | 390/380 | 4.62 | 3.40 | 63.9% | 59.2% | 22.69% | 20562.4% |
| 6 | TSLA | 2026-11-11 | 2026-11-25 | 14 | 387.5/380 | 3.32 | 1.15 | 65.1% | 59.6% | 19.63% | 10592.3% |
| 7 | AMD | 2026-11-11 | 2026-11-25 | 14 | 552.5/537.5 | 7.10 | 2.55 | 63.7% | 57.9% | 17.76% | 7001.0% |
| 8 | NVDA | 2026-11-11 | 2026-11-25 | 14 | 170/162.5 | 3.05 | 2.35 | 68.2% | 60.8% | 17.40% | 6452.7% |
| 9 | META | 2026-11-11 | 2026-11-25 | 14 | 622.5/610 | 5.18 | 1.50 | 67.9% | 60.0% | 17.31% | 6315.2% |
| 10 | TSLA | 2026-11-11 | 2026-11-25 | 14 | 390/375 | 6.20 | 4.80 | 67.9% | 59.8% | 16.91% | 5772.8% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-11)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-31 | 608/570 | 0.32 | 0.30 | 0.05 | +0.27 | 83.4% | 99.8% | 98.9% | 99.2% | +0.6 pp | 0.19 |
| 2 | SPY | 2026-12-24 | 645/610 | 0.43 | 0.39 | 0.07 | +0.36 | 82.8% | 99.7% | 98.2% | 98.8% | +0.9 pp | 0.24 |
| 3 | SPY | 2026-12-11 | 665/625 | 0.40 | 0.38 | 0.07 | +0.32 | 82.3% | 99.8% | 98.4% | 99.0% | +0.7 pp | 0.21 |
| 4 | SPY | 2026-12-31 | 627/570 | 0.56 | 0.54 | 0.10 | +0.46 | 82.2% | 99.8% | 98.5% | 99.0% | +0.7 pp | 0.21 |
| 5 | SPY | 2026-12-24 | 625/570 | 0.43 | 0.41 | 0.08 | +0.36 | 82.0% | 99.8% | 98.8% | 99.2% | +0.5 pp | 0.18 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 62 breaches in 53,504, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,406 eligible spreads of the latest session the median annualised return is 1.1% under the risk-neutral CDF and 65.0% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.6 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.1%, right tail uncovered 15.1%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
