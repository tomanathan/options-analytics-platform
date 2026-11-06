# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-05 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-05 | 1,215 | 3,845 | 3,759 | 47,598 |
| AMD | 2020-01-06 | 2026-11-05 | 1,212 | 3,839 | 3,751 | 47,609 |
| AMZN | 2020-01-06 | 2026-11-05 | 1,211 | 3,834 | 3,749 | 47,303 |
| DIA | 2020-01-06 | 2026-11-05 | 1,213 | 3,853 | 3,745 | 46,989 |
| GOOGL | 2020-01-06 | 2026-11-05 | 1,206 | 3,820 | 3,734 | 47,153 |
| META | 2022-07-01 | 2026-11-05 | 846 | 2,738 | 2,650 | 33,389 |
| MSFT | 2020-01-06 | 2026-11-05 | 1,201 | 3,800 | 3,714 | 46,885 |
| NVDA | 2020-01-06 | 2026-11-05 | 1,210 | 3,822 | 3,739 | 46,750 |
| SPY | 2020-01-06 | 2026-11-05 | 1,203 | 3,849 | 3,754 | 46,603 |
| TSLA | 2021-01-04 | 2026-11-05 | 1,061 | 3,377 | 3,291 | 41,612 |
| XLF | 2020-01-06 | 2026-11-05 | 1,203 | 3,822 | 3,733 | 47,237 |

In total: 1,860,389 quotes on 532,542 contracts, in 40,599 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,384 | 97.0% | enters the calibration sample |
| `unsettled` | 980 | 2.4% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1265 | 0.1290 | +0.0026 |
| Log loss (nats) | 0.3914 | 0.3959 | +0.0045 |
| Expected calibration error | 0.0339 | 0.0175 | -0.0164 |

