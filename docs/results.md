# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-02 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-02 | 1,212 | 3,835 | 3,757 | 47,573 |
| AMD | 2020-01-06 | 2026-11-02 | 1,209 | 3,829 | 3,750 | 47,596 |
| AMZN | 2020-01-06 | 2026-11-02 | 1,208 | 3,824 | 3,746 | 47,264 |
| DIA | 2020-01-06 | 2026-11-02 | 1,210 | 3,841 | 3,745 | 46,989 |
| GOOGL | 2020-01-06 | 2026-11-02 | 1,203 | 3,810 | 3,732 | 47,128 |
| META | 2022-07-01 | 2026-11-02 | 843 | 2,728 | 2,649 | 33,376 |
| MSFT | 2020-01-06 | 2026-11-02 | 1,198 | 3,790 | 3,712 | 46,863 |
| NVDA | 2020-01-06 | 2026-11-02 | 1,207 | 3,813 | 3,737 | 46,724 |
| SPY | 2020-01-06 | 2026-11-02 | 1,200 | 3,837 | 3,753 | 46,590 |
| TSLA | 2021-01-04 | 2026-11-02 | 1,058 | 3,367 | 3,289 | 41,588 |
| XLF | 2020-01-06 | 2026-11-02 | 1,200 | 3,810 | 3,730 | 47,198 |

In total: 1,854,895 quotes on 530,952 contracts, in 40,484 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,365 | 97.2% | enters the calibration sample |
| `unsettled` | 884 | 2.2% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1265 | 0.1290 | +0.0025 |
| Log loss (nats) | 0.3914 | 0.3959 | +0.0045 |
| Expected calibration error | 0.0340 | 0.0175 | -0.0165 |

Brier change +0.0025 (95% cluster-bootstrap interval -0.0005 to +0.0057, resampling expiration dates; negative means calibration helped) over 451,356 predictions, 35,451 snapshots and 885 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 142,878 | 0.1019 | 0.1044 | 0.0190 | 0.0221 |
| 21-35d | 143,601 | 0.1273 | 0.1305 | 0.0311 | 0.0223 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,587 | 0.1191 | 0.1200 | 0.0425 | 0.0163 |
| AMD | 42,170 | 0.1812 | 0.1856 | 0.0398 | 0.0412 |
| AMZN | 41,902 | 0.1350 | 0.1401 | 0.0276 | 0.0281 |
| DIA | 41,594 | 0.0626 | 0.0630 | 0.0265 | 0.0156 |
| GOOGL | 41,848 | 0.1323 | 0.1322 | 0.0510 | 0.0150 |
| META | 33,376 | 0.1535 | 0.1558 | 0.0431 | 0.0181 |
| MSFT | 41,755 | 0.1187 | 0.1224 | 0.0214 | 0.0271 |
| NVDA | 41,320 | 0.1573 | 0.1567 | 0.0769 | 0.0163 |
| SPY | 41,305 | 0.0687 | 0.0696 | 0.0274 | 0.0103 |
| TSLA | 41,588 | 0.1821 | 0.1917 | 0.0092 | 0.0641 |
| XLF | 41,911 | 0.0857 | 0.0871 | 0.0222 | 0.0212 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 99,763 | 0.1261 | 0.1260 | 0.0273 | 0.0197 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 136,988 | 0.0363 | 0.0186 | 168,002 | 0.0317 | 0.0391 |
| 0.1-0.2 | 56,073 | 0.1468 | 0.1121 | 62,428 | 0.1481 | 0.1917 |
| 0.2-0.3 | 40,433 | 0.2471 | 0.2071 | 39,380 | 0.2567 | 0.2820 |
| 0.3-0.4 | 33,000 | 0.3502 | 0.2982 | 30,523 | 0.3605 | 0.4039 |
| 0.4-0.5 | 35,550 | 0.4517 | 0.4046 | 24,958 | 0.4464 | 0.4699 |
| 0.5-0.6 | 27,587 | 0.5529 | 0.4998 | 28,503 | 0.5471 | 0.5675 |
| 0.6-0.7 | 33,197 | 0.6504 | 0.5964 | 32,384 | 0.6544 | 0.6595 |
| 0.7-0.8 | 30,854 | 0.7481 | 0.6913 | 21,056 | 0.7503 | 0.7528 |
| 0.8-0.9 | 24,961 | 0.8481 | 0.8179 | 16,602 | 0.8509 | 0.8638 |
| 0.9-1.0 | 32,713 | 0.9619 | 0.9563 | 27,520 | 0.9673 | 0.9677 |

