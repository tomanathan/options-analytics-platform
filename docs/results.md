# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-10-26 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-10-26 | 1,207 | 3,815 | 3,733 | 47,261 |
| AMD | 2020-01-06 | 2026-10-26 | 1,204 | 3,809 | 3,726 | 47,296 |
| AMZN | 2020-01-06 | 2026-10-26 | 1,203 | 3,804 | 3,722 | 46,952 |
| DIA | 2020-01-06 | 2026-10-26 | 1,205 | 3,821 | 3,721 | 46,688 |
| GOOGL | 2020-01-06 | 2026-10-26 | 1,198 | 3,790 | 3,708 | 46,817 |
| META | 2022-07-01 | 2026-10-26 | 838 | 2,708 | 2,626 | 33,094 |
| MSFT | 2020-01-06 | 2026-10-26 | 1,193 | 3,770 | 3,689 | 46,571 |
| NVDA | 2020-01-06 | 2026-10-26 | 1,202 | 3,793 | 3,713 | 46,412 |
| SPY | 2020-01-06 | 2026-10-26 | 1,195 | 3,817 | 3,721 | 46,174 |
| TSLA | 2021-01-04 | 2026-10-26 | 1,053 | 3,347 | 3,265 | 41,280 |
| XLF | 2020-01-06 | 2026-10-26 | 1,195 | 3,790 | 3,707 | 46,904 |

In total: 1,844,539 quotes on 528,103 contracts, in 40,264 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,096 | 97.1% | enters the calibration sample |
| `unsettled` | 933 | 2.3% | the expiration is after the last priced session, so there is no outcome yet |
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

Brier change +0.0025 (95% cluster-bootstrap interval -0.0006 to +0.0054, resampling expiration dates; negative means calibration helped) over 447,916 predictions, 35,182 snapshots and 881 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 142,293 | 0.1017 | 0.1043 | 0.0195 | 0.0216 |
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
| SPY | 40,889 | 0.0690 | 0.0697 | 0.0280 | 0.0096 |
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
| 2026 | 96,323 | 0.1253 | 0.1246 | 0.0320 | 0.0169 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 135,909 | 0.0363 | 0.0181 | 166,794 | 0.0317 | 0.0386 |
| 0.1-0.2 | 55,681 | 0.1469 | 0.1109 | 61,923 | 0.1480 | 0.1907 |
| 0.2-0.3 | 40,139 | 0.2472 | 0.2062 | 39,092 | 0.2567 | 0.2803 |
| 0.3-0.4 | 32,737 | 0.3501 | 0.2960 | 30,279 | 0.3605 | 0.4023 |
| 0.4-0.5 | 35,312 | 0.4517 | 0.4034 | 24,783 | 0.4464 | 0.4685 |
| 0.5-0.6 | 27,348 | 0.5529 | 0.4983 | 28,248 | 0.5472 | 0.5657 |
| 0.6-0.7 | 32,918 | 0.6504 | 0.5944 | 32,073 | 0.6544 | 0.6572 |
| 0.7-0.8 | 30,598 | 0.7481 | 0.6894 | 20,886 | 0.7503 | 0.7512 |
| 0.8-0.9 | 24,775 | 0.8482 | 0.8168 | 16,508 | 0.8509 | 0.8632 |
| 0.9-1.0 | 32,499 | 0.9619 | 0.9561 | 27,330 | 0.9673 | 0.9675 |

