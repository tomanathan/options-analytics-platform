# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-24 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-24 | 1,228 | 3,897 | 3,804 | 48,180 |
| AMD | 2020-01-06 | 2026-11-24 | 1,225 | 3,891 | 3,797 | 48,182 |
| AMZN | 2020-01-06 | 2026-11-24 | 1,224 | 3,886 | 3,793 | 47,875 |
| DIA | 2020-01-06 | 2026-11-24 | 1,226 | 3,905 | 3,792 | 47,564 |
| GOOGL | 2020-01-06 | 2026-11-24 | 1,219 | 3,872 | 3,778 | 47,725 |
| META | 2022-07-01 | 2026-11-24 | 859 | 2,790 | 2,696 | 33,956 |
| MSFT | 2020-01-06 | 2026-11-24 | 1,214 | 3,851 | 3,758 | 47,437 |
| NVDA | 2020-01-06 | 2026-11-24 | 1,223 | 3,874 | 3,781 | 47,296 |
| SPY | 2020-01-06 | 2026-11-24 | 1,216 | 3,901 | 3,799 | 47,165 |
| TSLA | 2021-01-04 | 2026-11-24 | 1,074 | 3,429 | 3,336 | 42,188 |
| XLF | 2020-01-06 | 2026-11-24 | 1,216 | 3,874 | 3,777 | 47,808 |

In total: 1,888,053 quotes on 540,134 contracts, in 41,170 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,876 | 96.9% | enters the calibration sample |
| `unsettled` | 1,059 | 2.6% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1274 | 0.1303 | +0.0029 |
| Log loss (nats) | 0.3940 | 0.3996 | +0.0056 |
| Expected calibration error | 0.0306 | 0.0208 | -0.0098 |

Brier change +0.0029 (95% cluster-bootstrap interval -0.0001 to +0.0056, resampling expiration dates; negative means calibration helped) over 457,843 predictions, 35,961 snapshots and 898 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 144,938 | 0.1022 | 0.1049 | 0.0176 | 0.0235 |
| 21-35d | 145,364 | 0.1282 | 0.1316 | 0.0282 | 0.0249 |
| 36-50d | 87,102 | 0.1488 | 0.1510 | 0.0413 | 0.0183 |
| >50d | 80,439 | 0.1481 | 0.1510 | 0.0476 | 0.0172 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 43,194 | 0.1183 | 0.1191 | 0.0427 | 0.0145 |
| AMD | 42,756 | 0.1825 | 0.1875 | 0.0342 | 0.0453 |
| AMZN | 42,513 | 0.1345 | 0.1395 | 0.0276 | 0.0282 |
| DIA | 42,169 | 0.0634 | 0.0641 | 0.0243 | 0.0162 |
| GOOGL | 42,445 | 0.1352 | 0.1357 | 0.0440 | 0.0192 |
| META | 33,956 | 0.1557 | 0.1588 | 0.0357 | 0.0217 |
| MSFT | 42,329 | 0.1187 | 0.1225 | 0.0195 | 0.0290 |
| NVDA | 41,892 | 0.1612 | 0.1615 | 0.0677 | 0.0203 |
| SPY | 41,880 | 0.0702 | 0.0714 | 0.0240 | 0.0109 |
| TSLA | 42,188 | 0.1812 | 0.1910 | 0.0086 | 0.0650 |
| XLF | 42,521 | 0.0854 | 0.0869 | 0.0222 | 0.0211 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 106,250 | 0.1300 | 0.1315 | 0.0131 | 0.0316 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 138,880 | 0.0363 | 0.0203 | 170,154 | 0.0317 | 0.0408 |
| 0.1-0.2 | 56,877 | 0.1468 | 0.1164 | 63,446 | 0.1481 | 0.1962 |
| 0.2-0.3 | 41,027 | 0.2471 | 0.2117 | 39,972 | 0.2568 | 0.2870 |
| 0.3-0.4 | 33,521 | 0.3502 | 0.3036 | 30,997 | 0.3606 | 0.4088 |
| 0.4-0.5 | 36,028 | 0.4516 | 0.4089 | 25,333 | 0.4464 | 0.4755 |
| 0.5-0.6 | 28,057 | 0.5529 | 0.5062 | 29,000 | 0.5470 | 0.5734 |
| 0.6-0.7 | 33,713 | 0.6504 | 0.6012 | 32,969 | 0.6544 | 0.6648 |
| 0.7-0.8 | 31,368 | 0.7481 | 0.6958 | 21,305 | 0.7503 | 0.7554 |
| 0.8-0.9 | 25,262 | 0.8481 | 0.8198 | 16,800 | 0.8509 | 0.8649 |
| 0.9-1.0 | 33,110 | 0.9619 | 0.9567 | 27,867 | 0.9673 | 0.9679 |