## Top 10 to enter (2026-11-02)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | TSLA | 2026-11-02 | 2026-12-18 | 46 | 400/370 | 10.75 | 11.00 | 69.5% | 10.12% | 114.8% | 16.7% | 0.14 | 31.7% |
| 2 | META | 2026-11-02 | 2026-12-18 | 46 | 605/560 | 16.40 | 16.92 | 68.1% | 10.41% | 119.4% | 16.5% | 0.15 | 22.9% |
| 3 | META | 2026-11-02 | 2026-12-18 | 46 | 600/560 | 14.05 | 14.55 | 69.5% | 9.97% | 112.6% | 16.7% | 0.14 | 22.8% |
| 4 | TSLA | 2026-11-02 | 2026-12-18 | 46 | 400/365 | 12.11 | 12.36 | 69.5% | 9.92% | 111.9% | 17.4% | 0.15 | 22.8% |
| 5 | TSLA | 2026-11-02 | 2026-12-18 | 46 | 395/380 | 5.45 | 5.70 | 68.3% | 11.00% | 128.9% | 17.2% | 0.15 | 20.0% |
| 6 | TSLA | 2026-11-02 | 2026-12-18 | 46 | 395/370 | 8.50 | 8.75 | 70.0% | 9.99% | 112.9% | 17.7% | 0.15 | 19.6% |
| 7 | SPY | 2026-11-02 | 2026-12-31 | 59 | 752/745 | 2.19 | 2.30 | 74.1% | 10.07% | 81.1% | 19.4% | 0.15 | 18.7% |
| 8 | META | 2026-11-02 | 2026-12-18 | 46 | 595/570 | 8.85 | 9.38 | 69.5% | 11.05% | 129.8% | 17.7% | 0.15 | 18.6% |
| 9 | NVDA | 2026-11-02 | 2026-12-18 | 46 | 195/182 | 3.90 | 4.05 | 74.1% | 9.32% | 102.8% | 19.6% | 0.15 | 18.2% |
| 10 | NVDA | 2026-11-02 | 2026-12-18 | 46 | 194/186 | 2.45 | 2.60 | 74.1% | 9.58% | 106.7% | 19.0% | 0.14 | 17.8% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-02)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-11 (39d) | long call `+1 C 365`, +327.5% | bull call spread `+1 C 350 / -1 C 365`, +106.5% | iron condor `-1 P 335 / +1 P 305 / -1 C 350 / +1 C 380`, +45.8% | iron condor `-1 P 330 / +1 P 305 / -1 C 340 / +1 C 365`, +85.1% | bear put spread `+1 P 330 / -1 P 305`, +171.4% | long strangle `+1 P 290 / +1 C 365`, +230.3% |
| AMD | 2026-12-11 (39d) | bull call spread `+1 C 550 / -1 C 585`, +298.5% | bull call spread `+1 C 470 / -1 C 515`, +127.4% | iron condor `-1 P 465 / +1 P 420 / -1 C 505 / +1 C 550`, +53.1% | iron condor `-1 P 395 / +1 P 350 / -1 C 470 / +1 C 515`, +61.5% | bear call spread `-1 C 385 / +1 C 430`, +167.7% | long call `+1 C 550`, +258.6% |
| AMZN | 2026-12-11 (39d) | long call `+1 C 265`, +297.1% | bull call spread `+1 C 245 / -1 C 265`, +89.3% | iron condor `-1 P 245 / +1 P 225 / -1 C 260 / +1 C 280`, +38.6% | bear call spread `-1 C 235 / +1 C 255`, +56.3% | long put `+1 P 235`, +144.2% | long strangle `+1 P 225 / +1 C 270`, +187.7% |
| DIA | 2026-12-11 (39d) | long call `+1 C 540`, +368.0% | bull put spread `-1 P 540 / +1 P 525`, +122.3% | iron condor `-1 P 519 / +1 P 504 / -1 C 535 / +1 C 550`, +66.4% | iron condor `-1 P 509 / +1 P 499 / -1 C 525 / +1 C 535`, +112.5% | bear put spread `+1 P 514 / -1 P 490`, +195.0% | long call `+1 C 550`, +420.6% |
| GOOGL | 2026-12-11 (39d) | bull call spread `+1 C 300 / -1 C 320`, +328.9% | bull call spread `+1 C 280 / -1 C 300`, +116.6% | iron condor `-1 P 275 / +1 P 255 / -1 C 300 / +1 C 320`, +48.9% | iron condor `-1 P 270 / +1 P 250 / -1 C 280 / +1 C 300`, +75.6% | long put `+1 P 275`, +158.4% | long strangle `+1 P 255 / +1 C 305`, +200.0% |
| META | 2026-12-11 (39d) | bull call spread `+1 C 665 / -1 C 715`, +340.9% | bull call spread `+1 C 620 / -1 C 655`, +127.5% | iron condor `-1 P 605 / +1 P 560 / -1 C 620 / +1 C 665`, +83.5% | iron condor `-1 P 560 / +1 P 530 / -1 C 615 / +1 C 645`, +111.5% | bear put spread `+1 P 580 / -1 P 530`, +197.5% | long strangle `+1 P 530 / +1 C 685`, +251.0% |
| MSFT | 2026-12-11 (39d) | long call `+1 C 550`, +335.5% | bull call spread `+1 C 510 / -1 C 550`, +103.4% | iron condor `-1 P 505 / +1 P 465 / -1 C 520 / +1 C 560`, +42.7% | iron condor `-1 P 485 / +1 P 445 / -1 C 510 / +1 C 550`, +66.2% | bear put spread `+1 P 495 / -1 P 445`, +158.2% | long strangle `+1 P 455 / +1 C 550`, +237.7% |
| NVDA | 2026-12-11 (39d) | long call `+1 C 235`, +288.3% | bull call spread `+1 C 205 / -1 C 220`, +112.8% | iron condor `-1 P 200 / +1 P 180 / -1 C 215 / +1 C 235`, +52.7% | iron condor `-1 P 195 / +1 P 175 / -1 C 205 / +1 C 225`, +63.0% | bear put spread `+1 P 195 / -1 P 175`, +148.0% | long strangle `+1 P 175 / +1 C 230`, +193.1% |
| SPY | 2026-12-11 (39d) | long call `+1 C 797`, +497.8% | bull call spread `+1 C 775 / -1 C 782`, +135.9% | iron condor `-1 P 752 / +1 P 745 / -1 C 775 / +1 C 782`, +88.4% | iron condor `-1 P 737 / +1 P 730 / -1 C 760 / +1 C 767`, +181.2% | bear put spread `+1 P 745 / -1 P 730`, +211.1% | long strangle `+1 P 640 / +1 C 797`, +275.8% |
| TSLA | 2026-12-11 (39d) | long call `+1 C 445`, +329.3% | bull call spread `+1 C 410 / -1 C 445`, +118.6% | iron condor `-1 P 400 / +1 P 365 / -1 C 430 / +1 C 465`, +71.7% | iron condor `-1 P 370 / +1 P 345 / -1 C 405 / +1 C 430`, +108.5% | bear put spread `+1 P 380 / -1 P 345`, +191.2% | long call `+1 C 475`, +375.0% |
| XLF | 2026-12-11 (39d) | long call `+1 C 59.5`, +227.5% | bull call spread `+1 C 57 / -1 C 59.5`, +36.1% | iron condor `-1 P 57 / +1 P 52 / -1 C 58 / +1 C 63`, +12.5% | bear call spread `-1 C 58 / +1 C 59.5`, +29.3% | bear call spread `-1 C 57 / +1 C 59.5`, +38.1% | long strangle `+1 P 52 / +1 C 61`, +280.7% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-02)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | XLF | 2026-11-02 | 2026-11-27 | 25 | 57.5/56.5 | 0.71 | 0.16 | 74.7% | 68.9% | 97.94% | 2134449.5% |
| 2 | XLF | 2026-11-02 | 2026-11-27 | 25 | 57.5/56 | 0.84 | 0.09 | 79.9% | 72.6% | 49.12% | 34065.9% |
| 3 | XLF | 2026-11-02 | 2026-11-27 | 25 | 57.5/55.5 | 0.99 | 0.41 | 79.9% | 72.6% | 36.47% | 9261.0% |
| 4 | META | 2026-11-02 | 2026-11-16 | 14 | 590/580 | 3.50 | 1.15 | 74.7% | 67.6% | 15.42% | 4107.7% |
| 5 | AMD | 2026-11-02 | 2026-12-11 | 39 | 465/455 | 5.80 | 2.25 | 60.7% | 54.5% | 44.97% | 3131.3% |
| 6 | DIA | 2026-11-02 | 2026-11-13 | 11 | 519/514 | 1.80 | 1.55 | 70.0% | 62.3% | 10.66% | 2781.0% |
| 7 | AMZN | 2026-11-02 | 2026-11-16 | 14 | 245/240 | 2.12 | 1.00 | 62.9% | 56.8% | 13.15% | 2405.0% |
| 8 | SPY | 2026-11-02 | 2026-11-13 | 11 | 752/745 | 2.33 | 2.27 | 70.7% | 65.0% | 9.73% | 2080.3% |
| 9 | META | 2026-11-02 | 2026-11-16 | 14 | 605/600 | 2.30 | 1.50 | 60.7% | 53.8% | 11.93% | 1786.3% |
| 10 | META | 2026-11-02 | 2026-11-16 | 14 | 605/595 | 4.42 | 3.54 | 60.7% | 55.4% | 11.89% | 1770.6% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-02)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-30 | 639/602 | 0.39 | 0.36 | 0.06 | +0.32 | 83.9% | 99.8% | 98.5% | 99.0% | +0.8 pp | 0.23 |
| 2 | SPY | 2026-12-11 | 600/565 | 0.35 | 0.33 | 0.06 | +0.29 | 83.7% | 99.8% | 98.7% | 99.0% | +0.8 pp | 0.22 |
| 3 | SPY | 2026-12-11 | 620/565 | 0.64 | 0.62 | 0.10 | +0.54 | 83.7% | 99.7% | 98.3% | 98.8% | +0.8 pp | 0.24 |
| 4 | SPY | 2026-12-11 | 620/600 | 0.29 | 0.26 | 0.05 | +0.24 | 83.6% | 99.7% | 98.3% | 98.6% | +1.1 pp | 0.25 |
| 5 | DIA | 2026-12-31 | 430/390 | 0.51 | 0.35 | 0.09 | +0.43 | 83.3% | 99.6% | 98.1% | 98.7% | +0.9 pp | 0.25 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 56 breaches in 53,300, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,316 eligible spreads of the latest session the median annualised return is 1.0% under the risk-neutral CDF and 83.5% after calibration, against a cash rate of 3.6%.

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
