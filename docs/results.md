# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-09 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-09 | 1,217 | 3,853 | 3,765 | 47,675 |
| AMD | 2020-01-06 | 2026-11-09 | 1,214 | 3,847 | 3,758 | 47,695 |
| AMZN | 2020-01-06 | 2026-11-09 | 1,213 | 3,842 | 3,753 | 47,355 |
| DIA | 2020-01-06 | 2026-11-09 | 1,215 | 3,861 | 3,753 | 47,093 |
| GOOGL | 2020-01-06 | 2026-11-09 | 1,208 | 3,828 | 3,740 | 47,231 |
| META | 2022-07-01 | 2026-11-09 | 848 | 2,746 | 2,656 | 33,461 |
| MSFT | 2020-01-06 | 2026-11-09 | 1,203 | 3,807 | 3,720 | 46,958 |
| NVDA | 2020-01-06 | 2026-11-09 | 1,212 | 3,830 | 3,743 | 46,802 |
| SPY | 2020-01-06 | 2026-11-09 | 1,205 | 3,857 | 3,760 | 46,676 |
| TSLA | 2021-01-04 | 2026-11-09 | 1,063 | 3,385 | 3,297 | 41,681 |
| XLF | 2020-01-06 | 2026-11-09 | 1,205 | 3,830 | 3,739 | 47,315 |

In total: 1,864,598 quotes on 533,682 contracts, in 40,686 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,449 | 97.0% | enters the calibration sample |
| `unsettled` | 1,002 | 2.5% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1265 | 0.1291 | +0.0026 |
| Log loss (nats) | 0.3916 | 0.3961 | +0.0046 |
| Expected calibration error | 0.0336 | 0.0178 | -0.0158 |

