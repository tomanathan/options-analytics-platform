# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-28 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-28 | 1,209 | 3,823 | 3,734 | 47,274 |
| AMD | 2020-01-06 | 2026-10-28 | 1,206 | 3,817 | 3,728 | 47,319 |
| AMZN | 2020-01-06 | 2026-10-28 | 1,205 | 3,812 | 3,723 | 46,965 |
| DIA | 2020-01-06 | 2026-10-28 | 1,207 | 3,829 | 3,721 | 46,688 |
| GOOGL | 2020-01-06 | 2026-10-28 | 1,200 | 3,798 | 3,708 | 46,817 |
| META | 2022-07-01 | 2026-10-28 | 840 | 2,716 | 2,627 | 33,101 |
| MSFT | 2020-01-06 | 2026-10-28 | 1,195 | 3,778 | 3,689 | 46,571 |
| NVDA | 2020-01-06 | 2026-10-28 | 1,204 | 3,801 | 3,714 | 46,425 |
| SPY | 2020-01-06 | 2026-10-28 | 1,197 | 3,825 | 3,722 | 46,187 |
| TSLA | 2021-01-04 | 2026-10-28 | 1,055 | 3,355 | 3,266 | 41,293 |
| XLF | 2020-01-06 | 2026-10-28 | 1,197 | 3,798 | 3,709 | 46,930 |

In total: 1,848,690 quotes on 528,985 contracts, in 40,352 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,106 | 96.9% | enters the calibration sample |
| `unsettled` | 1,011 | 2.5% | the expiration is after the last priced session, so there is no outcome yet |
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

