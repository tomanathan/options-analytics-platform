# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-13 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-13 | 1,221 | 3,869 | 3,773 | 47,779 |
| AMD | 2020-01-06 | 2026-11-13 | 1,218 | 3,863 | 3,766 | 47,799 |
| AMZN | 2020-01-06 | 2026-11-13 | 1,217 | 3,858 | 3,762 | 47,472 |
| DIA | 2020-01-06 | 2026-11-13 | 1,219 | 3,877 | 3,763 | 47,223 |
| GOOGL | 2020-01-06 | 2026-11-13 | 1,212 | 3,844 | 3,748 | 47,335 |
| META | 2022-07-01 | 2026-11-13 | 852 | 2,762 | 2,665 | 33,568 |
| MSFT | 2020-01-06 | 2026-11-13 | 1,207 | 3,823 | 3,728 | 47,059 |
| NVDA | 2020-01-06 | 2026-11-13 | 1,216 | 3,846 | 3,752 | 46,919 |
| SPY | 2020-01-06 | 2026-11-13 | 1,209 | 3,873 | 3,769 | 46,787 |
| TSLA | 2021-01-04 | 2026-11-13 | 1,067 | 3,401 | 3,305 | 41,785 |
| XLF | 2020-01-06 | 2026-11-13 | 1,209 | 3,846 | 3,747 | 47,419 |

In total: 1,873,088 quotes on 536,340 contracts, in 40,862 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,543 | 96.8% | enters the calibration sample |
| `unsettled` | 1,084 | 2.7% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1266 | 0.1292 | +0.0026 |
| Log loss (nats) | 0.3918 | 0.3965 | +0.0046 |
| Expected calibration error | 0.0333 | 0.0181 | -0.0153 |

