# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-06 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-06 | 1,216 | 3,849 | 3,763 | 47,650 |
| AMD | 2020-01-06 | 2026-11-06 | 1,213 | 3,843 | 3,756 | 47,674 |
| AMZN | 2020-01-06 | 2026-11-06 | 1,212 | 3,838 | 3,752 | 47,342 |
| DIA | 2020-01-06 | 2026-11-06 | 1,214 | 3,857 | 3,753 | 47,093 |
| GOOGL | 2020-01-06 | 2026-11-06 | 1,207 | 3,824 | 3,738 | 47,205 |
| META | 2022-07-01 | 2026-11-06 | 847 | 2,742 | 2,655 | 33,454 |
| MSFT | 2020-01-06 | 2026-11-06 | 1,202 | 3,804 | 3,718 | 46,937 |
| NVDA | 2020-01-06 | 2026-11-06 | 1,211 | 3,826 | 3,742 | 46,789 |
| SPY | 2020-01-06 | 2026-11-06 | 1,204 | 3,853 | 3,759 | 46,668 |
| TSLA | 2021-01-04 | 2026-11-06 | 1,062 | 3,381 | 3,295 | 41,664 |
| XLF | 2020-01-06 | 2026-11-06 | 1,204 | 3,826 | 3,737 | 47,289 |

In total: 1,862,579 quotes on 532,900 contracts, in 40,643 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,433 | 97.0% | enters the calibration sample |
| `unsettled` | 975 | 2.4% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1265 | 0.1291 | +0.0026 |
| Log loss (nats) | 0.3915 | 0.3961 | +0.0046 |
| Expected calibration error | 0.0336 | 0.0178 | -0.0159 |

