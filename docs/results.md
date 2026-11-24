# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-23 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-23 | 1,227 | 3,893 | 3,804 | 48,180 |
| AMD | 2020-01-06 | 2026-11-23 | 1,224 | 3,887 | 3,797 | 48,182 |
| AMZN | 2020-01-06 | 2026-11-23 | 1,223 | 3,882 | 3,793 | 47,875 |
| DIA | 2020-01-06 | 2026-11-23 | 1,225 | 3,901 | 3,792 | 47,564 |
| GOOGL | 2020-01-06 | 2026-11-23 | 1,218 | 3,868 | 3,778 | 47,725 |
| META | 2022-07-01 | 2026-11-23 | 858 | 2,786 | 2,696 | 33,956 |
| MSFT | 2020-01-06 | 2026-11-23 | 1,213 | 3,847 | 3,758 | 47,437 |
| NVDA | 2020-01-06 | 2026-11-23 | 1,222 | 3,870 | 3,781 | 47,296 |
| SPY | 2020-01-06 | 2026-11-23 | 1,215 | 3,897 | 3,798 | 47,152 |
| TSLA | 2021-01-04 | 2026-11-23 | 1,073 | 3,425 | 3,336 | 42,188 |
| XLF | 2020-01-06 | 2026-11-23 | 1,215 | 3,870 | 3,777 | 47,808 |

In total: 1,885,933 quotes on 539,622 contracts, in 41,126 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,875 | 97.0% | enters the calibration sample |
| `unsettled` | 1,016 | 2.5% | the expiration is after the last priced session, so there is no outcome yet |
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

Brier change +0.0029 (95% cluster-bootstrap interval +0.0002 to +0.0058, resampling expiration dates; negative means calibration helped) over 457,830 predictions, 35,960 snapshots and 897 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 144,925 | 0.1022 | 0.1049 | 0.0176 | 0.0234 |
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
| SPY | 41,867 | 0.0702 | 0.0714 | 0.0240 | 0.0110 |
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
| 2026 | 106,237 | 0.1300 | 0.1314 | 0.0132 | 0.0316 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 138,873 | 0.0363 | 0.0203 | 170,146 | 0.0317 | 0.0408 |
| 0.1-0.2 | 56,876 | 0.1468 | 0.1164 | 63,446 | 0.1481 | 0.1962 |
| 0.2-0.3 | 41,027 | 0.2471 | 0.2117 | 39,972 | 0.2568 | 0.2870 |
| 0.3-0.4 | 33,520 | 0.3502 | 0.3036 | 30,996 | 0.3606 | 0.4088 |
| 0.4-0.5 | 36,028 | 0.4516 | 0.4089 | 25,333 | 0.4464 | 0.4755 |
| 0.5-0.6 | 28,057 | 0.5529 | 0.5062 | 29,000 | 0.5470 | 0.5734 |
| 0.6-0.7 | 33,713 | 0.6504 | 0.6012 | 32,969 | 0.6544 | 0.6648 |
| 0.7-0.8 | 31,368 | 0.7481 | 0.6958 | 21,304 | 0.7503 | 0.7554 |
| 0.8-0.9 | 25,261 | 0.8481 | 0.8198 | 16,800 | 0.8509 | 0.8649 |
| 0.9-1.0 | 33,107 | 0.9619 | 0.9567 | 27,864 | 0.9673 | 0.9679 |

