# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-10 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-10 | 1,218 | 3,857 | 3,765 | 47,675 |
| AMD | 2020-01-06 | 2026-11-10 | 1,215 | 3,851 | 3,758 | 47,695 |
| AMZN | 2020-01-06 | 2026-11-10 | 1,214 | 3,846 | 3,753 | 47,355 |
| DIA | 2020-01-06 | 2026-11-10 | 1,216 | 3,865 | 3,753 | 47,093 |
| GOOGL | 2020-01-06 | 2026-11-10 | 1,209 | 3,832 | 3,740 | 47,231 |
| META | 2022-07-01 | 2026-11-10 | 849 | 2,750 | 2,656 | 33,461 |
| MSFT | 2020-01-06 | 2026-11-10 | 1,204 | 3,811 | 3,720 | 46,958 |
| NVDA | 2020-01-06 | 2026-11-10 | 1,213 | 3,834 | 3,743 | 46,802 |
| SPY | 2020-01-06 | 2026-11-10 | 1,206 | 3,861 | 3,761 | 46,683 |
| TSLA | 2021-01-04 | 2026-11-10 | 1,064 | 3,389 | 3,297 | 41,681 |
| XLF | 2020-01-06 | 2026-11-10 | 1,206 | 3,834 | 3,739 | 47,315 |

In total: 1,866,710 quotes on 534,630 contracts, in 40,730 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,450 | 96.9% | enters the calibration sample |
| `unsettled` | 1,045 | 2.6% | the expiration is after the last priced session, so there is no outcome yet |
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