## Top 10 to enter (2026-10-28)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | META | 2026-10-28 | 2026-12-18 | 51 | 605/575 | 11.35 | 11.77 | 69.9% | 12.56% | 133.2% | 18.7% | 0.17 | 42.4% |
| 2 | META | 2026-10-28 | 2026-12-18 | 51 | 600/575 | 9.20 | 9.45 | 70.2% | 12.41% | 131.0% | 19.6% | 0.17 | 39.4% |
| 3 | META | 2026-10-28 | 2026-12-18 | 51 | 610/565 | 16.60 | 17.40 | 70.2% | 13.05% | 140.6% | 19.9% | 0.19 | 34.3% |
| 4 | META | 2026-10-28 | 2026-12-18 | 51 | 590/575 | 5.30 | 5.45 | 70.8% | 13.32% | 144.7% | 22.5% | 0.19 | 31.9% |
| 5 | NVDA | 2026-10-28 | 2026-12-18 | 51 | 213/200 | 4.65 | 4.80 | 69.9% | 10.67% | 106.6% | 17.4% | 0.15 | 27.9% |
| 6 | META | 2026-10-28 | 2026-12-18 | 51 | 595/575 | 7.05 | 7.32 | 70.2% | 13.03% | 140.2% | 21.7% | 0.18 | 24.8% |
| 7 | TSLA | 2026-10-28 | 2026-12-18 | 51 | 400/370 | 10.50 | 10.78 | 69.9% | 10.36% | 102.4% | 17.6% | 0.15 | 24.0% |
| 8 | META | 2026-10-28 | 2026-12-18 | 51 | 610/550 | 20.80 | 21.35 | 70.2% | 11.97% | 124.6% | 20.8% | 0.19 | 23.7% |
| 9 | TSLA | 2026-10-28 | 2026-12-18 | 51 | 395/380 | 5.35 | 5.63 | 69.9% | 11.36% | 116.0% | 18.1% | 0.15 | 22.6% |
| 10 | META | 2026-10-28 | 2026-12-18 | 51 | 590/550 | 12.00 | 12.12 | 74.3% | 10.31% | 101.8% | 22.6% | 0.17 | 22.0% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-10-28)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-04 (37d) | long call `+1 C 365`, +251.9% | bull call spread `+1 C 345 / -1 C 360`, +100.7% | iron condor `-1 P 335 / +1 P 315 / -1 C 360 / +1 C 380`, +43.1% | iron condor `-1 P 335 / +1 P 315 / -1 C 345 / +1 C 365`, +87.4% | bear put spread `+1 P 340 / -1 P 315`, +169.0% | long strangle `+1 P 315 / +1 C 370`, +215.3% |
| AMD | 2026-12-04 (37d) | bull call spread `+1 C 650 / -1 C 695`, +282.7% | bull put spread `-1 P 635 / +1 P 600`, +110.4% | iron condor `-1 P 560 / +1 P 505 / -1 C 625 / +1 C 680`, +57.7% | iron condor `-1 P 505 / +1 P 465 / -1 C 585 / +1 C 625`, +81.2% | bear put spread `+1 P 520 / -1 P 465`, +168.5% | bear put spread `+1 P 475 / -1 P 435`, +174.4% |
| AMZN | 2026-12-04 (37d) | long call `+1 C 280`, +244.2% | bull put spread `-1 P 280 / +1 P 255`, +115.1% | iron condor `-1 P 250 / +1 P 225 / -1 C 275 / +1 C 300`, +51.0% | iron condor `-1 P 235 / +1 P 210 / -1 C 255 / +1 C 280`, +72.4% | long put `+1 P 250`, +155.1% | long call `+1 C 280`, +193.2% |
| DIA | 2026-12-04 (37d) | long call `+1 C 546`, +356.5% | bull call spread `+1 C 530 / -1 C 540`, +117.8% | iron condor `-1 P 519 / +1 P 504 / -1 C 540 / +1 C 555`, +47.2% | iron condor `-1 P 519 / +1 P 509 / -1 C 525 / +1 C 535`, +121.4% | bear put spread `+1 P 519 / -1 P 495`, +186.6% | long call `+1 C 555`, +400.9% |
| GOOGL | 2026-12-04 (37d) | bull call spread `+1 C 355 / -1 C 380`, +302.1% | bull call spread `+1 C 345 / -1 C 365`, +102.4% | iron condor `-1 P 310 / +1 P 300 / -1 C 365 / +1 C 375`, +68.0% | iron condor `-1 P 300 / +1 P 275 / -1 C 325 / +1 C 350`, +60.1% | bear put spread `+1 P 315 / -1 P 285`, +159.2% | bull call spread `+1 C 355 / -1 C 380`, +121.4% |
| META | 2026-12-04 (37d) | bull call spread `+1 C 675 / -1 C 720`, +331.7% | bull call spread `+1 C 620 / -1 C 675`, +118.1% | iron condor `-1 P 605 / +1 P 565 / -1 C 635 / +1 C 675`, +70.9% | iron condor `-1 P 565 / +1 P 535 / -1 C 620 / +1 C 650`, +87.7% | bear put spread `+1 P 575 / -1 P 535`, +190.2% | bull call spread `+1 C 705 / -1 C 765`, +357.0% |
| MSFT | 2026-12-04 (37d) | long call `+1 C 565`, +332.4% | bull call spread `+1 C 535 / -1 C 575`, +93.5% | iron condor `-1 P 525 / +1 P 480 / -1 C 550 / +1 C 595`, +53.8% | iron condor `-1 P 510 / +1 P 480 / -1 C 535 / +1 C 565`, +72.6% | bear put spread `+1 P 520 / -1 P 480`, +175.8% | long call `+1 C 595`, +306.6% |
| NVDA | 2026-12-04 (37d) | long call `+1 C 240`, +359.6% | bull call spread `+1 C 220 / -1 C 230`, +128.4% | iron condor `-1 P 215 / +1 P 200 / -1 C 225 / +1 C 240`, +83.6% | iron condor `-1 P 200 / +1 P 190 / -1 C 220 / +1 C 230`, +104.1% | bear put spread `+1 P 205 / -1 P 185`, +196.8% | long call `+1 C 250`, +408.3% |
| SPY | 2026-12-04 (37d) | long call `+1 C 803`, +477.1% | bull call spread `+1 C 788 / -1 C 795`, +137.4% | iron condor `-1 P 772 / +1 P 765 / -1 C 788 / +1 C 795`, +85.1% | iron condor `-1 P 757 / +1 P 749 / -1 C 780 / +1 C 788`, +158.4% | bear put spread `+1 P 765 / -1 P 757`, +208.2% | long strangle `+1 P 675 / +1 C 803`, +304.5% |
| TSLA | 2026-12-04 (37d) | bull call spread `+1 C 445 / -1 C 475`, +338.4% | bull call spread `+1 C 410 / -1 C 430`, +120.5% | iron condor `-1 P 395 / +1 P 380 / -1 C 430 / +1 C 445`, +76.9% | iron condor `-1 P 380 / +1 P 365 / -1 C 405 / +1 C 420`, +120.4% | bear put spread `+1 P 380 / -1 P 355`, +197.6% | bull call spread `+1 C 465 / -1 C 505`, +367.0% |
| XLF | 2026-12-04 (37d) | long call `+1 C 57.5`, +183.2% | iron condor `-1 P 56 / +1 P 54 / -1 C 58.5 / +1 C 60.5`, +29.9% | iron condor `-1 P 56 / +1 P 54 / -1 C 58.5 / +1 C 60.5`, +22.8% | bear call spread `-1 C 57.5 / +1 C 58.5`, +17.6% | bear put spread `+1 P 56 / -1 P 54`, +105.5% | long call `+1 C 58.5`, +232.2% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-10-28)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | XLF | 2026-10-28 | 2026-12-04 | 37 | 55.5/54 | 1.12 | 0.06 | 90.0% | 86.6% | 211.12% | 7288773.6% |
| 2 | AMD | 2026-10-28 | 2026-11-11 | 14 | 575/565 | 5.95 | 2.95 | 58.0% | 50.9% | 44.21% | 1396283.7% |
| 3 | AMD | 2026-10-28 | 2026-11-11 | 14 | 560/545 | 6.32 | 1.65 | 70.8% | 64.7% | 24.06% | 27532.6% |
| 4 | AMZN | 2026-10-28 | 2026-11-11 | 14 | 235/230 | 1.66 | 0.50 | 80.0% | 73.4% | 19.89% | 11234.0% |
| 5 | AMD | 2026-10-28 | 2026-11-11 | 14 | 575/545 | 13.00 | 8.95 | 70.8% | 64.7% | 18.36% | 8009.9% |
| 6 | META | 2026-10-28 | 2026-11-11 | 14 | 610/600 | 4.95 | 1.85 | 59.2% | 51.4% | 18.05% | 7469.7% |
| 7 | GOOGL | 2026-10-28 | 2026-11-11 | 14 | 320/310 | 4.29 | 1.84 | 61.1% | 56.7% | 16.02% | 4713.5% |
| 8 | META | 2026-10-28 | 2026-11-11 | 14 | 605/590 | 6.35 | 3.25 | 68.4% | 59.9% | 15.19% | 3892.1% |
| 9 | AMD | 2026-10-28 | 2026-11-11 | 14 | 575/555 | 8.72 | 4.80 | 63.1% | 56.8% | 14.45% | 3276.0% |
| 10 | META | 2026-10-28 | 2026-11-11 | 14 | 610/590 | 8.70 | 5.45 | 60.8% | 54.0% | 14.42% | 3252.4% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-10-28)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-18 | 635/580 | 0.62 | 0.60 | 0.10 | +0.53 | 84.5% | 99.8% | 98.4% | 98.9% | +0.9 pp | 0.25 |
| 2 | SPY | 2026-12-04 | 655/620 | 0.35 | 0.33 | 0.05 | +0.30 | 84.5% | 99.8% | 98.6% | 99.0% | +0.8 pp | 0.23 |
| 3 | SPY | 2026-12-18 | 620/580 | 0.40 | 0.38 | 0.06 | +0.34 | 84.2% | 99.8% | 98.7% | 99.0% | +0.8 pp | 0.23 |
| 4 | AAPL | 2026-12-04 | 285/260 | 0.42 | 0.25 | 0.07 | +0.35 | 84.1% | 99.5% | 97.7% | 98.3% | +1.2 pp | 0.30 |
| 5 | SPY | 2026-11-27 | 675/635 | 0.39 | 0.38 | 0.06 | +0.33 | 83.8% | 99.8% | 98.4% | 99.0% | +0.8 pp | 0.22 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,935, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,334 eligible spreads of the latest session the median annualised return is 1.1% under the risk-neutral CDF and 84.0% after calibration, against a cash rate of 3.6%.

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
