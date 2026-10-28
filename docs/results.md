# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-27 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-27 | 1,208 | 3,819 | 3,733 | 47,261 |
| AMD | 2020-01-06 | 2026-10-27 | 1,205 | 3,813 | 3,726 | 47,296 |
| AMZN | 2020-01-06 | 2026-10-27 | 1,204 | 3,808 | 3,722 | 46,952 |
| DIA | 2020-01-06 | 2026-10-27 | 1,206 | 3,825 | 3,721 | 46,688 |
| GOOGL | 2020-01-06 | 2026-10-27 | 1,199 | 3,794 | 3,708 | 46,817 |
| META | 2022-07-01 | 2026-10-27 | 839 | 2,712 | 2,626 | 33,094 |
| MSFT | 2020-01-06 | 2026-10-27 | 1,194 | 3,774 | 3,689 | 46,571 |
| NVDA | 2020-01-06 | 2026-10-27 | 1,203 | 3,797 | 3,713 | 46,412 |
| SPY | 2020-01-06 | 2026-10-27 | 1,196 | 3,821 | 3,722 | 46,187 |
| TSLA | 2021-01-04 | 2026-10-27 | 1,054 | 3,351 | 3,265 | 41,280 |
| XLF | 2020-01-06 | 2026-10-27 | 1,196 | 3,794 | 3,707 | 46,904 |

In total: 1,846,599 quotes on 528,497 contracts, in 40,308 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,097 | 97.0% | enters the calibration sample |
| `unsettled` | 976 | 2.4% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1263 | 0.1288 | +0.0025 |
| Log loss (nats) | 0.3909 | 0.3951 | +0.0042 |
| Expected calibration error | 0.0350 | 0.0165 | -0.0186 |

Brier change +0.0025 (95% cluster-bootstrap interval -0.0005 to +0.0056, resampling expiration dates; negative means calibration helped) over 447,929 predictions, 35,183 snapshots and 882 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 142,306 | 0.1017 | 0.1043 | 0.0195 | 0.0216 |
| 21-35d | 142,379 | 0.1269 | 0.1300 | 0.0326 | 0.0211 |
| 36-50d | 84,455 | 0.1477 | 0.1492 | 0.0482 | 0.0141 |
| >50d | 78,789 | 0.1468 | 0.1490 | 0.0541 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,275 | 0.1195 | 0.1205 | 0.0422 | 0.0173 |
| AMD | 41,870 | 0.1806 | 0.1847 | 0.0423 | 0.0396 |
| AMZN | 41,590 | 0.1352 | 0.1402 | 0.0285 | 0.0272 |
| DIA | 41,293 | 0.0628 | 0.0632 | 0.0265 | 0.0155 |
| GOOGL | 41,537 | 0.1302 | 0.1296 | 0.0556 | 0.0124 |
| META | 33,094 | 0.1526 | 0.1545 | 0.0467 | 0.0177 |
| MSFT | 41,463 | 0.1190 | 0.1227 | 0.0211 | 0.0273 |
| NVDA | 41,008 | 0.1571 | 0.1562 | 0.0795 | 0.0173 |
| SPY | 40,902 | 0.0689 | 0.0697 | 0.0280 | 0.0096 |
| TSLA | 41,280 | 0.1822 | 0.1922 | 0.0076 | 0.0663 |
| XLF | 41,617 | 0.0859 | 0.0874 | 0.0219 | 0.0215 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 96,336 | 0.1253 | 0.1246 | 0.0320 | 0.0169 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 135,917 | 0.0363 | 0.0181 | 166,802 | 0.0317 | 0.0386 |
| 0.1-0.2 | 55,681 | 0.1469 | 0.1109 | 61,923 | 0.1480 | 0.1907 |
| 0.2-0.3 | 40,140 | 0.2472 | 0.2062 | 39,093 | 0.2567 | 0.2803 |
| 0.3-0.4 | 32,737 | 0.3501 | 0.2960 | 30,279 | 0.3605 | 0.4023 |
| 0.4-0.5 | 35,312 | 0.4517 | 0.4034 | 24,783 | 0.4464 | 0.4685 |
| 0.5-0.6 | 27,348 | 0.5529 | 0.4983 | 28,248 | 0.5472 | 0.5657 |
| 0.6-0.7 | 32,918 | 0.6504 | 0.5944 | 32,073 | 0.6544 | 0.6572 |
| 0.7-0.8 | 30,598 | 0.7481 | 0.6894 | 20,887 | 0.7503 | 0.7512 |
| 0.8-0.9 | 24,776 | 0.8482 | 0.8168 | 16,508 | 0.8509 | 0.8632 |
| 0.9-1.0 | 32,502 | 0.9619 | 0.9561 | 27,333 | 0.9673 | 0.9675 |