## Top 10 to enter (2026-10-26)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-10-26 | 2026-12-18 | 53 | 765/758 | 2.27 | 2.32 | 73.5% | 10.60% | 100.1% | 20.3% | 0.16 | 29.6% |
| 2 | NVDA | 2026-10-26 | 2026-12-18 | 53 | 214/200 | 5.00 | 5.13 | 69.9% | 11.07% | 106.0% | 18.3% | 0.16 | 28.1% |
| 3 | NVDA | 2026-10-26 | 2026-12-18 | 53 | 214/205 | 3.40 | 3.55 | 68.4% | 11.79% | 115.4% | 17.3% | 0.15 | 27.9% |
| 4 | TSLA | 2026-10-26 | 2026-12-18 | 53 | 390/360 | 11.15 | 11.43 | 68.0% | 11.06% | 105.9% | 17.1% | 0.15 | 26.0% |
| 5 | TSLA | 2026-10-26 | 2026-12-18 | 53 | 385/360 | 8.84 | 9.10 | 69.9% | 10.63% | 100.5% | 17.7% | 0.15 | 24.8% |
| 6 | SPY | 2026-10-26 | 2026-12-18 | 53 | 765/750 | 4.43 | 4.48 | 74.9% | 9.11% | 82.2% | 20.2% | 0.15 | 21.9% |
| 7 | NVDA | 2026-10-26 | 2026-12-18 | 53 | 212/205 | 2.50 | 2.65 | 69.9% | 11.84% | 116.1% | 18.6% | 0.16 | 20.0% |
| 8 | NVDA | 2026-10-26 | 2026-12-18 | 53 | 212/200 | 4.10 | 4.22 | 70.2% | 10.99% | 105.1% | 19.3% | 0.16 | 18.7% |
| 9 | SPY | 2026-10-26 | 2026-12-18 | 53 | 758/742 | 3.85 | 3.90 | 80.0% | 7.05% | 59.8% | 20.3% | 0.13 | 18.3% |
| 10 | TSLA | 2026-10-26 | 2026-12-18 | 53 | 380/360 | 6.70 | 6.93 | 70.8% | 10.77% | 102.3% | 19.4% | 0.16 | 17.6% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-10-26)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-04 (39d) | long call `+1 C 370`, +322.1% | bull call spread `+1 C 350 / -1 C 370`, +114.3% | iron condor `-1 P 340 / +1 P 310 / -1 C 355 / +1 C 385`, +43.1% | iron condor `-1 P 330 / +1 P 310 / -1 C 345 / +1 C 365`, +67.0% | bear put spread `+1 P 330 / -1 P 300`, +183.5% | long call `+1 C 370`, +281.2% |
| AMD | 2026-12-04 (39d) | long call `+1 C 665`, +455.7% | bull call spread `+1 C 545 / -1 C 585`, +125.4% | iron condor `-1 P 500 / +1 P 450 / -1 C 575 / +1 C 625`, +62.0% | bear call spread `-1 C 510 / +1 C 545`, +74.9% | long put `+1 P 515`, +146.2% | long strangle `+1 P 480 / +1 C 610`, +213.9% |
| AMZN | 2026-12-04 (39d) | bull call spread `+1 C 275 / -1 C 295`, +298.3% | bull put spread `-1 P 270 / +1 P 250`, +101.8% | iron condor `-1 P 245 / +1 P 225 / -1 C 265 / +1 C 285`, +42.7% | iron condor `-1 P 230 / +1 P 210 / -1 C 250 / +1 C 270`, +76.1% | bear put spread `+1 P 230 / -1 P 210`, +161.7% | bull call spread `+1 C 285 / -1 C 295`, +232.0% |
| DIA | 2026-12-04 (39d) | bull call spread `+1 C 544 / -1 C 575`, +365.9% | bull put spread `-1 P 544 / +1 P 528`, +124.8% | iron condor `-1 P 517.5 / +1 P 512.5 / -1 C 539 / +1 C 544`, +47.2% | iron condor `-1 P 517.5 / +1 P 507.5 / -1 C 523 / +1 C 533`, +124.2% | bear put spread `+1 P 517.5 / -1 P 490`, +192.1% | long strangle `+1 P 445 / +1 C 544`, +249.4% |
| GOOGL | 2026-12-04 (39d) | bull call spread `+1 C 340 / -1 C 370`, +320.3% | bull call spread `+1 C 315 / -1 C 340`, +118.6% | iron condor `-1 P 310 / +1 P 290 / -1 C 330 / +1 C 350`, +62.6% | iron condor `-1 P 310 / +1 P 290 / -1 C 320 / +1 C 340`, +76.4% | bear put spread `+1 P 310 / -1 P 290`, +168.1% | long strangle `+1 P 285 / +1 C 350`, +204.9% |
| META | 2026-12-04 (39d) | long call `+1 C 680`, +272.4% | bull put spread `-1 P 670 / +1 P 610`, +96.1% | iron condor `-1 P 625 / +1 P 570 / -1 C 670 / +1 C 725`, +44.3% | bear put spread `+1 P 645 / -1 P 610`, +54.1% | bear put spread `+1 P 610 / -1 P 550`, +179.2% | long strangle `+1 P 550 / +1 C 725`, +191.4% |
| MSFT | 2026-12-04 (39d) | bull call spread `+1 C 575 / -1 C 610`, +343.0% | bull call spread `+1 C 540 / -1 C 575`, +115.2% | iron condor `-1 P 525 / +1 P 490 / -1 C 550 / +1 C 585`, +63.7% | iron condor `-1 P 490 / +1 P 465 / -1 C 540 / +1 C 565`, +78.3% | bear put spread `+1 P 510 / -1 P 465`, +186.3% | long strangle `+1 P 465 / +1 C 585`, +242.2% |
| NVDA | 2026-12-04 (39d) | long call `+1 C 240`, +324.7% | bull call spread `+1 C 220 / -1 C 235`, +111.3% | iron condor `-1 P 215 / +1 P 200 / -1 C 230 / +1 C 245`, +76.3% | iron condor `-1 P 200 / +1 P 190 / -1 C 220 / +1 C 230`, +87.3% | bear put spread `+1 P 210 / -1 P 190`, +180.6% | long strangle `+1 P 190 / +1 C 245`, +207.5% |
| SPY | 2026-12-04 (39d) | bull put spread `-1 P 860 / +1 P 788`, +467.7% | bull call spread `+1 C 781 / -1 C 788`, +145.3% | iron condor `-1 P 765 / +1 P 758 / -1 C 781 / +1 C 788`, +87.8% | iron condor `-1 P 750 / +1 P 742 / -1 C 773 / +1 C 781`, +177.6% | bear put spread `+1 P 758 / -1 P 750`, +213.8% | long strangle `+1 P 670 / +1 C 796`, +261.7% |
| TSLA | 2026-12-04 (39d) | bull call spread `+1 C 430 / -1 C 460`, +353.2% | bull call spread `+1 C 400 / -1 C 415`, +128.6% | iron condor `-1 P 385 / +1 P 360 / -1 C 415 / +1 C 440`, +81.0% | iron condor `-1 P 370 / +1 P 350 / -1 C 395 / +1 C 415`, +101.4% | bear put spread `+1 P 375 / -1 P 350`, +194.5% | long strangle `+1 P 335 / +1 C 440`, +247.2% |
| XLF | 2026-12-04 (39d) | long call `+1 C 58.5`, +355.0% | long call `+1 C 57`, +92.5% | bull call spread `+1 C 55 / -1 C 57.5`, +16.3% | bear call spread `-1 C 55 / +1 C 58.5`, +23.2% | bear put spread `+1 P 56.5 / -1 P 54`, +83.8% | long call `+1 C 58.5`, +178.3% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-10-26)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMD | 2026-10-26 | 2026-11-09 | 14 | 525/520 | 3.68 | 1.55 | 56.3% | 49.7% | 104.13% | 12015525426.2% |
| 2 | GOOGL | 2026-10-26 | 2026-11-09 | 14 | 310/305 | 2.60 | 1.20 | 63.1% | 57.6% | 35.22% | 260805.2% |
| 3 | AMZN | 2026-10-26 | 2026-11-09 | 14 | 235/230 | 2.22 | 1.05 | 70.2% | 62.3% | 30.88% | 111270.4% |
| 4 | META | 2026-10-26 | 2026-11-09 | 14 | 625/610 | 6.75 | 1.15 | 69.9% | 61.0% | 25.33% | 35932.6% |
| 5 | AMD | 2026-10-26 | 2026-11-09 | 14 | 510/500 | 4.05 | 1.85 | 74.3% | 66.6% | 24.82% | 32305.7% |
| 6 | AMD | 2026-10-26 | 2026-11-09 | 14 | 515/500 | 5.98 | 3.60 | 74.3% | 66.6% | 23.55% | 24680.0% |
| 7 | AMZN | 2026-10-26 | 2026-11-09 | 14 | 240/230 | 4.19 | 2.60 | 70.2% | 62.3% | 23.21% | 23001.4% |
| 8 | GOOGL | 2026-10-26 | 2026-11-09 | 14 | 310/300 | 4.27 | 2.95 | 68.8% | 60.6% | 20.61% | 13149.7% |
| 9 | AMD | 2026-10-26 | 2026-11-09 | 14 | 530/520 | 5.60 | 4.00 | 50.8% | 44.5% | 19.27% | 9782.4% |
| 10 | AMD | 2026-10-26 | 2026-11-09 | 14 | 515/490 | 9.33 | 5.10 | 74.3% | 66.6% | 18.91% | 9049.4% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-10-26)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-04 | 650/610 | 0.51 | 0.49 | 0.08 | +0.43 | 84.4% | 99.7% | 98.3% | 98.7% | +0.9 pp | 0.26 |
| 2 | DIA | 2026-12-18 | 430/390 | 0.34 | 0.19 | 0.05 | +0.29 | 84.3% | 99.8% | 98.8% | 99.1% | +0.6 pp | 0.20 |
| 3 | SPY | 2026-11-20 | 670/630 | 0.41 | 0.40 | 0.06 | +0.35 | 84.2% | 99.8% | 98.4% | 99.0% | +0.8 pp | 0.23 |
| 4 | SPY | 2026-12-18 | 610/575 | 0.42 | 0.40 | 0.07 | +0.35 | 84.0% | 99.8% | 98.5% | 98.8% | +1.0 pp | 0.24 |
| 5 | SPY | 2026-12-04 | 650/630 | 0.29 | 0.27 | 0.05 | +0.24 | 84.0% | 99.7% | 98.3% | 98.6% | +1.1 pp | 0.26 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,902, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,389 eligible spreads of the latest session the median annualised return is 1.1% under the risk-neutral CDF and 84.8% after calibration, against a cash rate of 3.6%.

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
