# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-29 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-29 | 1,210 | 3,827 | 3,734 | 47,274 |
| AMD | 2020-01-06 | 2026-10-29 | 1,207 | 3,821 | 3,728 | 47,319 |
| AMZN | 2020-01-06 | 2026-10-29 | 1,206 | 3,816 | 3,723 | 46,965 |
| DIA | 2020-01-06 | 2026-10-29 | 1,208 | 3,833 | 3,721 | 46,688 |
| GOOGL | 2020-01-06 | 2026-10-29 | 1,201 | 3,802 | 3,708 | 46,817 |
| META | 2022-07-01 | 2026-10-29 | 841 | 2,720 | 2,627 | 33,101 |
| MSFT | 2020-01-06 | 2026-10-29 | 1,196 | 3,782 | 3,689 | 46,571 |
| NVDA | 2020-01-06 | 2026-10-29 | 1,205 | 3,805 | 3,714 | 46,425 |
| SPY | 2020-01-06 | 2026-10-29 | 1,198 | 3,829 | 3,722 | 46,187 |
| TSLA | 2021-01-04 | 2026-10-29 | 1,056 | 3,359 | 3,266 | 41,293 |
| XLF | 2020-01-06 | 2026-10-29 | 1,198 | 3,802 | 3,709 | 46,930 |

In total: 1,850,667 quotes on 529,531 contracts, in 40,396 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,106 | 96.8% | enters the calibration sample |
| `unsettled` | 1,055 | 2.6% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1263 | 0.1288 | +0.0025 |
| Log loss (nats) | 0.3908 | 0.3951 | +0.0042 |
| Expected calibration error | 0.0350 | 0.0165 | -0.0186 |

Brier change +0.0025 (95% cluster-bootstrap interval -0.0006 to +0.0055, resampling expiration dates; negative means calibration helped) over 448,037 predictions, 35,192 snapshots and 883 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 142,414 | 0.1017 | 0.1042 | 0.0195 | 0.0216 |
| 21-35d | 142,379 | 0.1269 | 0.1300 | 0.0326 | 0.0211 |
| 36-50d | 84,455 | 0.1477 | 0.1492 | 0.0482 | 0.0141 |
| >50d | 78,789 | 0.1468 | 0.1490 | 0.0541 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,288 | 0.1195 | 0.1204 | 0.0422 | 0.0173 |
| AMD | 41,893 | 0.1806 | 0.1847 | 0.0423 | 0.0395 |
| AMZN | 41,603 | 0.1352 | 0.1402 | 0.0285 | 0.0272 |
| DIA | 41,293 | 0.0628 | 0.0632 | 0.0265 | 0.0155 |
| GOOGL | 41,537 | 0.1302 | 0.1296 | 0.0556 | 0.0124 |
| META | 33,101 | 0.1526 | 0.1545 | 0.0466 | 0.0176 |
| MSFT | 41,463 | 0.1190 | 0.1227 | 0.0211 | 0.0273 |
| NVDA | 41,021 | 0.1570 | 0.1562 | 0.0794 | 0.0172 |
| SPY | 40,902 | 0.0689 | 0.0697 | 0.0280 | 0.0096 |
| TSLA | 41,293 | 0.1822 | 0.1922 | 0.0076 | 0.0663 |
| XLF | 41,643 | 0.0858 | 0.0874 | 0.0219 | 0.0215 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 96,444 | 0.1253 | 0.1246 | 0.0320 | 0.0169 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 135,962 | 0.0363 | 0.0181 | 166,848 | 0.0317 | 0.0386 |
| 0.1-0.2 | 55,688 | 0.1469 | 0.1109 | 61,935 | 0.1480 | 0.1907 |
| 0.2-0.3 | 40,146 | 0.2472 | 0.2062 | 39,101 | 0.2567 | 0.2803 |
| 0.3-0.4 | 32,746 | 0.3501 | 0.2960 | 30,281 | 0.3605 | 0.4023 |
| 0.4-0.5 | 35,314 | 0.4517 | 0.4034 | 24,791 | 0.4464 | 0.4686 |
| 0.5-0.6 | 27,357 | 0.5529 | 0.4983 | 28,253 | 0.5472 | 0.5657 |
| 0.6-0.7 | 32,925 | 0.6504 | 0.5945 | 32,080 | 0.6544 | 0.6572 |
| 0.7-0.8 | 30,602 | 0.7481 | 0.6893 | 20,895 | 0.7503 | 0.7513 |
| 0.8-0.9 | 24,786 | 0.8482 | 0.8169 | 16,512 | 0.8509 | 0.8631 |
| 0.9-1.0 | 32,511 | 0.9619 | 0.9561 | 27,341 | 0.9673 | 0.9676 |

