# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-25 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-25 | 1,229 | 3,901 | 3,805 | 48,193 |
| AMD | 2020-01-06 | 2026-11-25 | 1,226 | 3,895 | 3,798 | 48,195 |
| AMZN | 2020-01-06 | 2026-11-25 | 1,225 | 3,890 | 3,794 | 47,888 |
| DIA | 2020-01-06 | 2026-11-25 | 1,227 | 3,909 | 3,792 | 47,564 |
| GOOGL | 2020-01-06 | 2026-11-25 | 1,220 | 3,876 | 3,780 | 47,751 |
| META | 2022-07-01 | 2026-11-25 | 860 | 2,794 | 2,697 | 33,968 |
| MSFT | 2020-01-06 | 2026-11-25 | 1,215 | 3,855 | 3,760 | 47,458 |
| NVDA | 2020-01-06 | 2026-11-25 | 1,224 | 3,878 | 3,783 | 47,322 |
| SPY | 2020-01-06 | 2026-11-25 | 1,217 | 3,905 | 3,800 | 47,178 |
| TSLA | 2021-01-04 | 2026-11-25 | 1,075 | 3,433 | 3,337 | 42,201 |
| XLF | 2020-01-06 | 2026-11-25 | 1,217 | 3,878 | 3,780 | 47,847 |

In total: 1,890,125 quotes on 541,004 contracts, in 41,214 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,891 | 96.8% | enters the calibration sample |
| `unsettled` | 1,088 | 2.6% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1274 | 0.1303 | +0.0029 |
| Log loss (nats) | 0.3941 | 0.3997 | +0.0055 |
| Expected calibration error | 0.0305 | 0.0209 | -0.0096 |

Brier change +0.0029 (95% cluster-bootstrap interval +0.0003 to +0.0057, resampling expiration dates; negative means calibration helped) over 458,032 predictions, 35,976 snapshots and 899 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 145,127 | 0.1023 | 0.1050 | 0.0173 | 0.0238 |
| 21-35d | 145,364 | 0.1282 | 0.1316 | 0.0282 | 0.0249 |
| 36-50d | 87,102 | 0.1488 | 0.1510 | 0.0413 | 0.0183 |
| >50d | 80,439 | 0.1481 | 0.1510 | 0.0476 | 0.0172 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 43,207 | 0.1183 | 0.1191 | 0.0427 | 0.0145 |
| AMD | 42,769 | 0.1825 | 0.1876 | 0.0340 | 0.0455 |
| AMZN | 42,526 | 0.1345 | 0.1395 | 0.0275 | 0.0282 |
| DIA | 42,169 | 0.0634 | 0.0641 | 0.0243 | 0.0162 |
| GOOGL | 42,471 | 0.1351 | 0.1357 | 0.0439 | 0.0192 |
| META | 33,968 | 0.1557 | 0.1588 | 0.0356 | 0.0217 |
| MSFT | 42,350 | 0.1187 | 0.1226 | 0.0193 | 0.0291 |
| NVDA | 41,918 | 0.1613 | 0.1615 | 0.0674 | 0.0203 |
| SPY | 41,893 | 0.0702 | 0.0714 | 0.0239 | 0.0110 |
| TSLA | 42,201 | 0.1812 | 0.1910 | 0.0085 | 0.0650 |
| XLF | 42,560 | 0.0854 | 0.0869 | 0.0221 | 0.0211 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 106,439 | 0.1300 | 0.1315 | 0.0127 | 0.0320 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 138,953 | 0.0363 | 0.0204 | 170,233 | 0.0317 | 0.0408 |
| 0.1-0.2 | 56,894 | 0.1468 | 0.1165 | 63,466 | 0.1481 | 0.1963 |
| 0.2-0.3 | 41,039 | 0.2471 | 0.2119 | 39,986 | 0.2568 | 0.2872 |
| 0.3-0.4 | 33,532 | 0.3502 | 0.3038 | 31,005 | 0.3606 | 0.4090 |
| 0.4-0.5 | 36,037 | 0.4516 | 0.4091 | 25,339 | 0.4464 | 0.4757 |
| 0.5-0.6 | 28,069 | 0.5529 | 0.5064 | 29,013 | 0.5470 | 0.5736 |
| 0.6-0.7 | 33,723 | 0.6504 | 0.6013 | 32,981 | 0.6544 | 0.6649 |
| 0.7-0.8 | 31,378 | 0.7481 | 0.6959 | 21,313 | 0.7503 | 0.7555 |
| 0.8-0.9 | 25,276 | 0.8481 | 0.8199 | 16,811 | 0.8509 | 0.8650 |
| 0.9-1.0 | 33,131 | 0.9619 | 0.9567 | 27,885 | 0.9674 | 0.9679 |