Brier change +0.0026 (95% cluster-bootstrap interval -0.0009 to +0.0061, resampling expiration dates; negative means calibration helped) over 451,595 predictions, 35,470 snapshots and 887 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 143,117 | 0.1019 | 0.1045 | 0.0189 | 0.0222 |
| 21-35d | 143,601 | 0.1273 | 0.1305 | 0.0311 | 0.0223 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,612 | 0.1191 | 0.1199 | 0.0425 | 0.0162 |
| AMD | 42,183 | 0.1812 | 0.1856 | 0.0397 | 0.0412 |
| AMZN | 41,941 | 0.1350 | 0.1400 | 0.0277 | 0.0281 |
| DIA | 41,594 | 0.0626 | 0.0630 | 0.0265 | 0.0156 |
| GOOGL | 41,873 | 0.1325 | 0.1323 | 0.0507 | 0.0152 |
| META | 33,389 | 0.1535 | 0.1559 | 0.0430 | 0.0181 |
| MSFT | 41,777 | 0.1187 | 0.1223 | 0.0215 | 0.0270 |
| NVDA | 41,346 | 0.1573 | 0.1567 | 0.0767 | 0.0163 |
| SPY | 41,318 | 0.0687 | 0.0696 | 0.0273 | 0.0103 |
| TSLA | 41,612 | 0.1820 | 0.1916 | 0.0092 | 0.0640 |
| XLF | 41,950 | 0.0857 | 0.0871 | 0.0223 | 0.0210 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 100,002 | 0.1261 | 0.1260 | 0.0271 | 0.0198 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,076 | 0.0363 | 0.0186 | 168,095 | 0.0317 | 0.0391 |
| 0.1-0.2 | 56,092 | 0.1468 | 0.1121 | 62,453 | 0.1481 | 0.1917 |
| 0.2-0.3 | 40,449 | 0.2471 | 0.2072 | 39,404 | 0.2567 | 0.2821 |
| 0.3-0.4 | 33,019 | 0.3502 | 0.2982 | 30,537 | 0.3605 | 0.4039 |
| 0.4-0.5 | 35,566 | 0.4517 | 0.4046 | 24,971 | 0.4464 | 0.4699 |
| 0.5-0.6 | 27,600 | 0.5529 | 0.4999 | 28,517 | 0.5471 | 0.5675 |
| 0.6-0.7 | 33,215 | 0.6504 | 0.5964 | 32,400 | 0.6544 | 0.6596 |
| 0.7-0.8 | 30,869 | 0.7481 | 0.6914 | 21,070 | 0.7503 | 0.7529 |
| 0.8-0.9 | 24,979 | 0.8481 | 0.8180 | 16,613 | 0.8508 | 0.8638 |
| 0.9-1.0 | 32,730 | 0.9619 | 0.9563 | 27,535 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-05)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-05 | 2026-12-31 | 56 | 726/689 | 8.33 | 8.56 | 79.9% | 6.73% | 52.9% | 20.6% | 0.13 | 7.6% |
| 2 | SPY | 2026-11-05 | 2026-12-31 | 56 | 704/674 | 4.82 | 5.01 | 85.6% | 5.17% | 38.9% | 23.1% | 0.12 | 4.1% |
| 3 | SPY | 2026-11-05 | 2026-12-31 | 56 | 718/704 | 3.14 | 3.39 | 79.9% | 6.99% | 55.4% | 20.1% | 0.13 | 2.0% |
| 4 | SPY | 2026-11-05 | 2026-12-31 | 56 | 704/689 | 2.62 | 2.82 | 84.2% | 5.95% | 45.7% | 23.3% | 0.13 | 1.5% |
| 5 | SPY | 2026-11-05 | 2026-12-31 | 56 | 704/660 | 6.44 | 6.62 | 86.1% | 4.91% | 36.7% | 24.7% | 0.13 | 1.3% |
| 6 | SPY | 2026-11-05 | 2026-12-31 | 56 | 726/711 | 3.90 | 4.15 | 75.8% | 8.04% | 65.5% | 19.6% | 0.13 | 0.6% |
| 7 | SPY | 2026-11-05 | 2026-12-31 | 56 | 726/704 | 5.50 | 5.74 | 76.2% | 7.32% | 58.5% | 19.2% | 0.13 | 0.4% |
| 8 | SPY | 2026-11-05 | 2026-12-31 | 56 | 711/689 | 4.20 | 4.41 | 81.8% | 5.92% | 45.5% | 21.5% | 0.12 | -0.1% |
| 9 | SPY | 2026-11-05 | 2026-12-31 | 56 | 726/674 | 10.53 | 10.75 | 79.9% | 6.02% | 46.3% | 21.0% | 0.13 | -1.2% |
| 10 | SPY | 2026-11-05 | 2026-12-31 | 56 | 711/674 | 6.40 | 6.60 | 82.9% | 5.29% | 40.0% | 21.9% | 0.12 | -1.3% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-05)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-04 (29d) | long call `+1 C 370`, +342.3% | bull call spread `+1 C 350 / -1 C 370`, +96.1% | iron condor `-1 P 340 / +1 P 325 / -1 C 355 / +1 C 370`, +46.8% | iron condor `-1 P 330 / +1 P 310 / -1 C 345 / +1 C 365`, +76.3% | bear put spread `+1 P 340 / -1 P 310`, +177.1% | long strangle `+1 P 300 / +1 C 370`, +248.3% |
| AMD | 2026-12-04 (29d) | long call `+1 C 465`, +375.1% | bull call spread `+1 C 420 / -1 C 455`, +110.6% | iron condor `-1 P 395 / +1 P 355 / -1 C 465 / +1 C 505`, +40.6% | iron condor `-1 P 355 / +1 P 325 / -1 C 405 / +1 C 435`, +81.8% | long put `+1 P 390`, +159.7% | long call `+1 C 505`, +415.6% |
| AMZN | 2026-12-04 (29d) | long call `+1 C 280`, +304.4% | bull call spread `+1 C 265 / -1 C 280`, +99.6% | iron condor `-1 P 260 / +1 P 240 / -1 C 280 / +1 C 300`, +57.2% | iron condor `-1 P 240 / +1 P 230 / -1 C 265 / +1 C 275`, +70.2% | bear put spread `+1 P 260 / -1 P 235`, +176.2% | long call `+1 C 285`, +259.4% |
| DIA | 2026-12-04 (29d) | long call `+1 C 535`, +359.6% | bull call spread `+1 C 519 / -1 C 535`, +103.7% | iron condor `-1 P 514 / +1 P 499 / -1 C 530 / +1 C 545`, +51.6% | bear call spread `-1 C 514 / +1 C 530`, +57.3% | bear put spread `+1 P 509 / -1 P 465`, +176.6% | long call `+1 C 545`, +414.4% |
| GOOGL | 2026-12-04 (29d) | bull call spread `+1 C 300 / -1 C 325`, +326.7% | bull call spread `+1 C 285 / -1 C 300`, +99.3% | iron condor `-1 P 280 / +1 P 260 / -1 C 300 / +1 C 320`, +47.3% | iron condor `-1 P 260 / +1 P 245 / -1 C 285 / +1 C 300`, +65.6% | bear put spread `+1 P 270 / -1 P 245`, +150.1% | long strangle `+1 P 260 / +1 C 310`, +195.7% |
| META | 2026-12-04 (29d) | bull call spread `+1 C 665 / -1 C 725`, +343.0% | bull call spread `+1 C 615 / -1 C 665`, +116.3% | iron condor `-1 P 605 / +1 P 555 / -1 C 630 / +1 C 680`, +72.3% | iron condor `-1 P 555 / +1 P 530 / -1 C 615 / +1 C 640`, +100.2% | bear put spread `+1 P 580 / -1 P 530`, +189.1% | bull call spread `+1 C 695 / -1 C 755`, +392.9% |
| MSFT | 2026-12-04 (29d) | long call `+1 C 580`, +344.2% | bull call spread `+1 C 545 / -1 C 580`, +104.4% | iron condor `-1 P 535 / +1 P 495 / -1 C 550 / +1 C 590`, +48.5% | iron condor `-1 P 525 / +1 P 495 / -1 C 540 / +1 C 570`, +74.1% | bear put spread `+1 P 530 / -1 P 480`, +165.3% | long strangle `+1 P 480 / +1 C 580`, +231.7% |
| NVDA | 2026-12-04 (29d) | long call `+1 C 210`, +353.4% | bull call spread `+1 C 185 / -1 C 200`, +121.9% | iron condor `-1 P 180 / +1 P 165 / -1 C 200 / +1 C 215`, +81.7% | iron condor `-1 P 160 / +1 P 150 / -1 C 185 / +1 C 195`, +108.8% | bear put spread `+1 P 170 / -1 P 155`, +193.8% | long strangle `+1 P 155 / +1 C 205`, +234.4% |
| SPY | 2026-12-04 (29d) | long call `+1 C 777`, +584.9% | bull call spread `+1 C 755 / -1 C 762`, +134.5% | iron condor `-1 P 725 / +1 P 710 / -1 C 762 / +1 C 777`, +66.8% | iron condor `-1 P 725 / +1 P 705 / -1 C 735 / +1 C 755`, +171.9% | bear put spread `+1 P 725 / -1 P 690`, +205.4% | long call `+1 C 777`, +685.2% |
| TSLA | 2026-12-04 (29d) | bull call spread `+1 C 385 / -1 C 410`, +349.2% | bull call spread `+1 C 355 / -1 C 380`, +126.8% | iron condor `-1 P 340 / +1 P 315 / -1 C 370 / +1 C 395`, +85.1% | iron condor `-1 P 310 / +1 P 290 / -1 C 345 / +1 C 365`, +133.4% | bear put spread `+1 P 330 / -1 P 300`, +192.0% | long strangle `+1 P 300 / +1 C 395`, +225.7% |
| XLF | 2026-12-04 (29d) | long call `+1 C 60`, +222.3% | bull call spread `+1 C 58 / -1 C 61`, +74.0% | bull put spread `-1 P 58 / +1 P 54`, +15.7% | bear call spread `-1 C 57.5 / +1 C 60`, +40.0% | bear put spread `+1 P 58 / -1 P 54`, +119.8% | long strangle `+1 P 55 / +1 C 61`, +139.6% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-05)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | TSLA | 2026-11-05 | 2026-11-18 | 13 | 340/337.5 | 1.60 | 0.60 | 70.6% | 64.0% | 96.18% | 16474836239.4% |
| 2 | AMD | 2026-11-05 | 2026-11-18 | 13 | 380/370 | 4.22 | 0.80 | 74.7% | 67.9% | 31.41% | 214258.7% |
| 3 | TSLA | 2026-11-05 | 2026-11-18 | 13 | 340/332.5 | 3.43 | 2.40 | 70.6% | 64.0% | 30.05% | 159652.4% |
| 4 | TSLA | 2026-11-05 | 2026-11-18 | 13 | 340/330 | 4.28 | 3.25 | 70.6% | 64.0% | 24.70% | 49074.4% |
| 5 | AMD | 2026-11-05 | 2026-11-18 | 13 | 345/335 | 3.05 | 0.10 | 81.3% | 77.3% | 20.04% | 16763.4% |
| 6 | AMZN | 2026-11-05 | 2026-11-18 | 13 | 260/252.5 | 3.20 | 0.70 | 70.0% | 62.3% | 18.06% | 10475.9% |
| 7 | TSLA | 2026-11-05 | 2026-11-18 | 13 | 342.5/337.5 | 2.00 | 1.45 | 70.6% | 64.0% | 17.76% | 9744.9% |
| 8 | TSLA | 2026-11-05 | 2026-11-18 | 13 | 340/322.5 | 6.46 | 5.30 | 70.6% | 64.8% | 16.58% | 7320.2% |
| 9 | AMD | 2026-11-05 | 2026-11-18 | 13 | 400/387.5 | 5.77 | 0.45 | 63.8% | 58.2% | 16.49% | 7165.5% |
| 10 | AMZN | 2026-11-05 | 2026-11-18 | 13 | 260/250 | 3.87 | 1.30 | 74.1% | 66.4% | 14.94% | 4885.6% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-05)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-20 | 585/550 | 0.30 | 0.27 | 0.05 | +0.25 | 84.3% | 99.8% | 98.9% | 99.1% | +0.6 pp | 0.20 |
| 2 | SPY | 2026-11-20 | 605/550 | 0.55 | 0.52 | 0.09 | +0.46 | 83.2% | 99.8% | 98.5% | 99.0% | +0.8 pp | 0.22 |
| 3 | SPY | 2026-12-04 | 585/550 | 0.51 | 0.46 | 0.09 | +0.42 | 82.3% | 99.6% | 98.1% | 98.5% | +1.1 pp | 0.25 |
| 4 | SPY | 2026-11-20 | 605/585 | 0.25 | 0.22 | 0.05 | +0.21 | 81.9% | 99.8% | 98.5% | 98.7% | +1.0 pp | 0.22 |
| 5 | SPY | 2026-11-20 | 625/585 | 0.61 | 0.57 | 0.12 | +0.50 | 81.1% | 99.5% | 97.8% | 98.5% | +1.0 pp | 0.25 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 56 breaches in 53,338, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,171 eligible spreads of the latest session the median annualised return is 1.1% under the risk-neutral CDF and 94.7% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.7 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.1%, right tail uncovered 15.2%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