## Top 10 to enter (2026-11-24)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-24 | 2027-01-15 | 52 | 705/690 | 3.86 | 3.96 | 77.3% | 6.93% | 60.1% | 17.9% | 0.12 | 11.8% |
| 2 | SPY | 2026-11-24 | 2027-01-15 | 52 | 710/705 | 1.49 | 1.59 | 74.3% | 9.37% | 87.5% | 19.0% | 0.14 | 11.0% |
| 3 | SPY | 2026-11-24 | 2027-01-15 | 52 | 710/695 | 4.25 | 4.34 | 74.3% | 8.18% | 73.6% | 18.8% | 0.13 | 10.3% |
| 4 | SPY | 2026-11-24 | 2027-01-15 | 52 | 705/675 | 6.87 | 6.96 | 79.4% | 6.23% | 52.8% | 19.0% | 0.12 | 9.6% |
| 5 | META | 2026-11-24 | 2027-01-15 | 52 | 570/530 | 11.80 | 12.55 | 73.8% | 8.88% | 81.7% | 18.3% | 0.14 | 7.4% |
| 6 | SPY | 2026-11-24 | 2027-01-15 | 52 | 690/675 | 2.92 | 3.00 | 82.5% | 5.58% | 46.4% | 20.3% | 0.12 | 6.3% |
| 7 | SPY | 2026-11-24 | 2027-01-15 | 52 | 705/695 | 2.66 | 2.75 | 75.5% | 7.62% | 67.4% | 18.7% | 0.13 | 5.8% |
| 8 | SPY | 2026-11-24 | 2027-01-15 | 52 | 710/690 | 5.45 | 5.54 | 74.3% | 7.51% | 66.2% | 18.3% | 0.13 | 5.3% |
| 9 | SPY | 2026-11-24 | 2027-01-15 | 52 | 695/675 | 4.12 | 4.20 | 80.6% | 5.59% | 46.5% | 19.1% | 0.11 | 3.8% |
| 10 | SPY | 2026-11-24 | 2027-01-15 | 52 | 710/660 | 10.73 | 10.81 | 79.4% | 5.78% | 48.4% | 19.1% | 0.12 | 3.2% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-24)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-31 (37d) | long call `+1 C 380`, +364.3% | bull call spread `+1 C 360 / -1 C 375`, +113.3% | iron condor `-1 P 350 / +1 P 340 / -1 C 370 / +1 C 380`, +61.9% | iron condor `-1 P 340 / +1 P 325 / -1 C 355 / +1 C 370`, +111.7% | bear put spread `+1 P 350 / -1 P 320`, +195.9% | long call `+1 C 380`, +363.4% |
| AMD | 2026-12-31 (37d) | long call `+1 C 515`, +347.4% | bull call spread `+1 C 410 / -1 C 440`, +100.0% | iron condor `-1 P 390 / +1 P 350 / -1 C 475 / +1 C 515`, +62.3% | iron condor `-1 P 350 / +1 P 310 / -1 C 415 / +1 C 455`, +101.5% | bear put spread `+1 P 350 / -1 P 310`, +173.5% | long strangle `+1 P 360 / +1 C 475`, +183.6% |
| AMZN | 2026-12-31 (37d) | long call `+1 C 280`, +336.2% | bull call spread `+1 C 260 / -1 C 270`, +114.4% | iron condor `-1 P 250 / +1 P 235 / -1 C 270 / +1 C 285`, +70.1% | iron condor `-1 P 235 / +1 P 225 / -1 C 255 / +1 C 265`, +96.8% | bear put spread `+1 P 240 / -1 P 215`, +192.3% | long call `+1 C 290`, +415.7% |
| DIA | 2026-12-31 (37d) | long call `+1 C 530`, +448.1% | bull call spread `+1 C 510 / -1 C 520`, +112.4% | iron condor `-1 P 495 / +1 P 480 / -1 C 515 / +1 C 530`, +63.0% | iron condor `-1 P 485 / +1 P 470 / -1 C 500 / +1 C 515`, +126.6% | bear put spread `+1 P 495 / -1 P 460`, +201.3% | long call `+1 C 530`, +542.2% |
| GOOGL | 2026-12-31 (37d) | bull call spread `+1 C 305 / -1 C 330`, +302.2% | bull call spread `+1 C 285 / -1 C 300`, +98.4% | iron condor `-1 P 275 / +1 P 260 / -1 C 300 / +1 C 315`, +57.9% | iron condor `-1 P 260 / +1 P 245 / -1 C 280 / +1 C 295`, +79.8% | bear put spread `+1 P 255 / -1 P 230`, +176.0% | bull call spread `+1 C 315 / -1 C 335`, +331.6% |
| META | 2026-12-31 (37d) | long call `+1 C 650`, +333.8% | bull call spread `+1 C 595 / -1 C 635`, +113.7% | iron condor `-1 P 585 / +1 P 545 / -1 C 625 / +1 C 665`, +70.6% | iron condor `-1 P 545 / +1 P 500 / -1 C 590 / +1 C 635`, +110.2% | bear put spread `+1 P 555 / -1 P 500`, +195.6% | long call `+1 C 680`, +372.6% |
| MSFT | 2026-12-31 (37d) | long call `+1 C 545`, +310.1% | bull call spread `+1 C 500 / -1 C 535`, +101.2% | iron condor `-1 P 495 / +1 P 455 / -1 C 505 / +1 C 545`, +44.8% | iron condor `-1 P 480 / +1 P 445 / -1 C 500 / +1 C 535`, +75.5% | bear put spread `+1 P 485 / -1 P 445`, +177.7% | long strangle `+1 P 445 / +1 C 545`, +218.0% |
| NVDA | 2026-12-31 (37d) | long call `+1 C 180`, +387.4% | bull put spread `-1 P 170 / +1 P 160`, +105.4% | iron condor `-1 P 135 / +1 P 130 / -1 C 175 / +1 C 180`, +55.9% | iron condor `-1 P 130 / +1 P 125 / -1 C 175 / +1 C 180`, +56.2% | bear put spread `+1 P 135 / -1 P 125`, +201.9% | long strangle `+1 P 135 / +1 C 175`, +240.1% |
| SPY | 2026-12-31 (37d) | long call `+1 C 762`, +522.4% | bull call spread `+1 C 740 / -1 C 748`, +139.5% | iron condor `-1 P 712 / +1 P 704 / -1 C 740 / +1 C 748`, +86.2% | iron condor `-1 P 704 / +1 P 690 / -1 C 719 / +1 C 733`, +191.5% | bear put spread `+1 P 704 / -1 P 690`, +219.7% | long call `+1 C 762`, +564.1% |
| TSLA | 2026-12-31 (37d) | long call `+1 C 450`, +367.6% | bull call spread `+1 C 400 / -1 C 425`, +109.9% | iron condor `-1 P 375 / +1 P 345 / -1 C 410 / +1 C 440`, +70.2% | iron condor `-1 P 360 / +1 P 335 / -1 C 385 / +1 C 410`, +105.4% | bear put spread `+1 P 355 / -1 P 325`, +177.6% | long strangle `+1 P 335 / +1 C 440`, +240.4% |
| XLF | 2026-12-31 (37d) | long call `+1 C 61`, +1291.1% | bull put spread `-1 P 58 / +1 P 55`, +56.4% | iron condor `-1 P 56 / +1 P 53 / -1 C 58 / +1 C 61`, +18.2% | bear call spread `-1 C 55 / +1 C 58`, +36.8% | long put `+1 P 57`, +123.4% | long call `+1 C 61`, +1522.4% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-24)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | NVDA | 2026-11-24 | 2026-12-07 | 13 | 155/152.5 | 1.32 | 0.54 | 63.4% | 59.1% | 36.98% | 686709.9% |
| 2 | GOOGL | 2026-11-24 | 2026-12-07 | 13 | 277.5/272.5 | 2.46 | 0.75 | 67.3% | 59.7% | 35.19% | 474508.7% |
| 3 | NVDA | 2026-11-24 | 2026-12-07 | 13 | 155/150 | 2.27 | 1.74 | 67.4% | 60.2% | 22.45% | 29401.1% |
| 4 | AMD | 2026-11-24 | 2026-12-07 | 13 | 400/390 | 4.28 | 1.15 | 68.9% | 61.6% | 20.81% | 20112.6% |
| 5 | GOOGL | 2026-11-24 | 2026-12-07 | 13 | 277.5/267.5 | 3.93 | 2.41 | 70.3% | 63.8% | 19.18% | 13687.4% |
| 6 | NVDA | 2026-11-24 | 2026-12-07 | 13 | 155/146 | 3.72 | 1.64 | 68.9% | 61.9% | 17.24% | 8590.3% |
| 7 | AMD | 2026-11-24 | 2026-12-07 | 13 | 395/380 | 5.54 | 1.04 | 70.5% | 64.2% | 14.74% | 4649.5% |
| 8 | GOOGL | 2026-11-24 | 2026-12-07 | 13 | 277.5/270 | 2.86 | 1.30 | 67.5% | 60.7% | 14.45% | 4326.3% |
| 9 | META | 2026-11-24 | 2026-12-07 | 13 | 577.5/565 | 4.45 | 0.65 | 70.6% | 65.2% | 14.27% | 4133.8% |
| 10 | AMD | 2026-11-24 | 2026-12-07 | 13 | 400/380 | 7.47 | 2.90 | 68.9% | 61.6% | 14.17% | 4025.2% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-24)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-07 | 630/595 | 0.39 | 0.36 | 0.08 | +0.31 | 80.4% | 99.6% | 98.2% | 98.9% | +0.7 pp | 0.21 |
| 2 | SPY | 2026-12-24 | 575/540 | 0.43 | 0.40 | 0.09 | +0.35 | 79.3% | 99.6% | 98.3% | 98.8% | +0.9 pp | 0.21 |
| 3 | SPY | 2026-12-07 | 630/575 | 0.49 | 0.47 | 0.10 | +0.39 | 79.2% | 99.6% | 98.2% | 99.1% | +0.5 pp | 0.18 |
| 4 | SPY | 2026-12-07 | 630/610 | 0.26 | 0.24 | 0.05 | +0.21 | 78.9% | 99.6% | 98.2% | 98.7% | +0.9 pp | 0.21 |
| 5 | SPY | 2026-12-31 | 575/540 | 0.54 | 0.51 | 0.12 | +0.42 | 77.8% | 99.5% | 97.9% | 98.5% | +1.1 pp | 0.22 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 73 breaches in 53,965, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,249 eligible spreads of the latest session the median annualised return is 1.4% under the risk-neutral CDF and 74.1% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.8 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.0%, right tail uncovered 15.2%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