Brier change +0.0026 (95% cluster-bootstrap interval -0.0007 to +0.0050, resampling expiration dates; negative means calibration helped) over 452,416 predictions, 35,536 snapshots and 890 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 143,600 | 0.1019 | 0.1046 | 0.0185 | 0.0226 |
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
| SPY | 41,398 | 0.0688 | 0.0697 | 0.0270 | 0.0106 |
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
| 2026 | 100,823 | 0.1263 | 0.1263 | 0.0256 | 0.0207 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,374 | 0.0363 | 0.0188 | 168,419 | 0.0317 | 0.0392 |
| 0.1-0.2 | 56,180 | 0.1468 | 0.1125 | 62,562 | 0.1481 | 0.1921 |
| 0.2-0.3 | 40,502 | 0.2471 | 0.2075 | 39,459 | 0.2567 | 0.2826 |
| 0.3-0.4 | 33,075 | 0.3502 | 0.2988 | 30,591 | 0.3606 | 0.4043 |
| 0.4-0.5 | 35,616 | 0.4517 | 0.4050 | 25,001 | 0.4464 | 0.4704 |
| 0.5-0.6 | 27,642 | 0.5529 | 0.5005 | 28,565 | 0.5471 | 0.5681 |
| 0.6-0.7 | 33,267 | 0.6504 | 0.5969 | 32,469 | 0.6544 | 0.6602 |
| 0.7-0.8 | 30,931 | 0.7481 | 0.6920 | 21,106 | 0.7503 | 0.7532 |
| 0.8-0.9 | 25,028 | 0.8481 | 0.8184 | 16,646 | 0.8509 | 0.8641 |
| 0.9-1.0 | 32,801 | 0.9619 | 0.9564 | 27,598 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-10)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMZN | 2026-11-10 | 2027-01-15 | 66 | 270/255 | 5.50 | 5.70 | 67.9% | 10.62% | 74.8% | 16.3% | 0.14 | 15.0% |
| 2 | SPY | 2026-11-10 | 2026-12-31 | 51 | 742/727 | 3.66 | 3.75 | 78.9% | 7.02% | 62.5% | 19.6% | 0.13 | 13.8% |
| 3 | AMZN | 2026-11-10 | 2027-01-15 | 66 | 270/250 | 6.85 | 7.05 | 69.5% | 9.87% | 68.3% | 17.0% | 0.14 | 12.1% |
| 4 | SPY | 2026-11-10 | 2026-12-31 | 51 | 742/720 | 4.99 | 5.07 | 79.8% | 6.69% | 59.0% | 20.7% | 0.13 | 10.4% |
| 5 | SPY | 2026-11-10 | 2026-12-31 | 51 | 727/720 | 1.25 | 1.32 | 84.7% | 6.05% | 52.3% | 23.9% | 0.13 | 7.0% |
| 6 | SPY | 2026-11-10 | 2026-12-31 | 51 | 727/705 | 3.43 | 3.50 | 86.1% | 4.79% | 39.8% | 22.7% | 0.12 | 6.0% |
| 7 | SPY | 2026-11-10 | 2026-12-31 | 51 | 742/735 | 1.84 | 1.93 | 76.2% | 8.15% | 75.2% | 20.1% | 0.14 | 5.7% |
| 8 | SPY | 2026-11-10 | 2026-12-31 | 51 | 720/705 | 2.12 | 2.18 | 87.6% | 4.23% | 34.6% | 22.0% | 0.10 | 5.6% |
| 9 | SPY | 2026-11-10 | 2026-12-31 | 51 | 735/720 | 3.07 | 3.14 | 81.0% | 6.07% | 52.5% | 21.1% | 0.12 | 4.7% |
| 10 | AMZN | 2026-11-10 | 2027-01-15 | 66 | 270/245 | 8.00 | 8.20 | 69.9% | 8.99% | 61.0% | 17.1% | 0.14 | 4.6% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-10)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-11 (31d) | long call `+1 C 370`, +366.1% | bull call spread `+1 C 355 / -1 C 370`, +115.5% | iron condor `-1 P 345 / +1 P 335 / -1 C 360 / +1 C 370`, +64.9% | iron condor `-1 P 340 / +1 P 330 / -1 C 350 / +1 C 360`, +115.0% | bear put spread `+1 P 345 / -1 P 320`, +196.2% | long strangle `+1 P 305 / +1 C 375`, +256.8% |
| AMD | 2026-12-11 (31d) | long call `+1 C 590`, +333.2% | bull call spread `+1 C 530 / -1 C 580`, +111.4% | iron condor `-1 P 515 / +1 P 465 / -1 C 555 / +1 C 605`, +71.8% | iron condor `-1 P 465 / +1 P 425 / -1 C 525 / +1 C 565`, +78.6% | long put `+1 P 475`, +174.4% | long strangle `+1 P 440 / +1 C 590`, +232.7% |
| AMZN | 2026-12-11 (31d) | long call `+1 C 295`, +323.9% | bull call spread `+1 C 275 / -1 C 285`, +115.9% | iron condor `-1 P 270 / +1 P 250 / -1 C 280 / +1 C 300`, +65.9% | iron condor `-1 P 260 / +1 P 250 / -1 C 275 / +1 C 285`, +86.6% | bear put spread `+1 P 265 / -1 P 250`, +188.3% | long strangle `+1 P 250 / +1 C 300`, +243.8% |
| DIA | 2026-12-11 (31d) | long call `+1 C 543`, +387.0% | bull put spread `-1 P 537.5 / +1 P 527`, +119.7% | iron condor `-1 P 517 / +1 P 506 / -1 C 532 / +1 C 543`, +55.9% | iron condor `-1 P 511 / +1 P 501 / -1 C 522 / +1 C 532`, +128.6% | bear put spread `+1 P 517 / -1 P 490`, +193.8% | long strangle `+1 P 445 / +1 C 543`, +300.2% |
| GOOGL | 2026-12-11 (31d) | long call `+1 C 305`, +316.6% | bull put spread `-1 P 300 / +1 P 290`, +123.5% | iron condor `-1 P 280 / +1 P 265 / -1 C 310 / +1 C 325`, +53.9% | iron condor `-1 P 275 / +1 P 260 / -1 C 290 / +1 C 305`, +80.8% | bear put spread `+1 P 280 / -1 P 260`, +184.5% | long strangle `+1 P 245 / +1 C 310`, +218.5% |
| META | 2026-12-11 (31d) | bull call spread `+1 C 705 / -1 C 755`, +355.9% | bull call spread `+1 C 650 / -1 C 695`, +120.9% | iron condor `-1 P 630 / +1 P 590 / -1 C 680 / +1 C 720`, +78.6% | iron condor `-1 P 605 / +1 P 575 / -1 C 650 / +1 C 680`, +103.6% | bear put spread `+1 P 615 / -1 P 560`, +201.7% | bull call spread `+1 C 740 / -1 C 800`, +432.4% |
| MSFT | 2026-12-11 (31d) | long call `+1 C 585`, +334.3% | bull call spread `+1 C 530 / -1 C 565`, +101.1% | iron condor `-1 P 530 / +1 P 500 / -1 C 555 / +1 C 585`, +55.2% | iron condor `-1 P 500 / +1 P 480 / -1 C 535 / +1 C 555`, +73.6% | bear put spread `+1 P 515 / -1 P 500`, +168.0% | long call `+1 C 585`, +420.3% |
| NVDA | 2026-12-11 (31d) | long call `+1 C 190`, +343.9% | bull call spread `+1 C 175 / -1 C 190`, +124.5% | iron condor `-1 P 165 / +1 P 150 / -1 C 180 / +1 C 195`, +81.0% | iron condor `-1 P 150 / +1 P 140 / -1 C 170 / +1 C 180`, +122.5% | bear put spread `+1 P 155 / -1 P 140`, +197.5% | long call `+1 C 205`, +431.4% |
| SPY | 2026-12-11 (31d) | long call `+1 C 780`, +506.3% | bull put spread `-1 P 780 / +1 P 765`, +141.9% | iron condor `-1 P 742 / +1 P 735 / -1 C 765 / +1 C 772`, +58.5% | iron condor `-1 P 742 / +1 P 727 / -1 C 750 / +1 C 765`, +181.0% | bear put spread `+1 P 742 / -1 P 720`, +209.7% | long call `+1 C 780`, +478.4% |
| TSLA | 2026-12-11 (31d) | bull call spread `+1 C 420 / -1 C 445`, +350.5% | bull call spread `+1 C 385 / -1 C 420`, +114.6% | iron condor `-1 P 370 / +1 P 340 / -1 C 395 / +1 C 425`, +65.4% | iron condor `-1 P 350 / +1 P 325 / -1 C 380 / +1 C 405`, +99.8% | bear put spread `+1 P 350 / -1 P 315`, +171.3% | long strangle `+1 P 325 / +1 C 435`, +257.1% |
| XLF | 2026-12-11 (31d) | long call `+1 C 59`, +207.4% | bull call spread `+1 C 57.5 / -1 C 60`, +29.8% | iron condor `-1 P 57.5 / +1 P 53.5 / -1 C 59 / +1 C 63`, +10.8% | bear put spread `+1 P 59 / -1 P 57`, +32.1% | long put `+1 P 59`, +120.4% | long strangle `+1 P 57 / +1 C 60`, +133.0% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-10)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | AMD | 2026-11-10 | 2026-11-23 | 13 | 515/510 | 3.20 | 0.45 | 59.1% | 51.9% | 64.24% | 112135165.7% |
| 2 | AMZN | 2026-11-10 | 2026-11-23 | 13 | 265/262.5 | 1.30 | 0.25 | 69.5% | 61.5% | 49.85% | 8542386.4% |
| 3 | AMD | 2026-11-10 | 2026-11-23 | 13 | 515/505 | 5.88 | 3.55 | 59.1% | 51.9% | 44.26% | 2939007.7% |
| 4 | AMD | 2026-11-10 | 2026-11-23 | 13 | 515/500 | 7.88 | 3.85 | 60.7% | 52.5% | 29.68% | 147404.8% |
| 5 | AMD | 2026-11-10 | 2026-11-23 | 13 | 510/505 | 2.67 | 1.00 | 59.1% | 52.2% | 28.79% | 121608.8% |
| 6 | AMD | 2026-11-10 | 2026-11-23 | 13 | 515/495 | 9.83 | 6.10 | 60.7% | 55.6% | 24.73% | 49383.7% |
| 7 | AMD | 2026-11-10 | 2026-11-23 | 13 | 515/485 | 13.55 | 10.20 | 68.0% | 60.1% | 20.26% | 17675.1% |
| 8 | AMD | 2026-11-10 | 2026-11-23 | 13 | 510/500 | 4.68 | 1.30 | 60.7% | 55.3% | 17.98% | 10287.3% |
| 9 | AMD | 2026-11-10 | 2026-11-23 | 13 | 515/475 | 16.38 | 13.40 | 68.2% | 60.8% | 16.49% | 7161.9% |
| 10 | AMD | 2026-11-10 | 2026-11-23 | 13 | 510/495 | 6.62 | 3.55 | 63.9% | 58.4% | 16.24% | 6735.0% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-10)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-11 | 635/600 | 0.33 | 0.32 | 0.05 | +0.28 | 84.2% | 99.8% | 98.7% | 99.0% | +0.7 pp | 0.22 |
| 2 | SPY | 2026-12-24 | 620/600 | 0.28 | 0.24 | 0.05 | +0.23 | 83.6% | 99.8% | 98.4% | 98.6% | +1.2 pp | 0.24 |
| 3 | SPY | 2026-12-31 | 600/560 | 0.43 | 0.41 | 0.07 | +0.36 | 83.5% | 99.8% | 98.6% | 98.9% | +0.8 pp | 0.23 |
| 4 | SPY | 2026-12-24 | 620/560 | 0.64 | 0.60 | 0.11 | +0.53 | 83.4% | 99.8% | 98.4% | 98.9% | +0.8 pp | 0.23 |
| 5 | SPY | 2026-12-24 | 600/560 | 0.35 | 0.33 | 0.06 | +0.30 | 83.2% | 99.8% | 98.8% | 99.1% | +0.7 pp | 0.20 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 58 breaches in 53,481, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,246 eligible spreads of the latest session the median annualised return is 1.3% under the risk-neutral CDF and 67.2% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.6 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.1%, right tail uncovered 15.1%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