## Top 10 to enter (2026-10-29)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMZN | 2026-10-29 | 2026-12-18 | 50 | 235/230 | 2.00 | 2.00 | 69.9% | 17.03% | 215.1% | 24.8% | 0.22 | 78.2% |
| 2 | TSLA | 2026-10-29 | 2026-12-18 | 50 | 395/380 | 5.45 | 5.62 | 69.9% | 11.32% | 118.8% | 18.1% | 0.15 | 32.8% |
| 3 | TSLA | 2026-10-29 | 2026-12-18 | 50 | 400/370 | 10.65 | 10.85 | 69.9% | 10.57% | 108.2% | 17.8% | 0.15 | 30.1% |
| 4 | AMZN | 2026-10-29 | 2026-12-18 | 50 | 235/225 | 3.65 | 3.83 | 69.9% | 15.05% | 178.3% | 23.5% | 0.20 | 29.9% |
| 5 | NVDA | 2026-10-29 | 2026-12-18 | 50 | 210/200 | 3.55 | 3.70 | 69.9% | 11.01% | 114.4% | 18.0% | 0.15 | 24.5% |
| 6 | TSLA | 2026-10-29 | 2026-12-18 | 50 | 395/385 | 3.75 | 3.92 | 68.0% | 11.54% | 121.9% | 17.1% | 0.15 | 24.3% |
| 7 | NVDA | 2026-10-29 | 2026-12-18 | 50 | 212/200 | 4.44 | 4.59 | 68.0% | 11.02% | 114.5% | 17.0% | 0.15 | 23.8% |
| 8 | TSLA | 2026-10-29 | 2026-12-18 | 50 | 395/370 | 8.40 | 8.57 | 70.8% | 10.34% | 105.1% | 18.9% | 0.16 | 22.0% |
| 9 | TSLA | 2026-10-29 | 2026-12-18 | 50 | 390/365 | 7.55 | 7.75 | 74.3% | 9.55% | 94.7% | 20.2% | 0.15 | 20.7% |
| 10 | TSLA | 2026-10-29 | 2026-12-18 | 50 | 400/365 | 11.90 | 12.07 | 69.9% | 9.93% | 99.6% | 17.9% | 0.15 | 20.4% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-10-29)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-04 (36d) | long call `+1 C 370`, +331.7% | bull call spread `+1 C 355 / -1 C 370`, +100.1% | iron condor `-1 P 345 / +1 P 320 / -1 C 360 / +1 C 385`, +52.7% | iron condor `-1 P 340 / +1 P 320 / -1 C 350 / +1 C 370`, +89.9% | bear put spread `+1 P 345 / -1 P 320`, +165.7% | long call `+1 C 375`, +316.8% |
| AMD | 2026-11-27 (29d) | long call `+1 C 650`, +366.9% | bull put spread `-1 P 635 / +1 P 600`, +78.2% | iron condor `-1 P 455 / +1 P 425 / -1 C 650 / +1 C 680`, +21.7% | bear put spread `+1 P 625 / -1 P 600`, +34.4% | long put `+1 P 600`, +130.2% | long call `+1 C 680`, +423.8% |
| AMZN | 2026-11-27 (29d) | long call `+1 C 270`, +350.6% | bull call spread `+1 C 255 / -1 C 260`, +108.6% | iron condor `-1 P 240 / +1 P 220 / -1 C 255 / +1 C 275`, +79.0% | iron condor `-1 P 225 / +1 P 215 / -1 C 245 / +1 C 255`, +118.5% | bear put spread `+1 P 235 / -1 P 215`, +177.5% | long call `+1 C 285`, +426.1% |
| DIA | 2026-11-27 (29d) | long call `+1 C 538`, +357.9% | bull call spread `+1 C 528 / -1 C 538`, +102.4% | iron condor `-1 P 522.5 / +1 P 512.5 / -1 C 528 / +1 C 538`, +39.6% | bear call spread `-1 C 522.5 / +1 C 533`, +56.5% | bear put spread `+1 P 517.5 / -1 P 490`, +172.8% | long strangle `+1 P 445 / +1 C 544`, +294.2% |
| GOOGL | 2026-11-27 (29d) | bull call spread `+1 C 300 / -1 C 320`, +343.5% | bull call spread `+1 C 285 / -1 C 300`, +131.4% | iron condor `-1 P 280 / +1 P 265 / -1 C 295 / +1 C 310`, +61.5% | iron condor `-1 P 270 / +1 P 260 / -1 C 285 / +1 C 295`, +88.2% | bear put spread `+1 P 275 / -1 P 250`, +180.0% | long call `+1 C 310`, +351.8% |
| META | 2026-11-27 (29d) | bull put spread `-1 P 720 / +1 P 660`, +381.3% | bull put spread `-1 P 675 / +1 P 630`, +134.2% | iron condor `-1 P 620 / +1 P 585 / -1 C 650 / +1 C 685`, +77.8% | iron condor `-1 P 585 / +1 P 560 / -1 C 625 / +1 C 650`, +104.0% | bear put spread `+1 P 600 / -1 P 545`, +190.6% | long strangle `+1 P 545 / +1 C 705`, +276.0% |
| MSFT | 2026-11-27 (29d) | long call `+1 C 560`, +368.6% | bull call spread `+1 C 530 / -1 C 560`, +110.5% | iron condor `-1 P 530 / +1 P 500 / -1 C 545 / +1 C 575`, +57.4% | iron condor `-1 P 515 / +1 P 490 / -1 C 535 / +1 C 560`, +67.3% | bear put spread `+1 P 520 / -1 P 475`, +168.4% | long call `+1 C 575`, +450.0% |
| NVDA | 2026-11-27 (29d) | bull call spread `+1 C 235 / -1 C 250`, +367.1% | bull call spread `+1 C 220 / -1 C 230`, +128.2% | iron condor `-1 P 210 / +1 P 200 / -1 C 225 / +1 C 235`, +82.2% | iron condor `-1 P 200 / +1 P 190 / -1 C 215 / +1 C 225`, +122.1% | bear put spread `+1 P 205 / -1 P 185`, +198.8% | long strangle `+1 P 185 / +1 C 240`, +238.3% |
| SPY | 2026-12-04 (36d) | long call `+1 C 800`, +529.0% | bull call spread `+1 C 777 / -1 C 792`, +130.6% | iron condor `-1 P 769 / +1 P 762 / -1 C 785 / +1 C 792`, +89.6% | iron condor `-1 P 754 / +1 P 746 / -1 C 777 / +1 C 785`, +134.5% | bear put spread `+1 P 762 / -1 P 746`, +208.9% | long call `+1 C 800`, +592.9% |
| TSLA | 2026-11-27 (29d) | bull call spread `+1 C 435 / -1 C 465`, +370.7% | bull call spread `+1 C 410 / -1 C 425`, +134.5% | iron condor `-1 P 400 / +1 P 385 / -1 C 420 / +1 C 435`, +87.6% | iron condor `-1 P 380 / +1 P 370 / -1 C 405 / +1 C 415`, +138.0% | bear put spread `+1 P 385 / -1 P 365`, +202.1% | bull call spread `+1 C 455 / -1 C 485`, +424.4% |
| XLF | 2026-11-27 (29d) | long call `+1 C 58.5`, +159.8% | bull put spread `-1 P 58 / +1 P 54.5`, +17.8% | iron condor `-1 P 56 / +1 P 51 / -1 C 58 / +1 C 63`, +8.6% | bear call spread `-1 C 56 / +1 C 60`, +14.0% | long put `+1 P 57`, +64.2% | long call `+1 C 58.5`, +104.2% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-10-29)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMZN | 2026-10-29 | 2026-11-13 | 15 | 237.5/235 | 1.15 | 0.40 | 69.9% | 61.9% | 29.82% | 57214.2% |
| 2 | AMZN | 2026-10-29 | 2026-11-13 | 15 | 242.5/240 | 1.37 | 0.30 | 55.2% | 46.7% | 24.73% | 21534.3% |
| 3 | AMZN | 2026-10-29 | 2026-11-13 | 15 | 237.5/230 | 2.92 | 2.25 | 70.8% | 63.0% | 17.08% | 4538.4% |
| 4 | MSFT | 2026-10-29 | 2026-11-13 | 15 | 530/525 | 2.30 | 1.45 | 60.8% | 53.8% | 14.64% | 2678.7% |
| 5 | AMZN | 2026-10-29 | 2026-11-13 | 15 | 242.5/235 | 3.27 | 2.30 | 64.1% | 58.9% | 14.46% | 2576.3% |
| 6 | META | 2026-10-29 | 2026-11-13 | 15 | 617.5/612.5 | 2.29 | 1.30 | 60.8% | 54.0% | 13.39% | 2029.3% |
| 7 | AMZN | 2026-10-29 | 2026-11-13 | 15 | 237.5/225 | 4.38 | 3.75 | 70.8% | 64.0% | 13.35% | 2008.9% |
| 8 | AMZN | 2026-10-29 | 2026-11-13 | 15 | 242.5/230 | 5.05 | 4.15 | 69.9% | 61.9% | 13.29% | 1981.6% |
| 9 | TSLA | 2026-10-29 | 2026-11-13 | 15 | 402.5/400 | 1.15 | 1.00 | 60.8% | 53.8% | 12.72% | 1742.5% |
| 10 | GOOGL | 2026-10-29 | 2026-11-13 | 15 | 277.5/275 | 0.93 | 0.40 | 70.2% | 62.0% | 12.03% | 1487.2% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-10-29)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-04 | 655/615 | 0.42 | 0.40 | 0.07 | +0.36 | 84.4% | 99.8% | 98.5% | 98.9% | +0.8 pp | 0.24 |
| 2 | SPY | 2026-12-18 | 615/575 | 0.41 | 0.39 | 0.06 | +0.35 | 84.3% | 99.8% | 98.6% | 99.0% | +0.8 pp | 0.23 |
| 3 | SPY | 2026-12-18 | 635/575 | 0.71 | 0.69 | 0.11 | +0.60 | 84.0% | 99.6% | 98.2% | 98.8% | +0.8 pp | 0.25 |
| 4 | SPY | 2026-11-27 | 675/635 | 0.44 | 0.41 | 0.07 | +0.37 | 83.9% | 99.7% | 98.3% | 98.9% | +0.8 pp | 0.24 |
| 5 | SPY | 2026-12-18 | 635/615 | 0.30 | 0.28 | 0.05 | +0.26 | 83.7% | 99.6% | 98.2% | 98.5% | +1.2 pp | 0.27 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,935, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,217 eligible spreads of the latest session the median annualised return is 0.8% under the risk-neutral CDF and 77.8% after calibration, against a cash rate of 3.6%.

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