Brier change +0.0026 (95% cluster-bootstrap interval -0.0001 to +0.0056, resampling expiration dates; negative means calibration helped) over 452,409 predictions, 35,535 snapshots and 889 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 143,593 | 0.1019 | 0.1046 | 0.0185 | 0.0226 |
| 21-35d | 143,939 | 0.1275 | 0.1307 | 0.0305 | 0.0229 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,689 | 0.1189 | 0.1198 | 0.0425 | 0.0160 |
| AMD | 42,269 | 0.1814 | 0.1859 | 0.0387 | 0.0419 |
| AMZN | 41,993 | 0.1349 | 0.1400 | 0.0278 | 0.0280 |
| DIA | 41,698 | 0.0626 | 0.0630 | 0.0263 | 0.0156 |
| GOOGL | 41,951 | 0.1327 | 0.1327 | 0.0498 | 0.0156 |
| META | 33,461 | 0.1537 | 0.1561 | 0.0421 | 0.0183 |
| MSFT | 41,850 | 0.1186 | 0.1222 | 0.0215 | 0.0270 |
| NVDA | 41,398 | 0.1575 | 0.1570 | 0.0760 | 0.0166 |
| SPY | 41,391 | 0.0687 | 0.0697 | 0.0270 | 0.0105 |
| TSLA | 41,681 | 0.1819 | 0.1915 | 0.0092 | 0.0642 |
| XLF | 42,028 | 0.0857 | 0.0871 | 0.0224 | 0.0209 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 100,816 | 0.1263 | 0.1263 | 0.0257 | 0.0207 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,372 | 0.0363 | 0.0188 | 168,417 | 0.0317 | 0.0392 |
| 0.1-0.2 | 56,179 | 0.1468 | 0.1125 | 62,561 | 0.1481 | 0.1921 |
| 0.2-0.3 | 40,502 | 0.2471 | 0.2075 | 39,459 | 0.2567 | 0.2826 |
| 0.3-0.4 | 33,075 | 0.3502 | 0.2988 | 30,590 | 0.3606 | 0.4043 |
| 0.4-0.5 | 35,615 | 0.4517 | 0.4050 | 25,001 | 0.4464 | 0.4704 |
| 0.5-0.6 | 27,642 | 0.5529 | 0.5005 | 28,565 | 0.5471 | 0.5681 |
| 0.6-0.7 | 33,267 | 0.6504 | 0.5969 | 32,469 | 0.6544 | 0.6602 |
| 0.7-0.8 | 30,931 | 0.7481 | 0.6920 | 21,106 | 0.7503 | 0.7532 |
| 0.8-0.9 | 25,027 | 0.8481 | 0.8184 | 16,645 | 0.8509 | 0.8640 |
| 0.9-1.0 | 32,799 | 0.9619 | 0.9564 | 27,596 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-09)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-09 | 2026-12-31 | 52 | 745/723 | 5.11 | 5.19 | 79.8% | 6.83% | 59.0% | 20.5% | 0.13 | 13.0% |
| 2 | GOOGL | 2026-11-09 | 2027-01-15 | 67 | 285/265 | 6.30 | 6.88 | 74.2% | 10.36% | 71.1% | 18.5% | 0.16 | 11.6% |
| 3 | GOOGL | 2026-11-09 | 2027-01-15 | 67 | 285/260 | 7.50 | 8.00 | 74.7% | 9.33% | 62.6% | 18.4% | 0.15 | 10.9% |
| 4 | SPY | 2026-11-09 | 2026-12-31 | 52 | 745/730 | 3.74 | 3.83 | 77.4% | 7.04% | 61.2% | 19.1% | 0.13 | 8.8% |
| 5 | SPY | 2026-11-09 | 2026-12-31 | 52 | 745/738 | 1.88 | 1.96 | 75.8% | 8.16% | 73.4% | 19.6% | 0.14 | 7.1% |
| 6 | SPY | 2026-11-09 | 2026-12-31 | 52 | 730/708 | 3.57 | 3.63 | 85.5% | 5.01% | 40.9% | 22.8% | 0.12 | 6.1% |
| 7 | SPY | 2026-11-09 | 2026-12-31 | 52 | 730/723 | 1.29 | 1.36 | 84.0% | 6.43% | 54.9% | 24.5% | 0.14 | 6.0% |
| 8 | SPY | 2026-11-09 | 2026-12-31 | 52 | 738/730 | 1.78 | 1.86 | 79.9% | 6.12% | 51.7% | 18.5% | 0.11 | 5.3% |
| 9 | AAPL | 2026-11-09 | 2027-01-15 | 67 | 350/340 | 3.46 | 3.76 | 69.5% | 11.22% | 78.5% | 17.6% | 0.15 | 4.9% |
| 10 | AAPL | 2026-11-09 | 2027-01-15 | 67 | 340/325 | 3.45 | 3.70 | 79.8% | 7.35% | 47.2% | 20.5% | 0.13 | 4.3% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-09)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-18 (39d) | long call `+1 C 380`, +400.1% | bull call spread `+1 C 360 / -1 C 370`, +121.0% | iron condor `-1 P 350 / +1 P 335 / -1 C 365 / +1 C 380`, +77.9% | iron condor `-1 P 340 / +1 P 330 / -1 C 355 / +1 C 365`, +113.5% | bear put spread `+1 P 345 / -1 P 315`, +197.8% | long strangle `+1 P 300 / +1 C 380`, +290.8% |
| AMD | 2026-12-04 (25d) | long call `+1 C 560`, +354.2% | bull put spread `-1 P 560 / +1 P 510`, +97.7% | iron condor `-1 P 500 / +1 P 460 / -1 C 560 / +1 C 600`, +71.2% | iron condor `-1 P 445 / +1 P 405 / -1 C 510 / +1 C 550`, +87.0% | bear put spread `+1 P 470 / -1 P 420`, +190.6% | long strangle `+1 P 445 / +1 C 570`, +232.2% |
| AMZN | 2026-12-18 (39d) | bull call spread `+1 C 290 / -1 C 315`, +360.6% | bull call spread `+1 C 275 / -1 C 285`, +131.3% | iron condor `-1 P 265 / +1 P 250 / -1 C 280 / +1 C 295`, +86.4% | iron condor `-1 P 250 / +1 P 245 / -1 C 270 / +1 C 275`, +122.8% | bear put spread `+1 P 260 / -1 P 245`, +192.3% | long strangle `+1 P 235 / +1 C 300`, +247.7% |
| DIA | 2026-12-04 (25d) | long call `+1 C 539`, +369.7% | bull put spread `-1 P 539 / +1 P 529`, +118.3% | iron condor `-1 P 523 / +1 P 513 / -1 C 534 / +1 C 544`, +65.1% | iron condor `-1 P 507.5 / +1 P 502.5 / -1 C 529 / +1 C 534`, +67.8% | bear put spread `+1 P 518 / -1 P 490`, +187.5% | long call `+1 C 544`, +387.9% |
| GOOGL | 2026-12-18 (39d) | bull call spread `+1 C 315 / -1 C 340`, +369.4% | bull call spread `+1 C 295 / -1 C 310`, +120.1% | iron condor `-1 P 285 / +1 P 270 / -1 C 300 / +1 C 315`, +78.7% | iron condor `-1 P 270 / +1 P 260 / -1 C 290 / +1 C 300`, +126.8% | bear put spread `+1 P 275 / -1 P 260`, +199.2% | long strangle `+1 P 245 / +1 C 325`, +253.1% |
| META | 2026-12-18 (39d) | bull call spread `+1 C 705 / -1 C 755`, +362.4% | bull call spread `+1 C 660 / -1 C 680`, +131.1% | iron condor `-1 P 630 / +1 P 590 / -1 C 680 / +1 C 720`, +85.4% | iron condor `-1 P 590 / +1 P 575 / -1 C 650 / +1 C 665`, +122.2% | bear put spread `+1 P 605 / -1 P 545`, +202.4% | bull call spread `+1 C 740 / -1 C 800`, +410.3% |
| MSFT | 2026-12-04 (25d) | long call `+1 C 590`, +349.5% | bull call spread `+1 C 555 / -1 C 565`, +111.7% | iron condor `-1 P 545 / +1 P 510 / -1 C 555 / +1 C 590`, +61.3% | iron condor `-1 P 525 / +1 P 510 / -1 C 550 / +1 C 565`, +80.7% | bear put spread `+1 P 530 / -1 P 490`, +177.9% | long strangle `+1 P 465 / +1 C 590`, +264.4% |
| NVDA | 2026-12-18 (39d) | bull call spread `+1 C 210 / -1 C 223`, +366.8% | bull call spread `+1 C 186 / -1 C 195`, +136.9% | iron condor `-1 P 177 / +1 P 160 / -1 C 193 / +1 C 210`, +90.1% | iron condor `-1 P 156 / +1 P 152 / -1 C 180 / +1 C 184`, +133.0% | bear put spread `+1 P 168 / -1 P 152`, +207.0% | long call `+1 C 214`, +391.9% |
| SPY | 2026-12-18 (39d) | long call `+1 C 798`, +614.5% | bull call spread `+1 C 768 / -1 C 775`, +138.7% | iron condor `-1 P 745 / +1 P 730 / -1 C 768 / +1 C 783`, +64.2% | iron condor `-1 P 745 / +1 P 730 / -1 C 753 / +1 C 768`, +185.5% | bear call spread `-1 C 708 / +1 C 753`, +216.4% | long call `+1 C 798`, +766.5% |
| TSLA | 2026-12-18 (39d) | bull call spread `+1 C 425 / -1 C 455`, +375.7% | bull call spread `+1 C 390 / -1 C 410`, +135.3% | iron condor `-1 P 370 / +1 P 355 / -1 C 400 / +1 C 415`, +92.3% | iron condor `-1 P 340 / +1 P 330 / -1 C 380 / +1 C 390`, +144.8% | bear put spread `+1 P 355 / -1 P 320`, +208.4% | long strangle `+1 P 330 / +1 C 425`, +252.4% |
| XLF | 2026-12-18 (39d) | long call `+1 C 60`, +281.2% | bull call spread `+1 C 59 / -1 C 61`, +69.8% | bull put spread `-1 P 59 / +1 P 56`, +35.1% | iron condor `-1 P 56 / +1 P 53 / -1 C 58 / +1 C 61`, +40.1% | long put `+1 P 58`, +153.8% | long strangle `+1 P 53 / +1 C 61`, +274.6% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-09)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | XLF | 2026-11-09 | 2026-12-18 | 39 | 57/56 | 0.59 | 0.16 | 79.9% | 74.3% | 98.10% | 59962.3% |
| 2 | AMD | 2026-11-09 | 2026-11-23 | 14 | 495/480 | 6.66 | 1.66 | 69.9% | 62.8% | 24.72% | 31586.4% |
| 3 | AMD | 2026-11-09 | 2026-11-23 | 14 | 500/490 | 5.07 | 0.70 | 60.7% | 55.2% | 24.43% | 29720.5% |
| 4 | AMD | 2026-11-09 | 2026-11-23 | 14 | 495/470 | 9.90 | 4.10 | 74.7% | 68.8% | 18.63% | 8493.1% |
| 5 | MSFT | 2026-11-09 | 2026-11-23 | 14 | 545/540 | 2.50 | 0.65 | 57.5% | 50.6% | 17.78% | 7033.5% |
| 6 | AMD | 2026-11-09 | 2026-11-23 | 14 | 505/490 | 7.20 | 1.30 | 60.7% | 55.2% | 17.53% | 6643.1% |
| 7 | META | 2026-11-09 | 2026-11-23 | 14 | 640/635 | 2.45 | 1.30 | 58.0% | 51.0% | 15.33% | 4023.3% |
| 8 | AMD | 2026-11-09 | 2026-11-23 | 14 | 495/460 | 12.63 | 6.55 | 74.7% | 68.9% | 15.24% | 3939.7% |
| 9 | AAPL | 2026-11-09 | 2026-11-20 | 11 | 350/347.5 | 1.00 | 0.75 | 64.0% | 59.2% | 10.70% | 2818.0% |
| 10 | MSFT | 2026-11-09 | 2026-12-04 | 25 | 545/540 | 2.55 | 1.10 | 60.7% | 52.4% | 24.82% | 2444.1% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-09)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-18 | 600/565 | 0.29 | 0.28 | 0.05 | +0.25 | 84.5% | 99.9% | 98.9% | 99.2% | +0.7 pp | 0.20 |
| 2 | SPY | 2026-12-31 | 602/565 | 0.44 | 0.42 | 0.07 | +0.36 | 83.3% | 99.8% | 98.4% | 98.8% | +0.9 pp | 0.23 |
| 3 | SPY | 2026-12-04 | 660/620 | 0.46 | 0.44 | 0.08 | +0.38 | 83.3% | 99.7% | 98.2% | 98.9% | +0.8 pp | 0.24 |
| 4 | SPY | 2026-12-18 | 620/565 | 0.54 | 0.53 | 0.09 | +0.45 | 83.2% | 99.8% | 98.5% | 99.0% | +0.8 pp | 0.22 |
| 5 | SPY | 2026-12-04 | 660/640 | 0.28 | 0.26 | 0.05 | +0.23 | 82.6% | 99.7% | 98.2% | 98.6% | +1.1 pp | 0.24 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 58 breaches in 53,480, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,311 eligible spreads of the latest session the median annualised return is 1.2% under the risk-neutral CDF and 73.4% after calibration, against a cash rate of 3.6%.

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