Brier change +0.0026 (95% cluster-bootstrap interval -0.0001 to +0.0056, resampling expiration dates; negative means calibration helped) over 453,612 predictions, 35,629 snapshots and 892 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 144,081 | 0.1020 | 0.1046 | 0.0184 | 0.0227 |
| 21-35d | 144,654 | 0.1277 | 0.1310 | 0.0299 | 0.0234 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,793 | 0.1188 | 0.1196 | 0.0426 | 0.0156 |
| AMD | 42,373 | 0.1813 | 0.1858 | 0.0385 | 0.0419 |
| AMZN | 42,110 | 0.1348 | 0.1398 | 0.0282 | 0.0276 |
| DIA | 41,828 | 0.0624 | 0.0629 | 0.0263 | 0.0157 |
| GOOGL | 42,055 | 0.1330 | 0.1330 | 0.0490 | 0.0161 |
| META | 33,568 | 0.1538 | 0.1563 | 0.0415 | 0.0183 |
| MSFT | 41,951 | 0.1185 | 0.1221 | 0.0213 | 0.0271 |
| NVDA | 41,515 | 0.1586 | 0.1582 | 0.0740 | 0.0176 |
| SPY | 41,502 | 0.0687 | 0.0696 | 0.0268 | 0.0107 |
| TSLA | 41,785 | 0.1817 | 0.1913 | 0.0094 | 0.0638 |
| XLF | 42,132 | 0.0857 | 0.0871 | 0.0225 | 0.0205 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 102,019 | 0.1265 | 0.1267 | 0.0245 | 0.0209 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,798 | 0.0363 | 0.0190 | 168,882 | 0.0317 | 0.0394 |
| 0.1-0.2 | 56,308 | 0.1469 | 0.1127 | 62,727 | 0.1481 | 0.1923 |
| 0.2-0.3 | 40,594 | 0.2471 | 0.2078 | 39,549 | 0.2568 | 0.2829 |
| 0.3-0.4 | 33,154 | 0.3502 | 0.2991 | 30,662 | 0.3606 | 0.4044 |
| 0.4-0.5 | 35,692 | 0.4517 | 0.4051 | 25,062 | 0.4464 | 0.4707 |
| 0.5-0.6 | 27,710 | 0.5529 | 0.5008 | 28,634 | 0.5471 | 0.5684 |
| 0.6-0.7 | 33,343 | 0.6504 | 0.5971 | 32,576 | 0.6544 | 0.6609 |
| 0.7-0.8 | 31,028 | 0.7481 | 0.6927 | 21,154 | 0.7503 | 0.7537 |
| 0.8-0.9 | 25,095 | 0.8481 | 0.8186 | 16,689 | 0.8509 | 0.8640 |
| 0.9-1.0 | 32,890 | 0.9620 | 0.9564 | 27,677 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-13)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMZN | 2026-11-13 | 2027-01-15 | 63 | 265/250 | 5.45 | 5.60 | 68.1% | 10.37% | 77.2% | 16.4% | 0.14 | 16.9% |
| 2 | AMZN | 2026-11-13 | 2027-01-15 | 63 | 265/245 | 6.80 | 6.97 | 69.9% | 9.79% | 71.8% | 17.1% | 0.14 | 13.9% |
| 3 | AMZN | 2026-11-13 | 2027-01-15 | 63 | 260/250 | 3.30 | 3.45 | 70.5% | 10.58% | 79.1% | 18.9% | 0.15 | 8.8% |
| 4 | AMZN | 2026-11-13 | 2027-01-15 | 63 | 260/240 | 5.75 | 5.93 | 74.1% | 8.71% | 62.2% | 19.2% | 0.14 | 8.3% |
| 5 | SPY | 2026-11-13 | 2027-01-15 | 63 | 740/730 | 2.29 | 2.41 | 79.9% | 6.76% | 46.1% | 19.4% | 0.12 | 6.2% |
| 6 | SPY | 2026-11-13 | 2027-01-15 | 63 | 745/725 | 4.73 | 4.87 | 78.6% | 6.96% | 47.7% | 19.7% | 0.13 | 6.0% |
| 7 | AMZN | 2026-11-13 | 2027-01-15 | 63 | 265/240 | 7.90 | 8.07 | 70.5% | 8.91% | 63.9% | 17.4% | 0.14 | 5.9% |
| 8 | SPY | 2026-11-13 | 2027-01-15 | 63 | 745/730 | 3.72 | 3.86 | 77.5% | 7.08% | 48.6% | 18.7% | 0.12 | 5.3% |
| 9 | SPY | 2026-11-13 | 2027-01-15 | 63 | 730/710 | 3.34 | 3.44 | 85.3% | 5.34% | 35.2% | 22.8% | 0.12 | 5.2% |
| 10 | AAPL | 2026-11-13 | 2027-01-15 | 63 | 355/345 | 3.34 | 3.57 | 69.9% | 10.66% | 79.9% | 18.1% | 0.15 | 4.3% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-13)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-24 (41d) | long call `+1 C 380`, +353.9% | bull call spread `+1 C 365 / -1 C 380`, +101.4% | iron condor `-1 P 355 / +1 P 340 / -1 C 370 / +1 C 385`, +58.5% | iron condor `-1 P 340 / +1 P 330 / -1 C 360 / +1 C 370`, +83.3% | bear put spread `+1 P 350 / -1 P 330`, +187.2% | long strangle `+1 P 305 / +1 C 385`, +250.5% |
| AMD | 2026-12-24 (41d) | long call `+1 C 600`, +300.7% | bull put spread `-1 P 585 / +1 P 535`, +107.0% | iron condor `-1 P 500 / +1 P 455 / -1 C 585 / +1 C 630`, +48.8% | iron condor `-1 P 440 / +1 P 400 / -1 C 535 / +1 C 575`, +84.9% | long put `+1 P 490`, +180.4% | long strangle `+1 P 455 / +1 C 600`, +204.3% |
| AMZN | 2026-12-24 (41d) | long call `+1 C 290`, +348.2% | bull call spread `+1 C 265 / -1 C 290`, +104.3% | iron condor `-1 P 260 / +1 P 245 / -1 C 285 / +1 C 300`, +56.7% | iron condor `-1 P 255 / +1 P 235 / -1 C 270 / +1 C 290`, +61.4% | bear put spread `+1 P 255 / -1 P 235`, +184.2% | long strangle `+1 P 245 / +1 C 290`, +205.1% |
| DIA | 2026-12-24 (41d) | long call `+1 C 544`, +349.8% | bull call spread `+1 C 528 / -1 C 544`, +105.5% | iron condor `-1 P 523 / +1 P 513 / -1 C 534 / +1 C 544`, +52.9% | iron condor `-1 P 513 / +1 P 502 / -1 C 528 / +1 C 539`, +73.4% | bear put spread `+1 P 518 / -1 P 490`, +181.4% | long call `+1 C 544`, +335.4% |
| GOOGL | 2026-12-24 (41d) | bull call spread `+1 C 320 / -1 C 340`, +335.2% | bull call spread `+1 C 300 / -1 C 320`, +117.7% | iron condor `-1 P 295 / +1 P 270 / -1 C 310 / +1 C 335`, +70.0% | iron condor `-1 P 270 / +1 P 260 / -1 C 300 / +1 C 310`, +86.5% | bear put spread `+1 P 285 / -1 P 260`, +195.1% | long strangle `+1 P 260 / +1 C 335`, +250.5% |
| META | 2026-12-24 (41d) | long call `+1 C 695`, +329.2% | bull call spread `+1 C 640 / -1 C 695`, +120.3% | iron condor `-1 P 635 / +1 P 580 / -1 C 665 / +1 C 720`, +71.1% | iron condor `-1 P 590 / +1 P 560 / -1 C 650 / +1 C 680`, +88.3% | bear put spread `+1 P 605 / -1 P 545`, +188.2% | long strangle `+1 P 560 / +1 C 720`, +248.2% |
| MSFT | 2026-12-24 (41d) | bull put spread `-1 P 615 / +1 P 565`, +319.1% | bull put spread `-1 P 575 / +1 P 530`, +107.2% | iron condor `-1 P 520 / +1 P 490 / -1 C 545 / +1 C 575`, +50.9% | iron condor `-1 P 490 / +1 P 460 / -1 C 525 / +1 C 555`, +65.7% | bear put spread `+1 P 505 / -1 P 460`, +163.7% | long call `+1 C 575`, +330.0% |
| NVDA | 2026-12-24 (41d) | bull call spread `+1 C 190 / -1 C 205`, +354.1% | bull call spread `+1 C 165 / -1 C 180`, +125.0% | iron condor `-1 P 160 / +1 P 145 / -1 C 175 / +1 C 190`, +85.1% | iron condor `-1 P 145 / +1 P 135 / -1 C 165 / +1 C 175`, +110.3% | bear put spread `+1 P 150 / -1 P 135`, +197.7% | long call `+1 C 195`, +336.5% |
| SPY | 2026-12-24 (41d) | long call `+1 C 785`, +487.2% | bull call spread `+1 C 769 / -1 C 777`, +132.3% | iron condor `-1 P 747 / +1 P 739 / -1 C 777 / +1 C 785`, +72.3% | iron condor `-1 P 732 / +1 P 725 / -1 C 762 / +1 C 769`, +149.6% | bear put spread `+1 P 747 / -1 P 710`, +208.9% | long call `+1 C 785`, +473.0% |
| TSLA | 2026-12-24 (41d) | long call `+1 C 430`, +333.7% | bull call spread `+1 C 400 / -1 C 420`, +120.6% | iron condor `-1 P 390 / +1 P 360 / -1 C 420 / +1 C 450`, +74.6% | iron condor `-1 P 360 / +1 P 340 / -1 C 395 / +1 C 415`, +101.3% | bear put spread `+1 P 365 / -1 P 330`, +192.3% | long call `+1 C 460`, +363.8% |
| XLF | 2026-12-24 (41d) | long call `+1 C 60`, +186.7% | bull call spread `+1 C 57.5 / -1 C 61`, +63.8% | iron condor `-1 P 57.5 / +1 P 54 / -1 C 61 / +1 C 64.5`, +12.6% | bear put spread `+1 P 59.5 / -1 P 57.5`, +72.7% | long put `+1 P 58`, +105.4% | long strangle `+1 P 50 / +1 C 60`, +152.7% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-13)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMD | 2026-11-13 | 2026-11-27 | 14 | 530/525 | 2.50 | 0.60 | 62.8% | 57.7% | 26.68% | 47487.0% |
| 2 | GOOGL | 2026-11-13 | 2026-11-27 | 14 | 290/287.5 | 1.08 | 0.30 | 63.9% | 59.4% | 18.79% | 8811.9% |
| 3 | AMD | 2026-11-13 | 2026-11-27 | 14 | 530/520 | 4.52 | 3.10 | 63.9% | 58.4% | 17.95% | 7306.9% |
| 4 | AMD | 2026-11-13 | 2026-11-27 | 14 | 530/515 | 6.38 | 5.10 | 63.9% | 59.0% | 15.34% | 4027.0% |
| 5 | AMD | 2026-11-13 | 2026-11-27 | 14 | 530/500 | 12.05 | 10.10 | 69.9% | 62.1% | 14.97% | 3696.3% |
| 6 | AMD | 2026-11-13 | 2026-11-27 | 14 | 515/500 | 5.68 | 3.50 | 69.9% | 62.3% | 14.63% | 3413.1% |
| 7 | NVDA | 2026-11-13 | 2026-11-27 | 14 | 162.5/160 | 1.24 | 1.10 | 56.0% | 50.1% | 14.47% | 3289.6% |
| 8 | AMD | 2026-11-13 | 2026-11-27 | 14 | 520/500 | 7.53 | 5.20 | 69.9% | 62.3% | 13.66% | 2715.6% |
| 9 | AMD | 2026-11-13 | 2026-12-11 | 28 | 515/500 | 7.50 | 4.55 | 61.0% | 56.6% | 28.21% | 2452.8% |
| 10 | AMD | 2026-11-13 | 2026-11-27 | 14 | 525/500 | 9.55 | 6.75 | 69.9% | 62.3% | 13.07% | 2361.5% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-13)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-24 | 605/565 | 0.35 | 0.32 | 0.06 | +0.29 | 82.5% | 99.7% | 98.8% | 99.1% | +0.6 pp | 0.20 |
| 2 | SPY | 2026-12-11 | 640/605 | 0.33 | 0.31 | 0.06 | +0.27 | 82.3% | 99.7% | 98.7% | 99.1% | +0.7 pp | 0.20 |
| 3 | SPY | 2026-12-24 | 620/565 | 0.55 | 0.51 | 0.10 | +0.45 | 81.4% | 99.7% | 98.5% | 99.0% | +0.7 pp | 0.21 |
| 4 | SPY | 2026-12-11 | 660/605 | 0.65 | 0.62 | 0.13 | +0.52 | 80.7% | 99.4% | 97.9% | 98.8% | +0.6 pp | 0.23 |
| 5 | SPY | 2026-12-11 | 660/620 | 0.53 | 0.50 | 0.10 | +0.43 | 80.3% | 99.4% | 97.9% | 98.7% | +0.8 pp | 0.23 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 68 breaches in 53,663, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,424 eligible spreads of the latest session the median annualised return is 1.0% under the risk-neutral CDF and 71.4% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.7 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.1%, right tail uncovered 15.1%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
