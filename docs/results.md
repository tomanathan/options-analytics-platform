# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-16 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-16 | 1,222 | 3,873 | 3,774 | 47,791 |
| AMD | 2020-01-06 | 2026-11-16 | 1,219 | 3,867 | 3,767 | 47,799 |
| AMZN | 2020-01-06 | 2026-11-16 | 1,218 | 3,862 | 3,764 | 47,498 |
| DIA | 2020-01-06 | 2026-11-16 | 1,220 | 3,881 | 3,763 | 47,223 |
| GOOGL | 2020-01-06 | 2026-11-16 | 1,213 | 3,848 | 3,750 | 47,361 |
| META | 2022-07-01 | 2026-11-16 | 853 | 2,766 | 2,667 | 33,585 |
| MSFT | 2020-01-06 | 2026-11-16 | 1,208 | 3,827 | 3,729 | 47,067 |
| NVDA | 2020-01-06 | 2026-11-16 | 1,217 | 3,850 | 3,754 | 46,945 |
| SPY | 2020-01-06 | 2026-11-16 | 1,210 | 3,877 | 3,770 | 46,794 |
| TSLA | 2021-01-04 | 2026-11-16 | 1,068 | 3,405 | 3,306 | 41,798 |
| XLF | 2020-01-06 | 2026-11-16 | 1,210 | 3,850 | 3,748 | 47,432 |

In total: 1,875,134 quotes on 537,106 contracts, in 40,906 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,557 | 96.7% | enters the calibration sample |
| `unsettled` | 1,114 | 2.7% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1266 | 0.1292 | +0.0026 |
| Log loss (nats) | 0.3919 | 0.3965 | +0.0047 |
| Expected calibration error | 0.0333 | 0.0181 | -0.0152 |

