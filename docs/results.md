# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-03 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-03 | 1,213 | 3,838 | 3,757 | 47,573 |
| AMD | 2020-01-06 | 2026-11-03 | 1,210 | 3,832 | 3,750 | 47,596 |
| AMZN | 2020-01-06 | 2026-11-03 | 1,209 | 3,827 | 3,746 | 47,264 |
| DIA | 2020-01-06 | 2026-11-03 | 1,211 | 3,845 | 3,745 | 46,989 |
| GOOGL | 2020-01-06 | 2026-11-03 | 1,204 | 3,813 | 3,732 | 47,128 |
| META | 2022-07-01 | 2026-11-03 | 844 | 2,731 | 2,649 | 33,376 |
| MSFT | 2020-01-06 | 2026-11-03 | 1,199 | 3,793 | 3,712 | 46,863 |
| NVDA | 2020-01-06 | 2026-11-03 | 1,208 | 3,816 | 3,737 | 46,724 |
| SPY | 2020-01-06 | 2026-11-03 | 1,201 | 3,841 | 3,754 | 46,603 |
| TSLA | 2021-01-04 | 2026-11-03 | 1,059 | 3,370 | 3,289 | 41,588 |
| XLF | 2020-01-06 | 2026-11-03 | 1,201 | 3,814 | 3,730 | 47,198 |

In total: 1,856,573 quotes on 531,410 contracts, in 40,520 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,366 | 97.2% | enters the calibration sample |
| `unsettled` | 919 | 2.3% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1265 | 0.1290 | +0.0025 |
| Log loss (nats) | 0.3914 | 0.3959 | +0.0045 |
| Expected calibration error | 0.0340 | 0.0175 | -0.0165 |

Brier change +0.0025 (95% cluster-bootstrap interval -0.0007 to +0.0056, resampling expiration dates; negative means calibration helped) over 451,369 predictions, 35,452 snapshots and 886 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 142,891 | 0.1019 | 0.1044 | 0.0190 | 0.0221 |
| 21-35d | 143,601 | 0.1273 | 0.1305 | 0.0311 | 0.0223 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,587 | 0.1191 | 0.1200 | 0.0425 | 0.0163 |
| AMD | 42,170 | 0.1812 | 0.1856 | 0.0398 | 0.0412 |
| AMZN | 41,902 | 0.1350 | 0.1401 | 0.0276 | 0.0281 |
| DIA | 41,594 | 0.0626 | 0.0630 | 0.0265 | 0.0156 |
| GOOGL | 41,848 | 0.1323 | 0.1322 | 0.0510 | 0.0150 |
| META | 33,376 | 0.1535 | 0.1558 | 0.0431 | 0.0181 |
| MSFT | 41,755 | 0.1187 | 0.1224 | 0.0214 | 0.0271 |
| NVDA | 41,320 | 0.1573 | 0.1567 | 0.0769 | 0.0163 |
| SPY | 41,318 | 0.0687 | 0.0696 | 0.0273 | 0.0103 |
| TSLA | 41,588 | 0.1821 | 0.1917 | 0.0092 | 0.0641 |
| XLF | 41,911 | 0.0857 | 0.0871 | 0.0222 | 0.0212 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 99,776 | 0.1261 | 0.1260 | 0.0273 | 0.0197 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 136,995 | 0.0363 | 0.0186 | 168,010 | 0.0317 | 0.0391 |
| 0.1-0.2 | 56,074 | 0.1468 | 0.1120 | 62,428 | 0.1481 | 0.1917 |
| 0.2-0.3 | 40,433 | 0.2471 | 0.2071 | 39,380 | 0.2567 | 0.2820 |
| 0.3-0.4 | 33,000 | 0.3502 | 0.2982 | 30,524 | 0.3605 | 0.4039 |
| 0.4-0.5 | 35,551 | 0.4517 | 0.4046 | 24,958 | 0.4464 | 0.4699 |
| 0.5-0.6 | 27,587 | 0.5529 | 0.4998 | 28,503 | 0.5471 | 0.5675 |
| 0.6-0.7 | 33,197 | 0.6504 | 0.5964 | 32,384 | 0.6544 | 0.6595 |
| 0.7-0.8 | 30,854 | 0.7481 | 0.6913 | 21,056 | 0.7503 | 0.7528 |
| 0.8-0.9 | 24,962 | 0.8481 | 0.8179 | 16,603 | 0.8509 | 0.8638 |
| 0.9-1.0 | 32,716 | 0.9619 | 0.9563 | 27,523 | 0.9673 | 0.9677 |