## Top 10 to enter (2026-10-27)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | NVDA | 2026-10-27 | 2026-12-18 | 52 | 216/205 | 4.10 | 4.23 | 68.4% | 11.23% | 111.1% | 17.2% | 0.15 | 28.4% |
| 2 | NVDA | 2026-10-27 | 2026-12-18 | 52 | 216/200 | 5.55 | 5.65 | 69.9% | 10.23% | 98.1% | 17.8% | 0.15 | 23.2% |
| 3 | NVDA | 2026-10-27 | 2026-12-18 | 52 | 214/205 | 3.20 | 3.35 | 69.9% | 11.56% | 115.5% | 18.6% | 0.16 | 22.4% |
| 4 | TSLA | 2026-10-27 | 2026-12-18 | 52 | 400/375 | 8.66 | 8.93 | 69.9% | 10.29% | 98.9% | 17.6% | 0.15 | 20.0% |
| 5 | META | 2026-10-27 | 2026-12-18 | 52 | 620/560 | 21.40 | 21.88 | 68.4% | 10.48% | 101.2% | 17.4% | 0.15 | 19.4% |
| 6 | META | 2026-10-27 | 2026-12-18 | 52 | 610/570 | 13.95 | 14.55 | 69.9% | 10.53% | 101.9% | 17.5% | 0.15 | 18.9% |
| 7 | META | 2026-10-27 | 2026-12-18 | 52 | 615/560 | 18.90 | 19.45 | 69.9% | 10.28% | 98.7% | 17.9% | 0.15 | 18.7% |
| 8 | META | 2026-10-27 | 2026-12-18 | 52 | 615/570 | 16.25 | 16.88 | 68.4% | 10.87% | 106.4% | 17.3% | 0.15 | 18.6% |
| 9 | SPY | 2026-10-27 | 2026-12-18 | 52 | 762/747 | 3.57 | 3.63 | 80.0% | 7.00% | 60.8% | 20.4% | 0.13 | 16.9% |
| 10 | META | 2026-10-27 | 2026-12-18 | 52 | 595/560 | 10.45 | 10.82 | 74.3% | 9.50% | 89.1% | 20.1% | 0.15 | 16.2% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-10-27)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-04 (38d) | long call `+1 C 380`, +331.8% | bull call spread `+1 C 350 / -1 C 370`, +92.6% | iron condor `-1 P 345 / +1 P 325 / -1 C 360 / +1 C 380`, +54.4% | iron condor `-1 P 340 / +1 P 320 / -1 C 350 / +1 C 370`, +68.3% | bear put spread `+1 P 340 / -1 P 310`, +176.8% | long call `+1 C 380`, +388.7% |
| AMD | 2026-12-04 (38d) | bull call spread `+1 C 630 / -1 C 670`, +331.0% | bull call spread `+1 C 570 / -1 C 615`, +130.1% | iron condor `-1 P 555 / +1 P 515 / -1 C 605 / +1 C 645`, +88.3% | iron condor `-1 P 515 / +1 P 475 / -1 C 565 / +1 C 605`, +98.8% | bear put spread `+1 P 515 / -1 P 475`, +202.5% | long strangle `+1 P 490 / +1 C 630`, +194.5% |
| AMZN | 2026-12-04 (38d) | long call `+1 C 280`, +327.6% | bull call spread `+1 C 250 / -1 C 270`, +90.0% | iron condor `-1 P 250 / +1 P 230 / -1 C 270 / +1 C 290`, +60.2% | iron condor `-1 P 230 / +1 P 215 / -1 C 255 / +1 C 270`, +78.6% | bear put spread `+1 P 240 / -1 P 215`, +159.5% | long call `+1 C 295`, +335.9% |
| DIA | 2026-12-04 (38d) | bull call spread `+1 C 544 / -1 C 575`, +368.1% | bull put spread `-1 P 544 / +1 P 529`, +126.3% | iron condor `-1 P 523 / +1 P 513 / -1 C 534 / +1 C 544`, +68.5% | iron condor `-1 P 507.5 / +1 P 502.5 / -1 C 529 / +1 C 534`, +92.0% | bear put spread `+1 P 518 / -1 P 490`, +191.5% | long strangle `+1 P 445 / +1 C 544`, +260.8% |
| GOOGL | 2026-12-04 (38d) | long call `+1 C 340`, +317.9% | bull call spread `+1 C 330 / -1 C 355`, +98.4% | iron condor `-1 P 320 / +1 P 290 / -1 C 330 / +1 C 360`, +46.6% | iron condor `-1 P 295 / +1 P 280 / -1 C 325 / +1 C 340`, +70.4% | bear put spread `+1 P 310 / -1 P 280`, +164.6% | long strangle `+1 P 280 / +1 C 360`, +225.9% |
| META | 2026-12-04 (38d) | bull call spread `+1 C 670 / -1 C 730`, +342.6% | bull call spread `+1 C 625 / -1 C 670`, +122.0% | iron condor `-1 P 615 / +1 P 570 / -1 C 655 / +1 C 700`, +79.3% | iron condor `-1 P 560 / +1 P 545 / -1 C 625 / +1 C 640`, +95.8% | bear put spread `+1 P 595 / -1 P 545`, +185.9% | long strangle `+1 P 545 / +1 C 700`, +260.8% |
| MSFT | 2026-12-04 (38d) | long call `+1 C 565`, +321.5% | bull call spread `+1 C 530 / -1 C 565`, +113.5% | iron condor `-1 P 525 / +1 P 490 / -1 C 565 / +1 C 600`, +55.5% | iron condor `-1 P 510 / +1 P 480 / -1 C 535 / +1 C 565`, +80.2% | bear put spread `+1 P 515 / -1 P 480`, +171.7% | long strangle `+1 P 480 / +1 C 600`, +233.7% |
| NVDA | 2026-12-04 (38d) | bull call spread `+1 C 240 / -1 C 255`, +365.9% | bull call spread `+1 C 225 / -1 C 240`, +126.7% | iron condor `-1 P 215 / +1 P 205 / -1 C 230 / +1 C 240`, +80.3% | iron condor `-1 P 205 / +1 P 195 / -1 C 220 / +1 C 230`, +123.9% | bear put spread `+1 P 210 / -1 P 190`, +199.4% | long strangle `+1 P 190 / +1 C 250`, +252.9% |
| SPY | 2026-12-04 (38d) | bull put spread `-1 P 845 / +1 P 800`, +549.5% | bull put spread `-1 P 800 / +1 P 785`, +145.4% | iron condor `-1 P 762 / +1 P 754 / -1 C 785 / +1 C 793`, +59.7% | iron condor `-1 P 762 / +1 P 747 / -1 C 770 / +1 C 785`, +176.8% | bear put spread `+1 P 762 / -1 P 754`, +212.0% | long strangle `+1 P 655 / +1 C 800`, +300.9% |
| TSLA | 2026-12-04 (38d) | bull call spread `+1 C 450 / -1 C 490`, +353.4% | bull call spread `+1 C 415 / -1 C 440`, +125.8% | iron condor `-1 P 405 / +1 P 375 / -1 C 430 / +1 C 460`, +79.6% | iron condor `-1 P 385 / +1 P 365 / -1 C 410 / +1 C 430`, +111.7% | bear put spread `+1 P 390 / -1 P 355`, +198.1% | long strangle `+1 P 355 / +1 C 460`, +245.1% |
| XLF | 2026-12-04 (38d) | long call `+1 C 57.5`, +255.1% | bull call spread `+1 C 56.5 / -1 C 58`, +64.8% | bull put spread `-1 P 56 / +1 P 50.5`, +9.1% | bear call spread `-1 C 55 / +1 C 57.5`, +48.9% | long put `+1 P 56`, +89.7% | long call `+1 C 57.5`, +259.8% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-10-27)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMD | 2026-10-27 | 2026-11-09 | 13 | 555/550 | 3.12 | 1.65 | 55.2% | 46.9% | 43.44% | 2506091.7% |
| 2 | AMD | 2026-10-27 | 2026-11-09 | 13 | 560/550 | 5.95 | 3.95 | 50.8% | 44.6% | 29.16% | 131827.9% |
| 3 | AMD | 2026-10-27 | 2026-12-04 | 38 | 555/550 | 3.68 | 1.41 | 55.2% | 48.2% | 102.55% | 87849.0% |
| 4 | GOOGL | 2026-10-27 | 2026-11-09 | 13 | 300/295 | 1.73 | 0.10 | 77.6% | 72.1% | 22.65% | 30792.8% |
| 5 | GOOGL | 2026-10-27 | 2026-11-09 | 13 | 320/315 | 2.72 | 1.00 | 55.2% | 46.1% | 19.76% | 15687.7% |
| 6 | AMZN | 2026-10-27 | 2026-11-11 | 15 | 250/245 | 2.15 | 1.40 | 69.9% | 61.9% | 23.10% | 15610.9% |
| 7 | AMD | 2026-10-27 | 2026-11-09 | 13 | 540/525 | 6.07 | 2.94 | 70.2% | 62.6% | 19.58% | 15037.7% |
| 8 | MSFT | 2026-10-27 | 2026-11-09 | 13 | 520/515 | 2.00 | 0.70 | 69.9% | 61.7% | 16.92% | 7950.1% |
| 9 | AMD | 2026-10-27 | 2026-11-09 | 13 | 560/555 | 2.82 | 1.60 | 50.8% | 44.6% | 16.85% | 7824.7% |
| 10 | AMD | 2026-10-27 | 2026-11-09 | 13 | 545/525 | 7.78 | 5.15 | 70.2% | 62.6% | 16.09% | 6501.0% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-10-27)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-04 | 655/615 | 0.43 | 0.42 | 0.07 | +0.37 | 84.4% | 99.8% | 98.5% | 98.9% | +0.9 pp | 0.24 |
| 2 | SPY | 2026-12-18 | 615/575 | 0.42 | 0.40 | 0.06 | +0.35 | 84.4% | 99.8% | 98.7% | 99.0% | +0.8 pp | 0.23 |
| 3 | SPY | 2026-12-18 | 635/575 | 0.72 | 0.70 | 0.11 | +0.60 | 84.2% | 99.7% | 98.2% | 98.8% | +0.9 pp | 0.25 |
| 4 | SPY | 2026-11-27 | 675/635 | 0.46 | 0.44 | 0.07 | +0.38 | 84.0% | 99.7% | 98.2% | 98.9% | +0.8 pp | 0.24 |
| 5 | SPY | 2026-11-27 | 655/615 | 0.32 | 0.31 | 0.05 | +0.27 | 83.9% | 99.8% | 98.9% | 99.2% | +0.6 pp | 0.19 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,909, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,394 eligible spreads of the latest session the median annualised return is 1.4% under the risk-neutral CDF and 80.5% after calibration, against a cash rate of 3.6%.

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
