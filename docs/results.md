# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-19 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-19 | 1,225 | 3,885 | 3,777 | 47,829 |
| AMD | 2020-01-06 | 2026-11-19 | 1,222 | 3,879 | 3,770 | 47,835 |
| AMZN | 2020-01-06 | 2026-11-19 | 1,221 | 3,874 | 3,766 | 47,524 |
| DIA | 2020-01-06 | 2026-11-19 | 1,223 | 3,893 | 3,763 | 47,223 |
| GOOGL | 2020-01-06 | 2026-11-19 | 1,216 | 3,860 | 3,752 | 47,387 |
| META | 2022-07-01 | 2026-11-19 | 856 | 2,778 | 2,668 | 33,597 |
| MSFT | 2020-01-06 | 2026-11-19 | 1,211 | 3,839 | 3,732 | 47,102 |
| NVDA | 2020-01-06 | 2026-11-19 | 1,220 | 3,862 | 3,755 | 46,958 |
| SPY | 2020-01-06 | 2026-11-19 | 1,213 | 3,889 | 3,771 | 46,801 |
| TSLA | 2021-01-04 | 2026-11-19 | 1,071 | 3,417 | 3,309 | 41,837 |
| XLF | 2020-01-06 | 2026-11-19 | 1,213 | 3,862 | 3,751 | 47,471 |

In total: 1,881,632 quotes on 538,654 contracts, in 41,038 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,579 | 96.4% | enters the calibration sample |
| `unsettled` | 1,224 | 3.0% | the expiration is after the last priced session, so there is no outcome yet |
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