## Top 10 to enter (2026-11-25)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-25 | 2027-01-15 | 51 | 715/700 | 4.62 | 4.82 | 73.8% | 8.77% | 82.5% | 17.5% | 0.13 | 18.2% |
| 2 | SPY | 2026-11-25 | 2027-01-15 | 51 | 715/695 | 5.95 | 6.15 | 74.3% | 8.64% | 80.9% | 18.4% | 0.14 | 16.8% |
| 3 | SPY | 2026-11-25 | 2027-01-15 | 51 | 715/690 | 7.17 | 7.37 | 74.3% | 8.06% | 74.1% | 18.1% | 0.13 | 11.6% |
| 4 | SPY | 2026-11-25 | 2027-01-15 | 51 | 700/690 | 2.41 | 2.55 | 79.4% | 7.09% | 63.2% | 19.3% | 0.12 | 10.4% |
| 5 | SPY | 2026-11-25 | 2027-01-15 | 51 | 710/700 | 2.91 | 3.06 | 74.3% | 8.28% | 76.7% | 17.7% | 0.13 | 10.0% |
| 6 | SPY | 2026-11-25 | 2027-01-15 | 51 | 710/695 | 4.24 | 4.39 | 74.3% | 8.28% | 76.7% | 18.8% | 0.13 | 8.1% |
| 7 | SPY | 2026-11-25 | 2027-01-15 | 51 | 700/675 | 5.49 | 5.62 | 79.7% | 6.19% | 53.7% | 19.6% | 0.12 | 5.4% |
| 8 | SPY | 2026-11-25 | 2027-01-15 | 51 | 710/690 | 5.46 | 5.61 | 74.3% | 7.66% | 69.6% | 18.4% | 0.13 | 4.3% |
| 9 | SPY | 2026-11-25 | 2027-01-15 | 51 | 710/660 | 10.90 | 11.05 | 79.4% | 5.94% | 51.1% | 19.2% | 0.12 | 4.2% |
| 10 | SPY | 2026-11-25 | 2027-01-15 | 51 | 690/660 | 5.30 | 5.44 | 83.6% | 4.92% | 41.1% | 20.0% | 0.11 | 3.4% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-25)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-24 (29d) | long call `+1 C 375`, +335.5% | bull call spread `+1 C 360 / -1 C 375`, +93.4% | iron condor `-1 P 355 / +1 P 340 / -1 C 370 / +1 C 385`, +54.3% | iron condor `-1 P 345 / +1 P 335 / -1 C 360 / +1 C 370`, +93.0% | bear put spread `+1 P 350 / -1 P 320`, +187.4% | long call `+1 C 385`, +462.6% |
| AMD | 2026-12-24 (29d) | long call `+1 C 485`, +330.1% | bull call spread `+1 C 415 / -1 C 455`, +96.5% | iron condor `-1 P 380 / +1 P 345 / -1 C 475 / +1 C 510`, +42.2% | iron condor `-1 P 335 / +1 P 300 / -1 C 410 / +1 C 445`, +60.5% | long put `+1 P 380`, +186.5% | long strangle `+1 P 355 / +1 C 465`, +177.2% |
| AMZN | 2026-12-24 (29d) | long call `+1 C 265`, +353.5% | bull call spread `+1 C 250 / -1 C 265`, +119.6% | iron condor `-1 P 240 / +1 P 220 / -1 C 255 / +1 C 275`, +60.0% | iron condor `-1 P 230 / +1 P 210 / -1 C 245 / +1 C 265`, +89.6% | bear put spread `+1 P 230 / -1 P 210`, +176.7% | long call `+1 C 280`, +411.0% |
| DIA | 2026-12-24 (29d) | long call `+1 C 521`, +329.9% | bull put spread `-1 P 521 / +1 P 506`, +95.9% | iron condor `-1 P 501 / +1 P 486 / -1 C 516 / +1 C 531`, +53.7% | iron condor `-1 P 480 / +1 P 470 / -1 C 506 / +1 C 516`, +79.3% | bear call spread `-1 C 460 / +1 C 496`, +190.1% | long call `+1 C 531`, +367.2% |
| GOOGL | 2026-12-24 (29d) | long call `+1 C 300`, +319.0% | bull call spread `+1 C 275 / -1 C 300`, +105.0% | iron condor `-1 P 270 / +1 P 250 / -1 C 285 / +1 C 305`, +61.1% | iron condor `-1 P 250 / +1 P 240 / -1 C 275 / +1 C 285`, +100.7% | bear put spread `+1 P 265 / -1 P 240`, +185.5% | long strangle `+1 P 240 / +1 C 305`, +242.7% |
| META | 2026-12-24 (29d) | long call `+1 C 660`, +330.4% | bull call spread `+1 C 610 / -1 C 660`, +111.3% | iron condor `-1 P 605 / +1 P 550 / -1 C 645 / +1 C 700`, +62.1% | iron condor `-1 P 560 / +1 P 535 / -1 C 610 / +1 C 635`, +109.1% | long put `+1 P 590`, +183.3% | long call `+1 C 700`, +328.3% |
| MSFT | 2026-12-24 (29d) | long call `+1 C 530`, +345.8% | bull call spread `+1 C 495 / -1 C 530`, +104.4% | iron condor `-1 P 485 / +1 P 450 / -1 C 505 / +1 C 540`, +43.8% | iron condor `-1 P 460 / +1 P 430 / -1 C 490 / +1 C 520`, +86.3% | bear put spread `+1 P 460 / -1 P 415`, +191.5% | long call `+1 C 550`, +433.8% |
| NVDA | 2026-12-31 (36d) | long call `+1 C 185`, +397.5% | bull call spread `+1 C 155 / -1 C 165`, +127.3% | iron condor `-1 P 145 / +1 P 135 / -1 C 160 / +1 C 170`, +83.3% | iron condor `-1 P 130 / +1 P 120 / -1 C 150 / +1 C 160`, +126.9% | bear put spread `+1 P 135 / -1 P 125`, +208.7% | long strangle `+1 P 130 / +1 C 170`, +239.5% |
| SPY | 2026-12-31 (36d) | long call `+1 C 760`, +501.0% | bull call spread `+1 C 738 / -1 C 745`, +137.5% | iron condor `-1 P 710 / +1 P 695 / -1 C 745 / +1 C 760`, +85.3% | iron condor `-1 P 695 / +1 P 674 / -1 C 717 / +1 C 738`, +179.1% | bear put spread `+1 P 710 / -1 P 688`, +218.1% | long call `+1 C 760`, +504.7% |
| TSLA | 2026-12-31 (36d) | long call `+1 C 430`, +353.8% | bull call spread `+1 C 385 / -1 C 420`, +115.1% | iron condor `-1 P 375 / +1 P 340 / -1 C 395 / +1 C 430`, +72.5% | iron condor `-1 P 350 / +1 P 315 / -1 C 385 / +1 C 420`, +97.1% | bear put spread `+1 P 355 / -1 P 325`, +185.2% | long call `+1 C 455`, +418.6% |
| XLF | 2026-12-24 (29d) | long call `+1 C 61`, +2253.3% | long call `+1 C 57`, +112.9% | bull call spread `+1 C 53 / -1 C 58`, +17.7% | bear call spread `-1 C 56 / +1 C 59`, +35.4% | long put `+1 P 57`, +119.5% | long strangle `+1 P 49 / +1 C 61`, +805.3% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-25)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | NVDA | 2026-11-25 | 2026-12-09 | 14 | 149/143 | 3.90 | 1.20 | 54.6% | 46.9% | 50.33% | 4126902.7% |
| 2 | NVDA | 2026-11-25 | 2026-12-09 | 14 | 146/143 | 1.77 | 0.30 | 54.6% | 46.9% | 37.18% | 379811.3% |
| 3 | NVDA | 2026-11-25 | 2026-12-09 | 14 | 149/145 | 2.43 | 0.25 | 54.6% | 46.9% | 28.46% | 68368.6% |
| 4 | TSLA | 2026-11-25 | 2026-12-09 | 14 | 372.5/365 | 3.40 | 1.25 | 68.9% | 61.1% | 26.38% | 44706.5% |
| 5 | AMZN | 2026-11-25 | 2026-12-09 | 14 | 230/225 | 1.44 | 0.25 | 84.6% | 80.1% | 20.30% | 12269.2% |
| 6 | TSLA | 2026-11-25 | 2026-12-09 | 14 | 380/365 | 6.73 | 3.75 | 68.9% | 61.1% | 19.67% | 10702.5% |
| 7 | NVDA | 2026-11-25 | 2026-12-09 | 14 | 149/140 | 4.43 | 2.40 | 54.6% | 46.9% | 19.07% | 9368.1% |
| 8 | NVDA | 2026-11-25 | 2026-12-09 | 14 | 149/137 | 5.38 | 3.25 | 58.8% | 51.2% | 18.57% | 8376.1% |
| 9 | GOOGL | 2026-11-25 | 2026-12-09 | 14 | 272.5/265 | 3.24 | 1.55 | 68.9% | 61.9% | 18.09% | 7539.0% |
| 10 | NVDA | 2026-11-25 | 2026-12-09 | 14 | 140/137 | 0.96 | 0.15 | 79.7% | 75.3% | 17.44% | 6505.7% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-25)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-08 | 610/575 | 0.32 | 0.30 | 0.06 | +0.26 | 80.8% | 99.7% | 98.6% | 99.1% | +0.6 pp | 0.19 |
| 2 | SPY | 2026-12-08 | 625/575 | 0.57 | 0.55 | 0.12 | +0.46 | 79.4% | 99.4% | 97.8% | 98.8% | +0.5 pp | 0.22 |
| 3 | SPY | 2026-12-08 | 625/590 | 0.46 | 0.44 | 0.10 | +0.37 | 79.1% | 99.4% | 97.8% | 98.7% | +0.7 pp | 0.23 |
| 4 | SPY | 2026-12-24 | 575/540 | 0.52 | 0.47 | 0.12 | +0.40 | 77.8% | 99.5% | 98.0% | 98.5% | +1.0 pp | 0.21 |
| 5 | SPY | 2026-12-08 | 625/610 | 0.26 | 0.23 | 0.06 | +0.20 | 77.7% | 99.4% | 97.8% | 98.3% | +1.1 pp | 0.23 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 74 breaches in 54,007, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,161 eligible spreads of the latest session the median annualised return is 1.5% under the risk-neutral CDF and 82.4% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.7 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.0%, right tail uncovered 15.2%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
