# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-12 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-12 | 1,220 | 3,865 | 3,766 | 47,688 |
| AMD | 2020-01-06 | 2026-11-12 | 1,217 | 3,859 | 3,759 | 47,708 |
| AMZN | 2020-01-06 | 2026-11-12 | 1,216 | 3,854 | 3,755 | 47,381 |
| DIA | 2020-01-06 | 2026-11-12 | 1,218 | 3,873 | 3,753 | 47,093 |
| GOOGL | 2020-01-06 | 2026-11-12 | 1,211 | 3,840 | 3,741 | 47,244 |
| META | 2022-07-01 | 2026-11-12 | 851 | 2,758 | 2,658 | 33,477 |
| MSFT | 2020-01-06 | 2026-11-12 | 1,206 | 3,819 | 3,721 | 46,968 |
| NVDA | 2020-01-06 | 2026-11-12 | 1,215 | 3,842 | 3,745 | 46,828 |
| SPY | 2020-01-06 | 2026-11-12 | 1,208 | 3,869 | 3,761 | 46,683 |
| TSLA | 2021-01-04 | 2026-11-12 | 1,066 | 3,397 | 3,298 | 41,694 |
| XLF | 2020-01-06 | 2026-11-12 | 1,208 | 3,842 | 3,741 | 47,341 |

In total: 1,870,950 quotes on 536,008 contracts, in 40,818 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,463 | 96.7% | enters the calibration sample |
| `unsettled` | 1,120 | 2.7% | the expiration is after the last priced session, so there is no outcome yet |
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