Brier change +0.0026 (95% cluster-bootstrap interval -0.0005 to +0.0057, resampling expiration dates; negative means calibration helped) over 454,031 predictions, 35,664 snapshots and 895 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 144,500 | 0.1021 | 0.1047 | 0.0182 | 0.0229 |
| 21-35d | 144,654 | 0.1277 | 0.1310 | 0.0299 | 0.0234 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,843 | 0.1187 | 0.1196 | 0.0426 | 0.0155 |
| AMD | 42,409 | 0.1813 | 0.1858 | 0.0387 | 0.0417 |
| AMZN | 42,162 | 0.1348 | 0.1397 | 0.0283 | 0.0275 |
| DIA | 41,828 | 0.0624 | 0.0629 | 0.0263 | 0.0157 |
| GOOGL | 42,107 | 0.1329 | 0.1329 | 0.0490 | 0.0160 |
| META | 33,597 | 0.1537 | 0.1562 | 0.0415 | 0.0182 |
| MSFT | 41,994 | 0.1185 | 0.1222 | 0.0211 | 0.0273 |
| NVDA | 41,554 | 0.1589 | 0.1586 | 0.0733 | 0.0180 |
| SPY | 41,516 | 0.0687 | 0.0697 | 0.0268 | 0.0108 |
| TSLA | 41,837 | 0.1816 | 0.1912 | 0.0094 | 0.0638 |
| XLF | 42,184 | 0.0857 | 0.0871 | 0.0225 | 0.0205 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 102,438 | 0.1265 | 0.1267 | 0.0243 | 0.0208 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,942 | 0.0363 | 0.0191 | 169,038 | 0.0316 | 0.0395 |
| 0.1-0.2 | 56,346 | 0.1469 | 0.1128 | 62,782 | 0.1481 | 0.1923 |
| 0.2-0.3 | 40,629 | 0.2471 | 0.2078 | 39,589 | 0.2568 | 0.2829 |
| 0.3-0.4 | 33,188 | 0.3502 | 0.2991 | 30,685 | 0.3606 | 0.4044 |
| 0.4-0.5 | 35,716 | 0.4517 | 0.4051 | 25,075 | 0.4464 | 0.4707 |
| 0.5-0.6 | 27,725 | 0.5529 | 0.5008 | 28,659 | 0.5471 | 0.5684 |
| 0.6-0.7 | 33,375 | 0.6504 | 0.5971 | 32,606 | 0.6544 | 0.6611 |
| 0.7-0.8 | 31,055 | 0.7481 | 0.6928 | 21,173 | 0.7503 | 0.7538 |
| 0.8-0.9 | 25,124 | 0.8481 | 0.8188 | 16,710 | 0.8509 | 0.8642 |
| 0.9-1.0 | 32,931 | 0.9620 | 0.9565 | 27,714 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-19)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-19 | 2027-01-15 | 57 | 715/695 | 6.19 | 6.33 | 74.1% | 9.49% | 78.7% | 19.3% | 0.15 | 22.0% |
| 2 | SPY | 2026-11-19 | 2027-01-15 | 57 | 710/700 | 3.03 | 3.15 | 74.7% | 9.25% | 76.2% | 19.0% | 0.14 | 18.9% |
| 3 | SPY | 2026-11-19 | 2027-01-15 | 57 | 710/695 | 4.41 | 4.52 | 74.7% | 9.01% | 73.7% | 19.6% | 0.14 | 16.3% |
| 4 | SPY | 2026-11-19 | 2027-01-15 | 57 | 700/685 | 3.68 | 3.78 | 79.7% | 7.15% | 55.6% | 19.6% | 0.13 | 16.3% |
| 5 | SPY | 2026-11-19 | 2027-01-15 | 57 | 715/685 | 8.60 | 8.74 | 74.7% | 8.41% | 67.7% | 19.1% | 0.14 | 13.6% |
| 6 | SPY | 2026-11-19 | 2027-01-15 | 57 | 685/675 | 1.93 | 2.02 | 84.0% | 6.49% | 49.6% | 23.5% | 0.13 | 10.0% |
| 7 | META | 2026-11-19 | 2027-01-15 | 57 | 595/550 | 16.15 | 17.04 | 68.0% | 10.50% | 89.5% | 16.3% | 0.14 | 10.0% |
| 8 | SPY | 2026-11-19 | 2027-01-15 | 57 | 695/685 | 2.32 | 2.41 | 79.9% | 6.47% | 49.4% | 18.6% | 0.11 | 9.6% |
| 9 | SPY | 2026-11-19 | 2027-01-15 | 57 | 700/675 | 5.70 | 5.80 | 79.8% | 6.87% | 53.1% | 20.9% | 0.13 | 9.5% |
| 10 | SPY | 2026-11-19 | 2027-01-15 | 57 | 715/700 | 4.81 | 4.96 | 70.9% | 9.83% | 82.3% | 18.8% | 0.14 | 9.5% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-19)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-18 (29d) | long call `+1 C 375`, +417.2% | bull call spread `+1 C 355 / -1 C 370`, +115.7% | iron condor `-1 P 345 / +1 P 335 / -1 C 365 / +1 C 375`, +68.1% | iron condor `-1 P 340 / +1 P 330 / -1 C 350 / +1 C 360`, +127.7% | bear put spread `+1 P 345 / -1 P 320`, +197.0% | long strangle `+1 P 305 / +1 C 375`, +298.6% |
| AMD | 2026-12-18 (29d) | long call `+1 C 610`, +406.4% | bull call spread `+1 C 510 / -1 C 550`, +133.6% | iron condor `-1 P 480 / +1 P 440 / -1 C 550 / +1 C 590`, +89.1% | iron condor `-1 P 430 / +1 P 390 / -1 C 490 / +1 C 530`, +114.9% | bear put spread `+1 P 440 / -1 P 400`, +193.9% | long strangle `+1 P 420 / +1 C 560`, +244.0% |
| AMZN | 2026-12-18 (29d) | bull call spread `+1 C 280 / -1 C 300`, +363.7% | bull call spread `+1 C 265 / -1 C 280`, +123.9% | iron condor `-1 P 255 / +1 P 240 / -1 C 270 / +1 C 285`, +78.2% | iron condor `-1 P 245 / +1 P 235 / -1 C 260 / +1 C 270`, +116.1% | bear put spread `+1 P 250 / -1 P 225`, +197.3% | long call `+1 C 290`, +409.2% |
| DIA | 2026-12-18 (29d) | long call `+1 C 520`, +431.4% | bull call spread `+1 C 501 / -1 C 510`, +107.4% | iron condor `-1 P 486 / +1 P 476 / -1 C 510 / +1 C 520`, +60.6% | iron condor `-1 P 470 / +1 P 460 / -1 C 491 / +1 C 501`, +97.6% | bear call spread `-1 C 450 / +1 C 486`, +186.7% | long call `+1 C 520`, +510.6% |
| GOOGL | 2026-12-18 (29d) | bull call spread `+1 C 300 / -1 C 320`, +353.5% | bull call spread `+1 C 280 / -1 C 290`, +122.4% | iron condor `-1 P 270 / +1 P 255 / -1 C 285 / +1 C 300`, +74.6% | iron condor `-1 P 255 / +1 P 245 / -1 C 275 / +1 C 285`, +108.1% | bear put spread `+1 P 265 / -1 P 240`, +203.4% | long strangle `+1 P 240 / +1 C 305`, +264.2% |
| META | 2026-12-18 (29d) | bull call spread `+1 C 655 / -1 C 700`, +359.6% | bull call spread `+1 C 610 / -1 C 645`, +124.7% | iron condor `-1 P 590 / +1 P 550 / -1 C 630 / +1 C 670`, +82.6% | iron condor `-1 P 550 / +1 P 535 / -1 C 600 / +1 C 615`, +123.1% | bear put spread `+1 P 570 / -1 P 520`, +201.5% | long call `+1 C 685`, +391.6% |
| MSFT | 2026-12-18 (29d) | long call `+1 C 540`, +351.0% | bull call spread `+1 C 510 / -1 C 530`, +120.8% | iron condor `-1 P 495 / +1 P 470 / -1 C 515 / +1 C 540`, +70.6% | iron condor `-1 P 470 / +1 P 450 / -1 C 500 / +1 C 520`, +129.4% | bear put spread `+1 P 485 / -1 P 450`, +197.8% | long call `+1 C 550`, +391.0% |
| NVDA | 2026-12-18 (29d) | bull call spread `+1 C 164 / -1 C 175`, +370.3% | bull call spread `+1 C 150 / -1 C 160`, +132.1% | iron condor `-1 P 142 / +1 P 134 / -1 C 160 / +1 C 168`, +87.1% | iron condor `-1 P 134 / +1 P 128 / -1 C 146 / +1 C 152`, +147.4% | bear put spread `+1 P 138 / -1 P 124`, +204.9% | bull call spread `+1 C 175 / -1 C 182`, +421.5% |
| SPY | 2026-12-18 (29d) | long call `+1 C 759`, +485.5% | bull call spread `+1 C 737 / -1 C 745`, +140.0% | iron condor `-1 P 709 / +1 P 695 / -1 C 745 / +1 C 759`, +84.1% | iron condor `-1 P 709 / +1 P 695 / -1 C 716 / +1 C 730`, +188.6% | bear put spread `+1 P 709 / -1 P 685`, +213.4% | long call `+1 C 759`, +506.4% |
| TSLA | 2026-12-18 (29d) | bull call spread `+1 C 420 / -1 C 450`, +365.0% | bull call spread `+1 C 390 / -1 C 405`, +127.9% | iron condor `-1 P 370 / +1 P 345 / -1 C 405 / +1 C 430`, +83.3% | iron condor `-1 P 350 / +1 P 330 / -1 C 375 / +1 C 395`, +133.8% | bear put spread `+1 P 350 / -1 P 320`, +200.5% | long strangle `+1 P 320 / +1 C 430`, +249.1% |
| XLF | 2026-12-18 (29d) | long call `+1 C 59`, +778.8% | bull call spread `+1 C 55 / -1 C 59`, +76.6% | iron condor `-1 P 55 / +1 P 53 / -1 C 58 / +1 C 60`, +25.3% | iron condor `-1 P 53 / +1 P 50 / -1 C 56 / +1 C 59`, +42.2% | bear put spread `+1 P 55 / -1 P 50`, +152.2% | long call `+1 C 59`, +923.5% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-19)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | TSLA | 2026-11-19 | 2026-12-02 | 13 | 370/362.5 | 3.92 | 1.49 | 65.1% | 59.6% | 41.98% | 1880375.0% |
| 2 | NVDA | 2026-11-19 | 2026-12-02 | 13 | 145/143 | 0.92 | 0.50 | 68.0% | 59.9% | 26.67% | 76162.8% |
| 3 | NVDA | 2026-11-19 | 2026-12-02 | 13 | 145/142 | 1.32 | 0.75 | 68.0% | 59.9% | 22.08% | 26993.1% |
| 4 | GOOGL | 2026-11-19 | 2026-12-02 | 13 | 272.5/270 | 1.23 | 0.05 | 60.7% | 52.9% | 20.44% | 18429.0% |
| 5 | TSLA | 2026-11-19 | 2026-12-02 | 13 | 370/360 | 3.90 | 2.09 | 65.1% | 59.6% | 17.16% | 8437.2% |
| 6 | NVDA | 2026-11-19 | 2026-12-02 | 13 | 145/140 | 2.05 | 1.65 | 68.0% | 59.9% | 16.99% | 8102.2% |
| 7 | GOOGL | 2026-11-19 | 2026-12-02 | 13 | 267.5/262.5 | 1.78 | 0.50 | 74.1% | 66.6% | 15.36% | 5421.9% |
| 8 | TSLA | 2026-11-19 | 2026-12-02 | 13 | 367.5/360 | 2.67 | 0.50 | 68.1% | 60.6% | 14.46% | 4334.0% |
| 9 | TSLA | 2026-11-19 | 2026-12-02 | 13 | 370/352.5 | 5.70 | 4.29 | 70.5% | 63.3% | 14.18% | 4036.0% |
| 10 | TSLA | 2026-11-19 | 2026-12-02 | 13 | 370/345 | 7.52 | 6.04 | 79.7% | 72.9% | 13.60% | 3491.2% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-19)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-02 | 610/575 | 0.34 | 0.32 | 0.06 | +0.28 | 81.5% | 99.7% | 98.6% | 99.0% | +0.7 pp | 0.20 |
| 2 | SPY | 2026-12-02 | 625/575 | 0.58 | 0.56 | 0.11 | +0.47 | 80.5% | 99.6% | 97.9% | 98.8% | +0.7 pp | 0.22 |
| 3 | SPY | 2026-12-02 | 625/590 | 0.46 | 0.44 | 0.09 | +0.37 | 79.9% | 99.6% | 97.9% | 98.7% | +0.9 pp | 0.23 |
| 4 | AAPL | 2026-12-18 | 290/260 | 0.33 | 0.17 | 0.07 | +0.26 | 78.6% | 99.4% | 97.6% | 98.9% | +0.5 pp | 0.21 |
| 5 | AAPL | 2026-12-04 | 305/280 | 0.31 | 0.16 | 0.07 | +0.24 | 78.2% | 99.6% | 97.9% | 98.8% | +0.8 pp | 0.20 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 71 breaches in 53,722, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,380 eligible spreads of the latest session the median annualised return is 1.2% under the risk-neutral CDF and 78.6% after calibration, against a cash rate of 3.6%.

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