Brier change +0.0026 (95% cluster-bootstrap interval -0.0003 to +0.0064, resampling expiration dates; negative means calibration helped) over 452,232 predictions, 35,519 snapshots and 888 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 143,416 | 0.1019 | 0.1045 | 0.0186 | 0.0225 |
| 21-35d | 143,939 | 0.1275 | 0.1307 | 0.0305 | 0.0229 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,664 | 0.1190 | 0.1199 | 0.0425 | 0.0161 |
| AMD | 42,248 | 0.1814 | 0.1859 | 0.0388 | 0.0419 |
| AMZN | 41,980 | 0.1349 | 0.1400 | 0.0277 | 0.0281 |
| DIA | 41,698 | 0.0626 | 0.0630 | 0.0263 | 0.0156 |
| GOOGL | 41,925 | 0.1327 | 0.1326 | 0.0501 | 0.0155 |
| META | 33,454 | 0.1537 | 0.1561 | 0.0421 | 0.0183 |
| MSFT | 41,829 | 0.1186 | 0.1223 | 0.0214 | 0.0270 |
| NVDA | 41,385 | 0.1575 | 0.1570 | 0.0762 | 0.0165 |
| SPY | 41,383 | 0.0688 | 0.0697 | 0.0271 | 0.0105 |
| TSLA | 41,664 | 0.1819 | 0.1916 | 0.0091 | 0.0641 |
| XLF | 42,002 | 0.0857 | 0.0871 | 0.0224 | 0.0209 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 100,639 | 0.1263 | 0.1263 | 0.0258 | 0.0206 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,309 | 0.0363 | 0.0187 | 168,349 | 0.0317 | 0.0392 |
| 0.1-0.2 | 56,164 | 0.1469 | 0.1125 | 62,538 | 0.1481 | 0.1921 |
| 0.2-0.3 | 40,486 | 0.2471 | 0.2075 | 39,442 | 0.2567 | 0.2825 |
| 0.3-0.4 | 33,058 | 0.3502 | 0.2987 | 30,580 | 0.3606 | 0.4043 |
| 0.4-0.5 | 35,607 | 0.4517 | 0.4049 | 24,993 | 0.4464 | 0.4703 |
| 0.5-0.6 | 27,634 | 0.5529 | 0.5004 | 28,554 | 0.5471 | 0.5680 |
| 0.6-0.7 | 33,252 | 0.6504 | 0.5968 | 32,457 | 0.6544 | 0.6601 |
| 0.7-0.8 | 30,921 | 0.7481 | 0.6919 | 21,099 | 0.7503 | 0.7532 |
| 0.8-0.9 | 25,017 | 0.8481 | 0.8183 | 16,636 | 0.8509 | 0.8640 |
| 0.9-1.0 | 32,784 | 0.9619 | 0.9564 | 27,584 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-06)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-06 | 2026-12-31 | 55 | 735/721 | 4.13 | 4.31 | 74.7% | 9.30% | 80.5% | 19.7% | 0.14 | 14.5% |
| 2 | SPY | 2026-11-06 | 2026-12-31 | 55 | 735/728 | 2.12 | 2.30 | 74.2% | 10.70% | 96.3% | 20.8% | 0.16 | 9.3% |
| 3 | SPY | 2026-11-06 | 2026-12-31 | 55 | 735/713 | 6.14 | 6.31 | 74.7% | 8.48% | 71.6% | 19.8% | 0.14 | 8.8% |
| 4 | SPY | 2026-11-06 | 2026-12-31 | 55 | 713/691 | 4.04 | 4.17 | 84.0% | 5.77% | 45.1% | 22.4% | 0.13 | 7.4% |
| 5 | SPY | 2026-11-06 | 2026-12-31 | 55 | 706/691 | 2.53 | 2.66 | 85.5% | 5.59% | 43.4% | 23.4% | 0.12 | 6.1% |
| 6 | SPY | 2026-11-06 | 2026-12-31 | 55 | 721/706 | 3.35 | 3.50 | 79.9% | 6.70% | 53.7% | 20.2% | 0.12 | 5.2% |
| 7 | SPY | 2026-11-06 | 2026-12-31 | 55 | 728/706 | 5.36 | 5.51 | 77.5% | 7.09% | 57.5% | 19.6% | 0.13 | 5.1% |
| 8 | SPY | 2026-11-06 | 2026-12-31 | 55 | 728/691 | 8.03 | 8.17 | 79.8% | 6.45% | 51.4% | 20.8% | 0.13 | 4.9% |
| 9 | SPY | 2026-11-06 | 2026-12-31 | 55 | 721/713 | 1.84 | 2.00 | 79.8% | 7.15% | 58.1% | 19.9% | 0.12 | 3.8% |
| 10 | SPY | 2026-11-06 | 2026-12-31 | 55 | 728/713 | 3.85 | 4.00 | 76.2% | 7.53% | 61.9% | 19.2% | 0.13 | 3.7% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-06)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-04 (28d) | long call `+1 C 365`, +348.4% | bull call spread `+1 C 350 / -1 C 365`, +106.6% | iron condor `-1 P 340 / +1 P 330 / -1 C 355 / +1 C 365`, +49.1% | iron condor `-1 P 330 / +1 P 320 / -1 C 345 / +1 C 355`, +88.4% | bear put spread `+1 P 340 / -1 P 310`, +167.2% | long strangle `+1 P 300 / +1 C 370`, +214.1% |
| AMD | 2026-12-04 (28d) | long call `+1 C 505`, +350.9% | bull call spread `+1 C 460 / -1 C 495`, +105.9% | iron condor `-1 P 440 / +1 P 405 / -1 C 495 / +1 C 530`, +69.7% | iron condor `-1 P 395 / +1 P 360 / -1 C 450 / +1 C 485`, +84.9% | long put `+1 P 405`, +166.9% | long strangle `+1 P 395 / +1 C 515`, +224.3% |
| AMZN | 2026-12-04 (28d) | bull call spread `+1 C 280 / -1 C 305`, +337.2% | bull call spread `+1 C 260 / -1 C 275`, +110.6% | iron condor `-1 P 255 / +1 P 240 / -1 C 275 / +1 C 290`, +51.8% | iron condor `-1 P 245 / +1 P 235 / -1 C 260 / +1 C 270`, +110.6% | bear put spread `+1 P 255 / -1 P 235`, +155.9% | long strangle `+1 P 235 / +1 C 285`, +212.6% |
| DIA | 2026-12-04 (28d) | long call `+1 C 532.5`, +370.4% | bull call spread `+1 C 517.5 / -1 C 532.5`, +108.0% | iron condor `-1 P 512 / +1 P 502 / -1 C 522.5 / +1 C 532.5`, +51.6% | iron condor `-1 P 507 / +1 P 497 / -1 C 517.5 / +1 C 527.5`, +82.9% | bear put spread `+1 P 507 / -1 P 480`, +185.6% | long call `+1 C 543`, +453.0% |
| GOOGL | 2026-12-04 (28d) | long call `+1 C 300`, +316.3% | bull call spread `+1 C 290 / -1 C 300`, +122.2% | iron condor `-1 P 280 / +1 P 260 / -1 C 295 / +1 C 315`, +50.4% | iron condor `-1 P 270 / +1 P 255 / -1 C 285 / +1 C 300`, +67.5% | bear put spread `+1 P 280 / -1 P 255`, +180.1% | bull call spread `+1 C 315 / -1 C 340`, +373.9% |
| META | 2026-12-04 (28d) | bull call spread `+1 C 670 / -1 C 730`, +342.4% | bull call spread `+1 C 615 / -1 C 660`, +121.6% | iron condor `-1 P 610 / +1 P 560 / -1 C 635 / +1 C 685`, +76.2% | iron condor `-1 P 575 / +1 P 550 / -1 C 620 / +1 C 645`, +98.4% | bear put spread `+1 P 590 / -1 P 535`, +191.3% | long strangle `+1 P 520 / +1 C 685`, +244.1% |
| MSFT | 2026-12-04 (28d) | long call `+1 C 575`, +357.0% | bull call spread `+1 C 545 / -1 C 560`, +107.2% | iron condor `-1 P 530 / +1 P 500 / -1 C 545 / +1 C 575`, +64.8% | iron condor `-1 P 515 / +1 P 490 / -1 C 535 / +1 C 560`, +85.0% | bear put spread `+1 P 515 / -1 P 465`, +183.9% | long strangle `+1 P 465 / +1 C 575`, +247.0% |
| NVDA | 2026-12-04 (28d) | bull call spread `+1 C 210 / -1 C 225`, +359.3% | bull call spread `+1 C 195 / -1 C 200`, +133.9% | iron condor `-1 P 185 / +1 P 170 / -1 C 200 / +1 C 215`, +85.0% | iron condor `-1 P 170 / +1 P 160 / -1 C 190 / +1 C 200`, +128.7% | bear put spread `+1 P 180 / -1 P 165`, +201.8% | long call `+1 C 220`, +423.5% |
| SPY | 2026-12-04 (28d) | long call `+1 C 779`, +659.9% | bull call spread `+1 C 757 / -1 C 765`, +132.9% | iron condor `-1 P 735 / +1 P 720 / -1 C 750 / +1 C 765`, +74.8% | iron condor `-1 P 720 / +1 P 705 / -1 C 750 / +1 C 765`, +122.7% | bear put spread `+1 P 730 / -1 P 715`, +211.3% | long call `+1 C 779`, +802.4% |
| TSLA | 2026-12-04 (28d) | bull call spread `+1 C 395 / -1 C 430`, +360.1% | bull call spread `+1 C 370 / -1 C 385`, +132.6% | iron condor `-1 P 355 / +1 P 335 / -1 C 385 / +1 C 405`, +85.7% | iron condor `-1 P 330 / +1 P 315 / -1 C 360 / +1 C 375`, +136.9% | bear put spread `+1 P 335 / -1 P 305`, +201.7% | long strangle `+1 P 305 / +1 C 410`, +246.2% |
| XLF | 2026-12-04 (28d) | long call `+1 C 59.5`, +284.9% | bull call spread `+1 C 57 / -1 C 59`, +70.9% | iron condor `-1 P 56.5 / +1 P 53.5 / -1 C 58.5 / +1 C 61.5`, +25.6% | iron condor `-1 P 55.5 / +1 P 53.5 / -1 C 57.5 / +1 C 59.5`, +49.4% | bear put spread `+1 P 57 / -1 P 51.5`, +148.6% | long strangle `+1 P 55.5 / +1 C 59.5`, +145.8% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-06)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMD | 2026-11-06 | 2026-11-20 | 14 | 435/430 | 2.47 | 0.90 | 60.7% | 56.1% | 23.44% | 24106.9% |
| 2 | XLF | 2026-11-06 | 2026-11-20 | 14 | 56.5/56 | 0.23 | 0.03 | 62.8% | 57.4% | 22.07% | 18024.6% |
| 3 | MSFT | 2026-11-06 | 2026-11-20 | 14 | 525/520 | 1.93 | 1.10 | 69.9% | 62.4% | 14.61% | 3397.6% |
| 4 | XLF | 2026-11-06 | 2026-11-20 | 14 | 57/56 | 0.42 | 0.21 | 62.8% | 57.4% | 13.09% | 2372.1% |
| 5 | AMD | 2026-11-06 | 2026-11-20 | 14 | 415/405 | 3.10 | 1.55 | 76.2% | 71.1% | 12.61% | 2110.0% |
| 6 | TSLA | 2026-11-06 | 2026-11-20 | 14 | 355/350 | 2.00 | 1.80 | 67.9% | 59.7% | 11.98% | 1809.6% |
| 7 | META | 2026-11-06 | 2026-11-20 | 14 | 600/590 | 3.55 | 3.40 | 70.5% | 63.6% | 11.41% | 1573.1% |
| 8 | MSFT | 2026-11-06 | 2026-11-20 | 14 | 525/515 | 3.45 | 2.65 | 70.5% | 63.8% | 11.34% | 1547.1% |
| 9 | MSFT | 2026-11-06 | 2026-11-20 | 14 | 530/520 | 3.75 | 2.90 | 69.9% | 62.4% | 11.28% | 1523.9% |
| 10 | TSLA | 2026-11-06 | 2026-11-20 | 14 | 347.5/345 | 0.82 | 0.60 | 74.2% | 66.6% | 11.27% | 1517.1% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-06)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-20 | 625/590 | 0.33 | 0.30 | 0.05 | +0.27 | 83.8% | 99.8% | 98.7% | 99.1% | +0.7 pp | 0.21 |
| 2 | SPY | 2026-12-04 | 590/550 | 0.44 | 0.41 | 0.07 | +0.37 | 83.7% | 99.8% | 98.6% | 98.9% | +0.9 pp | 0.23 |
| 3 | SPY | 2026-12-04 | 605/550 | 0.67 | 0.64 | 0.11 | +0.56 | 83.7% | 99.7% | 98.2% | 98.8% | +0.9 pp | 0.25 |
| 4 | SPY | 2026-11-20 | 645/590 | 0.64 | 0.61 | 0.11 | +0.53 | 82.8% | 99.6% | 97.9% | 98.8% | +0.8 pp | 0.24 |
| 5 | SPY | 2026-11-20 | 645/605 | 0.52 | 0.49 | 0.09 | +0.43 | 82.6% | 99.6% | 97.9% | 98.7% | +0.9 pp | 0.25 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 57 breaches in 53,451, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,437 eligible spreads of the latest session the median annualised return is 1.1% under the risk-neutral CDF and 86.3% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.7 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.1%, right tail uncovered 15.1%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