## Top 10 to enter (2026-11-12)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-12 | 2026-12-31 | 49 | 757/750 | 2.22 | 2.30 | 74.2% | 9.96% | 102.8% | 19.3% | 0.15 | 28.4% |
| 2 | SPY | 2026-11-12 | 2026-12-31 | 49 | 757/742 | 4.36 | 4.45 | 74.7% | 8.67% | 85.8% | 19.5% | 0.14 | 18.0% |
| 3 | SPY | 2026-11-12 | 2026-12-31 | 49 | 750/734 | 3.77 | 3.85 | 79.8% | 6.85% | 63.8% | 20.1% | 0.13 | 15.0% |
| 4 | SPY | 2026-11-12 | 2026-12-31 | 49 | 750/742 | 2.06 | 2.14 | 77.5% | 7.65% | 73.1% | 19.6% | 0.13 | 11.6% |
| 5 | SPY | 2026-11-12 | 2026-12-31 | 49 | 734/727 | 1.15 | 1.22 | 86.1% | 5.37% | 47.7% | 23.2% | 0.12 | 7.1% |
| 6 | SPY | 2026-11-12 | 2026-12-31 | 49 | 750/727 | 5.00 | 5.07 | 79.8% | 6.38% | 58.5% | 20.9% | 0.13 | 6.2% |
| 7 | SPY | 2026-11-12 | 2026-12-31 | 49 | 742/727 | 2.86 | 2.93 | 82.3% | 5.76% | 51.7% | 21.8% | 0.12 | 4.2% |
| 8 | SPY | 2026-11-12 | 2026-12-31 | 49 | 727/712 | 1.93 | 1.98 | 88.4% | 4.15% | 35.3% | 24.1% | 0.11 | 3.8% |
| 9 | SPY | 2026-11-12 | 2026-12-31 | 49 | 757/734 | 6.07 | 6.16 | 74.7% | 7.72% | 74.0% | 19.8% | 0.14 | 3.6% |
| 10 | AAPL | 2026-11-12 | 2027-01-15 | 64 | 350/335 | 4.15 | 4.38 | 74.7% | 8.47% | 59.0% | 19.1% | 0.14 | 3.4% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-12)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-11 (29d) | long call `+1 C 375`, +366.3% | bull call spread `+1 C 360 / -1 C 370`, +118.7% | iron condor `-1 P 350 / +1 P 340 / -1 C 365 / +1 C 375`, +63.3% | iron condor `-1 P 345 / +1 P 335 / -1 C 355 / +1 C 365`, +118.7% | bear put spread `+1 P 350 / -1 P 325`, +199.9% | long call `+1 C 375`, +351.0% |
| AMD | 2026-12-11 (29d) | long call `+1 C 660`, +359.6% | bull put spread `-1 P 645 / +1 P 590`, +110.9% | iron condor `-1 P 580 / +1 P 525 / -1 C 620 / +1 C 675`, +64.5% | iron condor `-1 P 500 / +1 P 470 / -1 C 590 / +1 C 620`, +99.3% | bear put spread `+1 P 550 / -1 P 500`, +197.8% | long call `+1 C 730`, +417.9% |
| AMZN | 2026-12-11 (29d) | bull call spread `+1 C 285 / -1 C 310`, +368.5% | bull call spread `+1 C 270 / -1 C 285`, +119.6% | iron condor `-1 P 265 / +1 P 255 / -1 C 285 / +1 C 295`, +71.5% | iron condor `-1 P 260 / +1 P 245 / -1 C 270 / +1 C 285`, +93.9% | bear put spread `+1 P 260 / -1 P 235`, +194.7% | long call `+1 C 300`, +412.2% |
| DIA | 2026-12-11 (29d) | long call `+1 C 543`, +379.5% | bull put spread `-1 P 538 / +1 P 527.5`, +119.3% | iron condor `-1 P 517 / +1 P 507 / -1 C 533 / +1 C 543`, +50.7% | iron condor `-1 P 512 / +1 P 507 / -1 C 522.5 / +1 C 527.5`, +100.0% | bear put spread `+1 P 517 / -1 P 490`, +187.3% | long strangle `+1 P 445 / +1 C 543`, +311.9% |
| GOOGL | 2026-12-11 (29d) | long call `+1 C 315`, +305.5% | bull call spread `+1 C 300 / -1 C 315`, +118.4% | iron condor `-1 P 295 / +1 P 280 / -1 C 315 / +1 C 330`, +59.1% | iron condor `-1 P 285 / +1 P 270 / -1 C 300 / +1 C 315`, +92.1% | bear put spread `+1 P 285 / -1 P 260`, +183.8% | bull call spread `+1 C 330 / -1 C 350`, +351.6% |
| META | 2026-12-11 (29d) | bull call spread `+1 C 675 / -1 C 735`, +353.4% | bull call spread `+1 C 635 / -1 C 660`, +127.5% | iron condor `-1 P 610 / +1 P 585 / -1 C 660 / +1 C 685`, +77.9% | iron condor `-1 P 585 / +1 P 560 / -1 C 625 / +1 C 650`, +124.1% | bear put spread `+1 P 600 / -1 P 560`, +204.4% | long strangle `+1 P 560 / +1 C 700`, +269.8% |
| MSFT | 2026-12-11 (29d) | long call `+1 C 555`, +338.3% | bull put spread `-1 P 545 / +1 P 525`, +106.0% | iron condor `-1 P 520 / +1 P 480 / -1 C 535 / +1 C 575`, +49.5% | iron condor `-1 P 500 / +1 P 480 / -1 C 525 / +1 C 545`, +80.3% | bear put spread `+1 P 520 / -1 P 480`, +169.4% | long strangle `+1 P 460 / +1 C 575`, +247.1% |
| NVDA | 2026-12-11 (29d) | long call `+1 C 190`, +361.8% | bull call spread `+1 C 170 / -1 C 180`, +131.1% | iron condor `-1 P 165 / +1 P 150 / -1 C 175 / +1 C 190`, +72.2% | iron condor `-1 P 145 / +1 P 140 / -1 C 170 / +1 C 175`, +102.7% | bear put spread `+1 P 150 / -1 P 135`, +191.2% | long strangle `+1 P 145 / +1 C 190`, +256.2% |
| SPY | 2026-12-11 (29d) | long call `+1 C 787`, +558.4% | bull call spread `+1 C 772 / -1 C 780`, +138.1% | iron condor `-1 P 757 / +1 P 750 / -1 C 780 / +1 C 787`, +89.6% | iron condor `-1 P 757 / +1 P 750 / -1 C 765 / +1 C 772`, +163.7% | bear put spread `+1 P 750 / -1 P 742`, +210.9% | long strangle `+1 P 645 / +1 C 787`, +394.3% |
| TSLA | 2026-12-11 (29d) | long call `+1 C 435`, +325.5% | bull call spread `+1 C 400 / -1 C 430`, +122.2% | iron condor `-1 P 395 / +1 P 365 / -1 C 415 / +1 C 445`, +66.6% | iron condor `-1 P 360 / +1 P 340 / -1 C 400 / +1 C 420`, +102.3% | bear put spread `+1 P 380 / -1 P 350`, +189.3% | long strangle `+1 P 340 / +1 C 445`, +245.9% |
| XLF | 2026-12-11 (29d) | long call `+1 C 60.5`, +281.7% | bull call spread `+1 C 59 / -1 C 60.5`, +71.4% | bull put spread `-1 P 59 / +1 P 56`, +21.4% | iron condor `-1 P 57.5 / +1 P 56 / -1 C 59 / +1 C 60.5`, +32.4% | long put `+1 P 58`, +156.2% | long call `+1 C 60.5`, +321.1% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-12)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMD | 2026-11-12 | 2026-11-27 | 15 | 572.5/567.5 | 3.00 | 0.20 | 62.8% | 56.9% | 55.90% | 4929356.8% |
| 2 | GOOGL | 2026-11-12 | 2026-11-27 | 15 | 290/287.5 | 1.08 | 0.45 | 70.5% | 63.2% | 26.62% | 31081.4% |
| 3 | AMD | 2026-11-12 | 2026-11-27 | 15 | 562.5/550 | 5.03 | 2.75 | 70.9% | 64.9% | 20.88% | 9993.7% |
| 4 | NVDA | 2026-11-12 | 2026-11-27 | 15 | 155/152.5 | 0.92 | 0.50 | 74.2% | 65.9% | 18.18% | 5725.0% |
| 5 | AMD | 2026-11-12 | 2026-11-27 | 15 | 572.5/550 | 9.12 | 6.65 | 70.9% | 64.9% | 17.24% | 4698.4% |
| 6 | AMD | 2026-11-12 | 2026-11-27 | 15 | 580/567.5 | 5.80 | 3.50 | 60.7% | 56.0% | 14.62% | 2669.3% |
| 7 | AMD | 2026-11-12 | 2026-11-27 | 15 | 562.5/540 | 8.03 | 5.55 | 73.5% | 65.7% | 14.61% | 2662.3% |
| 8 | TSLA | 2026-11-12 | 2026-11-27 | 15 | 390/385 | 1.95 | 1.40 | 69.5% | 60.9% | 14.39% | 2532.9% |
| 9 | AMD | 2026-11-12 | 2026-11-27 | 15 | 572.5/540 | 12.12 | 9.45 | 70.9% | 64.9% | 14.04% | 2345.1% |
| 10 | GOOGL | 2026-11-12 | 2026-11-27 | 15 | 297.5/295 | 1.17 | 0.80 | 60.7% | 52.8% | 13.53% | 2094.6% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-12)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-24 | 605/570 | 0.29 | 0.25 | 0.05 | +0.24 | 83.2% | 99.9% | 98.9% | 99.2% | +0.7 pp | 0.18 |
| 2 | SPY | 2026-12-31 | 625/606 | 0.28 | 0.26 | 0.05 | +0.23 | 83.0% | 99.7% | 98.3% | 98.5% | +1.2 pp | 0.25 |
| 3 | SPY | 2026-12-31 | 625/570 | 0.63 | 0.62 | 0.11 | +0.53 | 82.8% | 99.7% | 98.3% | 98.8% | +0.8 pp | 0.23 |
| 4 | SPY | 2026-12-11 | 660/625 | 0.42 | 0.40 | 0.07 | +0.35 | 82.8% | 99.7% | 98.2% | 98.8% | +0.9 pp | 0.24 |
| 5 | SPY | 2026-12-31 | 606/570 | 0.35 | 0.34 | 0.06 | +0.29 | 82.7% | 99.8% | 98.7% | 99.0% | +0.7 pp | 0.21 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 62 breaches in 53,504, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,393 eligible spreads of the latest session the median annualised return is 0.9% under the risk-neutral CDF and 78.1% after calibration, against a cash rate of 3.6%.

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