## Top 10 to enter (2026-11-03)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | TSLA | 2026-11-03 | 2026-12-18 | 45 | 390/375 | 5.50 | 5.72 | 68.2% | 10.98% | 132.9% | 17.1% | 0.15 | 23.5% |
| 2 | TSLA | 2026-11-03 | 2026-12-18 | 45 | 390/365 | 8.55 | 8.75 | 70.0% | 10.12% | 118.6% | 18.0% | 0.15 | 23.0% |
| 3 | TSLA | 2026-11-03 | 2026-12-18 | 45 | 395/365 | 10.74 | 10.97 | 68.3% | 10.08% | 117.9% | 16.7% | 0.14 | 23.0% |
| 4 | TSLA | 2026-11-03 | 2026-12-18 | 45 | 395/360 | 11.99 | 12.25 | 69.5% | 9.69% | 111.7% | 17.2% | 0.15 | 20.5% |
| 5 | META | 2026-11-03 | 2026-12-18 | 45 | 610/585 | 8.90 | 9.48 | 69.5% | 11.10% | 134.9% | 17.5% | 0.15 | 19.3% |
| 6 | NVDA | 2026-11-03 | 2026-12-18 | 45 | 205/190 | 5.20 | 5.40 | 69.5% | 9.97% | 116.2% | 17.0% | 0.14 | 19.2% |
| 7 | META | 2026-11-03 | 2026-12-18 | 45 | 615/570 | 15.50 | 16.07 | 69.5% | 10.08% | 117.9% | 17.3% | 0.15 | 18.0% |
| 8 | NVDA | 2026-11-03 | 2026-12-18 | 45 | 205/194 | 4.00 | 4.20 | 67.9% | 10.60% | 126.4% | 16.5% | 0.14 | 17.0% |
| 9 | META | 2026-11-03 | 2026-12-18 | 45 | 610/570 | 13.30 | 13.85 | 70.6% | 10.10% | 118.3% | 18.2% | 0.15 | 16.4% |
| 10 | TSLA | 2026-11-03 | 2026-12-18 | 45 | 390/360 | 9.80 | 10.02 | 70.6% | 9.67% | 111.4% | 18.4% | 0.15 | 16.4% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-03)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-04 (31d) | long call `+1 C 350`, +340.2% | bull call spread `+1 C 335 / -1 C 350`, +106.4% | iron condor `-1 P 330 / +1 P 320 / -1 C 350 / +1 C 360`, +52.2% | iron condor `-1 P 320 / +1 P 305 / -1 C 335 / +1 C 350`, +77.8% | bear put spread `+1 P 325 / -1 P 300`, +176.6% | long call `+1 C 360`, +444.9% |
| AMD | 2026-12-04 (31d) | long call `+1 C 545`, +322.7% | bull call spread `+1 C 485 / -1 C 525`, +118.4% | iron condor `-1 P 470 / +1 P 425 / -1 C 525 / +1 C 570`, +81.6% | iron condor `-1 P 425 / +1 P 400 / -1 C 490 / +1 C 515`, +102.3% | bear put spread `+1 P 445 / -1 P 400`, +188.1% | long call `+1 C 570`, +286.7% |
| AMZN | 2026-12-04 (31d) | long call `+1 C 270`, +344.5% | bull call spread `+1 C 250 / -1 C 270`, +102.6% | iron condor `-1 P 245 / +1 P 235 / -1 C 270 / +1 C 280`, +54.0% | iron condor `-1 P 235 / +1 P 225 / -1 C 255 / +1 C 265`, +74.8% | bear put spread `+1 P 245 / -1 P 220`, +178.2% | long strangle `+1 P 220 / +1 C 275`, +255.2% |
| DIA | 2026-12-04 (31d) | long call `+1 C 537.5`, +399.2% | bull put spread `-1 P 532.5 / +1 P 522`, +117.3% | iron condor `-1 P 517 / +1 P 507 / -1 C 527.5 / +1 C 537.5`, +66.9% | bear call spread `-1 C 517 / +1 C 527.5`, +65.3% | bear put spread `+1 P 512 / -1 P 485`, +190.6% | long strangle `+1 P 440 / +1 C 537.5`, +291.6% |
| GOOGL | 2026-12-04 (31d) | bull call spread `+1 C 300 / -1 C 320`, +343.9% | bull call spread `+1 C 285 / -1 C 300`, +118.2% | iron condor `-1 P 280 / +1 P 260 / -1 C 290 / +1 C 310`, +61.9% | bear call spread `-1 C 275 / +1 C 285`, +83.4% | bear put spread `+1 P 270 / -1 P 250`, +176.9% | bull call spread `+1 C 310 / -1 C 335`, +409.6% |
| META | 2026-12-04 (31d) | bull call spread `+1 C 670 / -1 C 730`, +354.0% | bull call spread `+1 C 635 / -1 C 660`, +129.7% | iron condor `-1 P 610 / +1 P 570 / -1 C 660 / +1 C 700`, +76.8% | iron condor `-1 P 595 / +1 P 560 / -1 C 625 / +1 C 660`, +102.4% | bear put spread `+1 P 595 / -1 P 545`, +200.2% | bull call spread `+1 C 715 / -1 C 775`, +415.9% |
| MSFT | 2026-12-04 (31d) | long call `+1 C 565`, +346.4% | bull call spread `+1 C 530 / -1 C 550`, +112.9% | iron condor `-1 P 520 / +1 P 490 / -1 C 535 / +1 C 565`, +56.7% | iron condor `-1 P 480 / +1 P 470 / -1 C 530 / +1 C 540`, +76.9% | bear put spread `+1 P 510 / -1 P 480`, +180.2% | long call `+1 C 575`, +434.0% |
| NVDA | 2026-12-04 (31d) | bull call spread `+1 C 225 / -1 C 245`, +345.0% | bull call spread `+1 C 215 / -1 C 225`, +122.5% | iron condor `-1 P 205 / +1 P 190 / -1 C 220 / +1 C 235`, +82.0% | iron condor `-1 P 190 / +1 P 180 / -1 C 210 / +1 C 220`, +122.7% | bear put spread `+1 P 195 / -1 P 175`, +198.8% | bull call spread `+1 C 240 / -1 C 260`, +401.3% |
| SPY | 2026-11-30 (27d) | long call `+1 C 785`, +516.4% | bull call spread `+1 C 769 / -1 C 777`, +133.5% | iron condor `-1 P 747 / +1 P 739 / -1 C 777 / +1 C 785`, +65.7% | iron condor `-1 P 739 / +1 P 732 / -1 C 762 / +1 C 769`, +150.9% | bear put spread `+1 P 747 / -1 P 724`, +202.1% | long call `+1 C 785`, +519.1% |
| TSLA | 2026-12-04 (31d) | bull call spread `+1 C 440 / -1 C 470`, +372.6% | bull call spread `+1 C 410 / -1 C 420`, +133.9% | iron condor `-1 P 395 / +1 P 375 / -1 C 420 / +1 C 440`, +88.8% | iron condor `-1 P 360 / +1 P 350 / -1 C 400 / +1 C 410`, +145.6% | bear put spread `+1 P 375 / -1 P 360`, +205.2% | long strangle `+1 P 350 / +1 C 450`, +252.3% |
| XLF | 2026-12-04 (31d) | bull call spread `+1 C 59.5 / -1 C 63`, +264.4% | bull call spread `+1 C 58 / -1 C 59.5`, +91.9% | iron condor `-1 P 57 / +1 P 55 / -1 C 58.5 / +1 C 60.5`, +30.1% | bear call spread `-1 C 57 / +1 C 59.5`, +45.4% | bear put spread `+1 P 57 / -1 P 52.5`, +163.0% | long call `+1 C 59.5`, +205.2% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-03)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | MSFT | 2026-11-03 | 2026-11-18 | 15 | 520/515 | 2.60 | 0.10 | 60.7% | 54.5% | 29.99% | 59052.7% |
| 2 | GOOGL | 2026-11-03 | 2026-11-16 | 13 | 270/265 | 1.71 | 0.61 | 77.5% | 72.0% | 21.15% | 21764.0% |
| 3 | GOOGL | 2026-11-03 | 2026-11-16 | 13 | 280/275 | 2.27 | 1.40 | 60.7% | 55.5% | 16.47% | 7131.5% |
| 4 | META | 2026-11-03 | 2026-11-16 | 13 | 610/600 | 3.73 | 3.01 | 70.0% | 62.1% | 13.85% | 3717.3% |
| 5 | META | 2026-11-03 | 2026-11-16 | 13 | 615/600 | 5.76 | 5.11 | 69.5% | 60.8% | 12.71% | 2779.8% |
| 6 | AMD | 2026-11-03 | 2026-11-18 | 15 | 470/455 | 6.12 | 2.59 | 68.0% | 60.0% | 14.26% | 2461.9% |
| 7 | AAPL | 2026-11-03 | 2026-11-18 | 15 | 330/325 | 2.12 | 0.45 | 62.9% | 57.1% | 14.17% | 2414.1% |
| 8 | META | 2026-11-03 | 2026-11-16 | 13 | 620/600 | 7.98 | 7.16 | 65.0% | 59.6% | 12.16% | 2407.2% |
| 9 | MSFT | 2026-11-03 | 2026-11-18 | 15 | 520/505 | 5.70 | 3.25 | 70.7% | 63.6% | 13.99% | 2317.7% |
| 10 | MSFT | 2026-11-03 | 2026-11-18 | 15 | 510/500 | 3.03 | 0.60 | 74.8% | 69.9% | 13.63% | 2141.3% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-03)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | DIA | 2026-12-31 | 425/390 | 0.42 | 0.22 | 0.07 | +0.35 | 83.8% | 99.7% | 98.3% | 98.8% | +0.9 pp | 0.24 |
| 2 | SPY | 2026-11-30 | 641/603 | 0.35 | 0.31 | 0.06 | +0.30 | 83.5% | 99.8% | 98.7% | 99.1% | +0.7 pp | 0.21 |
| 3 | DIA | 2026-12-18 | 440/390 | 0.56 | 0.37 | 0.09 | +0.47 | 83.4% | 99.6% | 98.0% | 98.9% | +0.7 pp | 0.24 |
| 4 | SPY | 2026-12-18 | 605/565 | 0.48 | 0.44 | 0.08 | +0.40 | 83.2% | 99.8% | 98.4% | 98.8% | +1.0 pp | 0.23 |
| 5 | SPY | 2026-12-18 | 620/565 | 0.73 | 0.69 | 0.13 | +0.61 | 83.0% | 99.6% | 98.1% | 98.7% | +1.0 pp | 0.25 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 56 breaches in 53,306, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,119 eligible spreads of the latest session the median annualised return is 1.3% under the risk-neutral CDF and 72.4% after calibration, against a cash rate of 3.6%.

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