Brier change +0.0026 (95% cluster-bootstrap interval -0.0004 to +0.0052, resampling expiration dates; negative means calibration helped) over 453,760 predictions, 35,642 snapshots and 893 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 144,229 | 0.1021 | 0.1047 | 0.0183 | 0.0228 |
| 21-35d | 144,654 | 0.1277 | 0.1310 | 0.0299 | 0.0234 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,805 | 0.1188 | 0.1196 | 0.0426 | 0.0156 |
| AMD | 42,373 | 0.1813 | 0.1858 | 0.0385 | 0.0419 |
| AMZN | 42,136 | 0.1348 | 0.1398 | 0.0282 | 0.0275 |
| DIA | 41,828 | 0.0624 | 0.0629 | 0.0263 | 0.0157 |
| GOOGL | 42,081 | 0.1329 | 0.1330 | 0.0490 | 0.0160 |
| META | 33,585 | 0.1537 | 0.1562 | 0.0415 | 0.0182 |
| MSFT | 41,959 | 0.1185 | 0.1221 | 0.0213 | 0.0271 |
| NVDA | 41,541 | 0.1588 | 0.1585 | 0.0735 | 0.0179 |
| SPY | 41,509 | 0.0687 | 0.0696 | 0.0268 | 0.0108 |
| TSLA | 41,798 | 0.1817 | 0.1913 | 0.0094 | 0.0638 |
| XLF | 42,145 | 0.0857 | 0.0871 | 0.0225 | 0.0205 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 102,167 | 0.1266 | 0.1267 | 0.0244 | 0.0209 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,848 | 0.0363 | 0.0191 | 168,934 | 0.0317 | 0.0394 |
| 0.1-0.2 | 56,322 | 0.1469 | 0.1128 | 62,750 | 0.1481 | 0.1923 |
| 0.2-0.3 | 40,606 | 0.2471 | 0.2078 | 39,559 | 0.2568 | 0.2829 |
| 0.3-0.4 | 33,163 | 0.3502 | 0.2991 | 30,670 | 0.3606 | 0.4044 |
| 0.4-0.5 | 35,700 | 0.4517 | 0.4050 | 25,069 | 0.4464 | 0.4707 |
| 0.5-0.6 | 27,719 | 0.5529 | 0.5008 | 28,640 | 0.5471 | 0.5684 |
| 0.6-0.7 | 33,351 | 0.6504 | 0.5971 | 32,588 | 0.6544 | 0.6610 |
| 0.7-0.8 | 31,038 | 0.7481 | 0.6928 | 21,161 | 0.7504 | 0.7538 |
| 0.8-0.9 | 25,108 | 0.8481 | 0.8187 | 16,698 | 0.8509 | 0.8641 |
| 0.9-1.0 | 32,905 | 0.9620 | 0.9564 | 27,691 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-16)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | GOOGL | 2026-11-16 | 2027-01-15 | 60 | 280/260 | 6.20 | 6.62 | 74.1% | 9.19% | 70.8% | 17.4% | 0.14 | 13.8% |
| 2 | SPY | 2026-11-16 | 2027-01-15 | 60 | 735/725 | 2.91 | 3.02 | 74.7% | 8.70% | 66.1% | 18.8% | 0.13 | 12.3% |
| 3 | GOOGL | 2026-11-16 | 2027-01-15 | 60 | 280/255 | 7.45 | 7.90 | 74.7% | 8.90% | 68.0% | 18.0% | 0.14 | 12.2% |
| 4 | SPY | 2026-11-16 | 2026-12-31 | 45 | 725/718 | 1.63 | 1.71 | 79.9% | 6.63% | 68.4% | 19.1% | 0.12 | 11.0% |
| 5 | SPY | 2026-11-16 | 2026-12-31 | 45 | 733/718 | 3.96 | 4.05 | 76.1% | 7.46% | 79.3% | 19.0% | 0.13 | 10.7% |
| 6 | SPY | 2026-11-16 | 2027-01-15 | 60 | 735/720 | 4.20 | 4.30 | 74.7% | 8.52% | 64.4% | 19.7% | 0.14 | 8.7% |
| 7 | META | 2026-11-16 | 2026-12-31 | 45 | 625/575 | 17.24 | 18.55 | 69.4% | 10.97% | 132.6% | 17.9% | 0.16 | 8.3% |
| 8 | SPY | 2026-11-16 | 2027-01-15 | 60 | 710/695 | 2.48 | 2.56 | 86.1% | 5.32% | 37.1% | 23.1% | 0.12 | 8.1% |
| 9 | SPY | 2026-11-16 | 2027-01-15 | 60 | 725/710 | 3.40 | 3.49 | 79.9% | 6.74% | 48.7% | 20.3% | 0.13 | 8.0% |
| 10 | SPY | 2026-11-16 | 2026-12-31 | 45 | 718/710 | 1.57 | 1.64 | 82.8% | 6.29% | 64.1% | 22.7% | 0.13 | 8.0% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-16)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-11 (25d) | long call `+1 C 375`, +342.9% | bull call spread `+1 C 360 / -1 C 375`, +100.5% | iron condor `-1 P 350 / +1 P 340 / -1 C 365 / +1 C 375`, +54.4% | iron condor `-1 P 340 / +1 P 330 / -1 C 355 / +1 C 365`, +96.3% | bear put spread `+1 P 350 / -1 P 320`, +181.4% | long strangle `+1 P 300 / +1 C 380`, +299.4% |
| AMD | 2026-12-11 (25d) | long call `+1 C 630`, +414.2% | bull call spread `+1 C 515 / -1 C 565`, +99.7% | iron condor `-1 P 490 / +1 P 440 / -1 C 545 / +1 C 595`, +56.4% | iron condor `-1 P 455 / +1 P 405 / -1 C 505 / +1 C 555`, +78.4% | long put `+1 P 465`, +175.0% | long call `+1 C 630`, +503.8% |
| AMZN | 2026-12-11 (25d) | bull call spread `+1 C 280 / -1 C 305`, +341.3% | bull call spread `+1 C 265 / -1 C 275`, +109.7% | iron condor `-1 P 255 / +1 P 240 / -1 C 270 / +1 C 285`, +68.8% | iron condor `-1 P 240 / +1 P 230 / -1 C 260 / +1 C 270`, +108.3% | bear put spread `+1 P 250 / -1 P 230`, +190.4% | long strangle `+1 P 230 / +1 C 285`, +247.6% |
| DIA | 2026-12-11 (25d) | long call `+1 C 536`, +382.3% | bull put spread `-1 P 531 / +1 P 521`, +116.3% | iron condor `-1 P 511 / +1 P 495 / -1 C 531 / +1 C 547`, +44.7% | iron condor `-1 P 505 / +1 P 495 / -1 C 516 / +1 C 526`, +112.7% | bear put spread `+1 P 511 / -1 P 485`, +186.6% | long strangle `+1 P 440 / +1 C 536`, +292.4% |
| GOOGL | 2026-12-11 (25d) | bull call spread `+1 C 310 / -1 C 325`, +356.6% | bull call spread `+1 C 285 / -1 C 300`, +111.0% | iron condor `-1 P 280 / +1 P 270 / -1 C 300 / +1 C 310`, +67.1% | iron condor `-1 P 270 / +1 P 255 / -1 C 285 / +1 C 300`, +77.0% | bear put spread `+1 P 275 / -1 P 255`, +178.0% | long call `+1 C 310`, +353.9% |
| META | 2026-12-11 (25d) | bull call spread `+1 C 690 / -1 C 750`, +351.2% | bull call spread `+1 C 640 / -1 C 675`, +118.2% | iron condor `-1 P 615 / +1 P 590 / -1 C 665 / +1 C 690`, +78.3% | iron condor `-1 P 590 / +1 P 550 / -1 C 635 / +1 C 675`, +90.2% | bear put spread `+1 P 600 / -1 P 550`, +199.4% | long strangle `+1 P 550 / +1 C 705`, +270.1% |
| MSFT | 2026-12-11 (25d) | long call `+1 C 550`, +362.9% | bull put spread `-1 P 550 / +1 P 520`, +102.3% | iron condor `-1 P 515 / +1 P 485 / -1 C 540 / +1 C 570`, +48.8% | iron condor `-1 P 495 / +1 P 465 / -1 C 520 / +1 C 550`, +68.8% | bear put spread `+1 P 510 / -1 P 475`, +165.6% | long call `+1 C 560`, +377.7% |
| NVDA | 2026-12-11 (25d) | bull call spread `+1 C 180 / -1 C 195`, +374.5% | bull call spread `+1 C 160 / -1 C 170`, +137.6% | iron condor `-1 P 150 / +1 P 140 / -1 C 170 / +1 C 180`, +90.7% | iron condor `-1 P 135 / +1 P 130 / -1 C 160 / +1 C 165`, +120.6% | bear put spread `+1 P 140 / -1 P 125`, +206.6% | long strangle `+1 P 135 / +1 C 175`, +244.8% |
| SPY | 2026-12-11 (25d) | long call `+1 C 770`, +525.0% | bull call spread `+1 C 755 / -1 C 762`, +140.0% | iron condor `-1 P 733 / +1 P 725 / -1 C 762 / +1 C 770`, +76.3% | iron condor `-1 P 725 / +1 P 710 / -1 C 740 / +1 C 755`, +176.0% | bear put spread `+1 P 733 / -1 P 720`, +214.4% | long strangle `+1 P 630 / +1 C 770`, +330.6% |
| TSLA | 2026-12-11 (25d) | long call `+1 C 420`, +346.0% | bull call spread `+1 C 390 / -1 C 410`, +120.3% | iron condor `-1 P 375 / +1 P 350 / -1 C 395 / +1 C 420`, +78.2% | iron condor `-1 P 355 / +1 P 340 / -1 C 380 / +1 C 395`, +114.5% | bear put spread `+1 P 365 / -1 P 330`, +194.0% | long strangle `+1 P 325 / +1 C 435`, +260.9% |
| XLF | 2026-12-11 (25d) | long call `+1 C 60`, +174.1% | bull call spread `+1 C 57.5 / -1 C 60.5`, +48.9% | bear call spread `-1 C 58 / +1 C 63`, +5.9% | bear call spread `-1 C 57 / +1 C 60`, +56.7% | long put `+1 P 59.5`, +177.7% | long put `+1 P 57`, +383.0% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-16)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | TSLA | 2026-11-16 | 2026-11-30 | 14 | 370/365 | 3.32 | 0.60 | 69.8% | 62.9% | 109.63% | 24016264477.7% |
| 2 | META | 2026-11-16 | 2026-11-30 | 14 | 625/620 | 3.35 | 0.30 | 55.0% | 46.5% | 63.03% | 34215033.1% |
| 3 | META | 2026-11-16 | 2026-11-30 | 14 | 615/610 | 2.85 | 0.25 | 59.1% | 52.2% | 39.22% | 557619.3% |
| 4 | META | 2026-11-16 | 2026-11-30 | 14 | 625/610 | 8.20 | 4.50 | 59.1% | 51.4% | 26.19% | 42939.6% |
| 5 | AMD | 2026-11-16 | 2026-11-30 | 14 | 500/490 | 4.85 | 0.15 | 60.7% | 54.6% | 20.35% | 12413.6% |
| 6 | META | 2026-11-16 | 2026-11-30 | 14 | 625/615 | 5.35 | 2.30 | 55.6% | 48.8% | 20.17% | 11923.1% |
| 7 | AMD | 2026-11-16 | 2026-11-30 | 14 | 500/485 | 6.85 | 2.15 | 63.9% | 59.3% | 18.69% | 8615.7% |
| 8 | NVDA | 2026-11-16 | 2026-11-30 | 14 | 155/150 | 2.42 | 1.85 | 60.7% | 52.5% | 18.61% | 8450.4% |
| 9 | TSLA | 2026-11-16 | 2026-11-30 | 14 | 370/355 | 5.17 | 1.75 | 74.7% | 67.2% | 18.34% | 7957.5% |
| 10 | TSLA | 2026-11-16 | 2026-11-30 | 14 | 370/350 | 6.55 | 3.55 | 75.8% | 70.4% | 17.75% | 6979.4% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-16)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-11 | 610/555 | 0.45 | 0.43 | 0.09 | +0.36 | 81.0% | 99.7% | 98.8% | 99.2% | +0.5 pp | 0.18 |
| 2 | SPY | 2026-12-11 | 630/590 | 0.50 | 0.48 | 0.10 | +0.40 | 80.6% | 99.6% | 98.2% | 98.8% | +0.8 pp | 0.22 |
| 3 | SPY | 2026-11-30 | 647/610 | 0.26 | 0.25 | 0.05 | +0.21 | 80.1% | 99.8% | 98.9% | 99.3% | +0.5 pp | 0.15 |
| 4 | SPY | 2026-12-11 | 630/610 | 0.29 | 0.27 | 0.06 | +0.23 | 79.6% | 99.6% | 98.2% | 98.5% | +1.0 pp | 0.22 |
| 5 | SPY | 2026-11-30 | 666/629 | 0.42 | 0.41 | 0.09 | +0.33 | 79.4% | 99.6% | 98.0% | 98.9% | +0.7 pp | 0.21 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 71 breaches in 53,679, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,244 eligible spreads of the latest session the median annualised return is 1.4% under the risk-neutral CDF and 71.0% after calibration, against a cash rate of 3.6%.

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