## Top 10 to enter (2026-11-23)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-23 | 2027-01-15 | 53 | 720/710 | 3.15 | 3.29 | 73.8% | 9.59% | 87.9% | 18.6% | 0.14 | 21.7% |
| 2 | SPY | 2026-11-23 | 2027-01-15 | 53 | 720/700 | 5.88 | 6.01 | 74.3% | 8.55% | 75.9% | 18.7% | 0.14 | 15.9% |
| 3 | AMZN | 2026-11-23 | 2027-01-15 | 53 | 250/235 | 4.50 | 4.75 | 73.8% | 8.75% | 78.2% | 17.8% | 0.14 | 11.1% |
| 4 | SPY | 2026-11-23 | 2027-01-15 | 53 | 720/695 | 7.08 | 7.20 | 74.3% | 7.89% | 68.7% | 18.2% | 0.13 | 10.8% |
| 5 | SPY | 2026-11-23 | 2027-01-15 | 53 | 710/695 | 3.81 | 3.91 | 77.3% | 6.86% | 57.9% | 18.0% | 0.12 | 9.5% |
| 6 | SPY | 2026-11-23 | 2027-01-15 | 53 | 710/680 | 6.81 | 6.91 | 79.4% | 6.23% | 51.6% | 19.1% | 0.12 | 8.1% |
| 7 | MSFT | 2026-11-23 | 2027-01-15 | 53 | 490/455 | 10.30 | 11.15 | 74.3% | 9.67% | 88.9% | 19.6% | 0.15 | 6.6% |
| 8 | SPY | 2026-11-23 | 2027-01-15 | 53 | 715/695 | 5.33 | 5.49 | 75.4% | 7.36% | 63.1% | 18.1% | 0.12 | 6.0% |
| 9 | SPY | 2026-11-23 | 2027-01-15 | 53 | 695/680 | 2.91 | 3.00 | 82.5% | 5.65% | 46.0% | 20.5% | 0.12 | 5.6% |
| 10 | AMZN | 2026-11-23 | 2027-01-15 | 53 | 255/235 | 6.65 | 7.00 | 69.3% | 9.36% | 85.2% | 16.4% | 0.14 | 4.3% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-23)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-31 (38d) | long call `+1 C 375`, +360.9% | bull put spread `-1 P 375 / +1 P 350`, +89.7% | iron condor `-1 P 345 / +1 P 330 / -1 C 370 / +1 C 385`, +40.0% | iron condor `-1 P 335 / +1 P 320 / -1 C 350 / +1 C 365`, +106.8% | bear put spread `+1 P 345 / -1 P 315`, +169.3% | long strangle `+1 P 320 / +1 C 375`, +237.3% |
| AMD | 2026-12-31 (38d) | long call `+1 C 535`, +358.8% | bull call spread `+1 C 465 / -1 C 510`, +106.2% | iron condor `-1 P 440 / +1 P 395 / -1 C 520 / +1 C 565`, +49.5% | iron condor `-1 P 385 / +1 P 340 / -1 C 455 / +1 C 500`, +83.5% | long put `+1 P 410`, +193.3% | long call `+1 C 565`, +380.6% |
| AMZN | 2026-12-31 (38d) | long call `+1 C 280`, +354.6% | bull call spread `+1 C 265 / -1 C 280`, +95.4% | iron condor `-1 P 255 / +1 P 235 / -1 C 275 / +1 C 295`, +55.3% | iron condor `-1 P 235 / +1 P 215 / -1 C 260 / +1 C 280`, +70.7% | bear put spread `+1 P 245 / -1 P 225`, +164.4% | long strangle `+1 P 235 / +1 C 280`, +212.9% |
| DIA | 2026-12-31 (38d) | long call `+1 C 526`, +436.5% | bull call spread `+1 C 506 / -1 C 516`, +108.3% | iron condor `-1 P 491 / +1 P 476 / -1 C 511 / +1 C 526`, +57.5% | iron condor `-1 P 481 / +1 P 466 / -1 C 496 / +1 C 511`, +120.8% | bear put spread `+1 P 491 / -1 P 456`, +195.5% | long strangle `+1 P 434 / +1 C 526`, +260.3% |
| GOOGL | 2026-12-31 (38d) | bull call spread `+1 C 315 / -1 C 340`, +320.4% | bull put spread `-1 P 300 / +1 P 280`, +94.0% | iron condor `-1 P 280 / +1 P 265 / -1 C 300 / +1 C 315`, +52.0% | iron condor `-1 P 265 / +1 P 245 / -1 C 285 / +1 C 305`, +74.7% | bear put spread `+1 P 270 / -1 P 245`, +188.0% | long strangle `+1 P 245 / +1 C 315`, +191.6% |
| META | 2026-12-31 (38d) | long call `+1 C 655`, +328.7% | bull call spread `+1 C 610 / -1 C 655`, +112.6% | iron condor `-1 P 590 / +1 P 540 / -1 C 635 / +1 C 685`, +63.0% | iron condor `-1 P 560 / +1 P 525 / -1 C 600 / +1 C 635`, +100.8% | bear put spread `+1 P 575 / -1 P 525`, +187.8% | long call `+1 C 700`, +374.3% |
| MSFT | 2026-12-31 (38d) | long call `+1 C 530`, +303.8% | bull put spread `-1 P 530 / +1 P 495`, +99.4% | iron condor `-1 P 490 / +1 P 445 / -1 C 520 / +1 C 565`, +47.2% | iron condor `-1 P 465 / +1 P 430 / -1 C 495 / +1 C 530`, +76.9% | long put `+1 P 485`, +165.7% | long strangle `+1 P 445 / +1 C 540`, +186.1% |
| NVDA | 2026-12-31 (38d) | long call `+1 C 190`, +349.0% | bull call spread `+1 C 165 / -1 C 180`, +122.5% | iron condor `-1 P 160 / +1 P 145 / -1 C 180 / +1 C 195`, +75.1% | iron condor `-1 P 145 / +1 P 135 / -1 C 170 / +1 C 180`, +96.9% | bear put spread `+1 P 150 / -1 P 135`, +192.9% | long strangle `+1 P 145 / +1 C 185`, +216.9% |
| SPY | 2026-12-31 (38d) | long call `+1 C 766`, +495.7% | bull call spread `+1 C 744 / -1 C 751`, +139.0% | iron condor `-1 P 722 / +1 P 708 / -1 C 737 / +1 C 751`, +81.6% | iron condor `-1 P 715 / +1 P 701 / -1 C 730 / +1 C 744`, +178.5% | bear put spread `+1 P 715 / -1 P 693`, +217.6% | long call `+1 C 766`, +505.3% |
| TSLA | 2026-12-31 (38d) | long call `+1 C 435`, +333.5% | bull call spread `+1 C 390 / -1 C 425`, +97.6% | iron condor `-1 P 385 / +1 P 355 / -1 C 415 / +1 C 445`, +72.0% | iron condor `-1 P 345 / +1 P 320 / -1 C 390 / +1 C 415`, +91.8% | bear put spread `+1 P 370 / -1 P 335`, +185.5% | long strangle `+1 P 330 / +1 C 435`, +232.9% |
| XLF | 2026-12-31 (38d) | long call `+1 C 57`, +154.1% | bull put spread `-1 P 58 / +1 P 56`, +68.5% | bull put spread `-1 P 57 / +1 P 53`, +21.9% | bear call spread `-1 C 55 / +1 C 58`, +27.1% | long put `+1 P 56`, +153.4% | long strangle `+1 P 53 / +1 C 58`, +111.5% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-23)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMD | 2026-11-23 | 2026-12-07 | 14 | 450/440 | 5.75 | 0.30 | 56.4% | 50.3% | 35.57% | 279068.4% |
| 2 | TSLA | 2026-11-23 | 2026-12-07 | 14 | 370/360 | 3.89 | 1.34 | 78.3% | 72.3% | 31.16% | 117751.0% |
| 3 | NVDA | 2026-11-23 | 2026-12-18 | 25 | 164/162 | 1.15 | 0.75 | 60.4% | 53.6% | 42.29% | 17139.8% |
| 4 | TSLA | 2026-11-23 | 2026-12-07 | 14 | 370/355 | 4.52 | 0.39 | 78.3% | 72.3% | 18.40% | 8065.9% |
| 5 | AAPL | 2026-11-23 | 2026-12-07 | 14 | 345/340 | 1.77 | 0.70 | 73.3% | 65.7% | 15.14% | 3849.5% |
| 6 | TSLA | 2026-11-23 | 2026-12-07 | 14 | 380/360 | 6.85 | 4.75 | 75.4% | 70.4% | 14.85% | 3594.1% |
| 7 | TSLA | 2026-11-23 | 2026-12-07 | 14 | 385/375 | 4.41 | 1.25 | 62.8% | 57.8% | 14.60% | 3392.1% |
| 8 | META | 2026-11-23 | 2026-12-07 | 14 | 590/580 | 4.02 | 0.15 | 67.3% | 59.7% | 13.83% | 2826.5% |
| 9 | XLF | 2026-11-23 | 2026-12-18 | 25 | 55.5/54.5 | 0.44 | 0.11 | 69.3% | 62.2% | 25.28% | 2586.0% |
| 10 | GOOGL | 2026-11-23 | 2026-12-07 | 14 | 280/270 | 3.84 | 0.85 | 68.9% | 61.5% | 13.11% | 2380.6% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-23)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-04 | 630/596 | 0.33 | 0.32 | 0.06 | +0.27 | 81.0% | 99.7% | 98.4% | 99.0% | +0.7 pp | 0.20 |
| 2 | SPY | 2026-12-18 | 580/540 | 0.42 | 0.40 | 0.08 | +0.34 | 80.9% | 99.7% | 98.6% | 98.9% | +0.8 pp | 0.21 |
| 3 | SPY | 2026-12-04 | 615/578 | 0.26 | 0.24 | 0.05 | +0.21 | 80.3% | 99.9% | 99.0% | 99.3% | +0.6 pp | 0.15 |
| 4 | SPY | 2026-12-18 | 595/540 | 0.67 | 0.64 | 0.13 | +0.53 | 80.3% | 99.5% | 98.1% | 98.8% | +0.7 pp | 0.22 |
| 5 | AAPL | 2026-12-18 | 290/260 | 0.29 | 0.18 | 0.06 | +0.24 | 80.2% | 99.7% | 98.4% | 99.0% | +0.7 pp | 0.20 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 73 breaches in 53,959, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,287 eligible spreads of the latest session the median annualised return is 1.5% under the risk-neutral CDF and 81.7% after calibration, against a cash rate of 3.6%.

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
