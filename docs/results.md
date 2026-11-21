# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-20 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-20 | 1,226 | 3,889 | 3,803 | 48,167 |
| AMD | 2020-01-06 | 2026-11-20 | 1,223 | 3,883 | 3,795 | 48,160 |
| AMZN | 2020-01-06 | 2026-11-20 | 1,222 | 3,878 | 3,791 | 47,849 |
| DIA | 2020-01-06 | 2026-11-20 | 1,224 | 3,897 | 3,792 | 47,564 |
| GOOGL | 2020-01-06 | 2026-11-20 | 1,217 | 3,864 | 3,777 | 47,712 |
| META | 2022-07-01 | 2026-11-20 | 857 | 2,782 | 2,694 | 33,935 |
| MSFT | 2020-01-06 | 2026-11-20 | 1,212 | 3,843 | 3,757 | 47,427 |
| NVDA | 2020-01-06 | 2026-11-20 | 1,221 | 3,866 | 3,780 | 47,283 |
| SPY | 2020-01-06 | 2026-11-20 | 1,214 | 3,893 | 3,797 | 47,139 |
| TSLA | 2021-01-04 | 2026-11-20 | 1,072 | 3,421 | 3,334 | 42,162 |
| XLF | 2020-01-06 | 2026-11-20 | 1,214 | 3,866 | 3,776 | 47,796 |

In total: 1,883,795 quotes on 539,030 contracts, in 41,082 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,861 | 97.0% | enters the calibration sample |
| `unsettled` | 986 | 2.4% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1274 | 0.1303 | +0.0029 |
| Log loss (nats) | 0.3940 | 0.3996 | +0.0055 |
| Expected calibration error | 0.0307 | 0.0207 | -0.0100 |

Brier change +0.0029 (95% cluster-bootstrap interval -0.0010 to +0.0056, resampling expiration dates; negative means calibration helped) over 457,661 predictions, 35,946 snapshots and 896 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 144,756 | 0.1022 | 0.1049 | 0.0178 | 0.0233 |
| 21-35d | 145,364 | 0.1282 | 0.1316 | 0.0282 | 0.0249 |
| 36-50d | 87,102 | 0.1488 | 0.1510 | 0.0413 | 0.0183 |
| >50d | 80,439 | 0.1481 | 0.1510 | 0.0476 | 0.0172 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 43,181 | 0.1183 | 0.1191 | 0.0427 | 0.0146 |
| AMD | 42,734 | 0.1824 | 0.1875 | 0.0344 | 0.0452 |
| AMZN | 42,487 | 0.1345 | 0.1395 | 0.0277 | 0.0281 |
| DIA | 42,169 | 0.0634 | 0.0641 | 0.0243 | 0.0162 |
| GOOGL | 42,432 | 0.1352 | 0.1357 | 0.0440 | 0.0192 |
| META | 33,935 | 0.1557 | 0.1588 | 0.0358 | 0.0216 |
| MSFT | 42,319 | 0.1186 | 0.1225 | 0.0196 | 0.0289 |
| NVDA | 41,879 | 0.1612 | 0.1615 | 0.0678 | 0.0203 |
| SPY | 41,854 | 0.0702 | 0.0714 | 0.0241 | 0.0109 |
| TSLA | 42,162 | 0.1813 | 0.1911 | 0.0086 | 0.0651 |
| XLF | 42,509 | 0.0854 | 0.0869 | 0.0223 | 0.0210 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 106,068 | 0.1300 | 0.1314 | 0.0134 | 0.0313 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 138,815 | 0.0364 | 0.0203 | 170,081 | 0.0317 | 0.0408 |
| 0.1-0.2 | 56,858 | 0.1468 | 0.1164 | 63,424 | 0.1481 | 0.1961 |
| 0.2-0.3 | 41,014 | 0.2471 | 0.2116 | 39,958 | 0.2568 | 0.2869 |
| 0.3-0.4 | 33,506 | 0.3502 | 0.3034 | 30,984 | 0.3606 | 0.4087 |
| 0.4-0.5 | 36,017 | 0.4516 | 0.4088 | 25,327 | 0.4464 | 0.4755 |
| 0.5-0.6 | 28,051 | 0.5529 | 0.5061 | 28,987 | 0.5470 | 0.5732 |
| 0.6-0.7 | 33,700 | 0.6504 | 0.6010 | 32,958 | 0.6544 | 0.6647 |
| 0.7-0.8 | 31,356 | 0.7481 | 0.6957 | 21,299 | 0.7503 | 0.7553 |
| 0.8-0.9 | 25,252 | 0.8481 | 0.8197 | 16,792 | 0.8509 | 0.8649 |
| 0.9-1.0 | 33,092 | 0.9619 | 0.9567 | 27,851 | 0.9673 | 0.9679 |

## Top 10 to enter (2026-11-20)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-20 | 2027-01-15 | 56 | 685/660 | 6.99 | 7.35 | 74.3% | 8.16% | 66.8% | 18.3% | 0.13 | 3.8% |
| 2 | SPY | 2026-11-20 | 2027-01-15 | 56 | 685/670 | 4.35 | 4.73 | 74.3% | 8.44% | 69.5% | 17.2% | 0.13 | 3.8% |
| 3 | SPY | 2026-11-20 | 2027-01-15 | 56 | 675/635 | 8.80 | 9.14 | 79.4% | 6.18% | 47.8% | 19.0% | 0.12 | 2.4% |
| 4 | SPY | 2026-11-20 | 2027-01-15 | 56 | 670/650 | 4.54 | 4.88 | 79.4% | 6.58% | 51.5% | 18.7% | 0.12 | 1.9% |
| 5 | SPY | 2026-11-20 | 2027-01-15 | 56 | 675/650 | 6.00 | 6.35 | 77.3% | 6.66% | 52.3% | 18.0% | 0.12 | -0.5% |
| 6 | SPY | 2026-11-20 | 2027-01-15 | 56 | 670/635 | 7.34 | 7.68 | 79.7% | 6.07% | 46.8% | 19.7% | 0.12 | -1.1% |
| 7 | SPY | 2026-11-20 | 2027-01-15 | 56 | 685/650 | 9.24 | 9.61 | 74.3% | 7.33% | 58.6% | 17.9% | 0.13 | -1.4% |
| 8 | SPY | 2026-11-20 | 2027-01-15 | 56 | 660/620 | 7.01 | 7.29 | 82.5% | 4.92% | 36.8% | 19.6% | 0.11 | -2.8% |
| 9 | SPY | 2026-11-20 | 2027-01-15 | 56 | 675/620 | 11.08 | 11.39 | 79.6% | 5.57% | 42.4% | 19.3% | 0.12 | -3.2% |
| 10 | SPY | 2026-11-20 | 2027-01-15 | 56 | 660/605 | 8.77 | 9.07 | 83.6% | 4.64% | 34.4% | 20.7% | 0.11 | -3.9% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-20)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-31 (41d) | long call `+1 C 375`, +302.9% | bull call spread `+1 C 350 / -1 C 375`, +88.3% | iron condor `-1 P 340 / +1 P 310 / -1 C 355 / +1 C 385`, +35.8% | iron condor `-1 P 320 / +1 P 300 / -1 C 345 / +1 C 365`, +65.2% | long put `+1 P 335`, +164.8% | long strangle `+1 P 310 / +1 C 375`, +215.0% |
| AMD | 2026-12-31 (41d) | long call `+1 C 530`, +293.0% | bull put spread `-1 P 500 / +1 P 465`, +103.2% | iron condor `-1 P 390 / +1 P 350 / -1 C 490 / +1 C 530`, +40.1% | iron condor `-1 P 360 / +1 P 320 / -1 C 425 / +1 C 465`, +69.7% | bear call spread `-1 C 320 / +1 C 360`, +210.3% | long call `+1 C 530`, +325.6% |
| AMZN | 2026-12-31 (41d) | bull call spread `+1 C 270 / -1 C 290`, +321.8% | bull call spread `+1 C 250 / -1 C 270`, +101.3% | iron condor `-1 P 245 / +1 P 225 / -1 C 260 / +1 C 280`, +60.3% | iron condor `-1 P 225 / +1 P 205 / -1 C 250 / +1 C 270`, +64.9% | long put `+1 P 245`, +167.8% | long call `+1 C 285`, +322.9% |
| DIA | 2026-12-31 (41d) | long call `+1 C 510`, +344.2% | bull call spread `+1 C 491 / -1 C 510`, +96.0% | iron condor `-1 P 481 / +1 P 452 / -1 C 500 / +1 C 529`, +46.5% | iron condor `-1 P 467 / +1 P 443 / -1 C 486 / +1 C 510`, +91.7% | bear put spread `+1 P 476 / -1 P 434`, +181.9% | long strangle `+1 P 452 / +1 C 520`, +208.6% |
| GOOGL | 2026-12-31 (41d) | bull call spread `+1 C 300 / -1 C 320`, +323.1% | bull call spread `+1 C 280 / -1 C 300`, +90.4% | iron condor `-1 P 265 / +1 P 245 / -1 C 290 / +1 C 310`, +51.9% | iron condor `-1 P 245 / +1 P 225 / -1 C 270 / +1 C 290`, +88.9% | long put `+1 P 250`, +184.6% | long strangle `+1 P 230 / +1 C 305`, +234.0% |
| META | 2026-12-31 (41d) | long call `+1 C 630`, +335.1% | bull call spread `+1 C 580 / -1 C 630`, +107.5% | iron condor `-1 P 560 / +1 P 505 / -1 C 605 / +1 C 660`, +59.2% | iron condor `-1 P 515 / +1 P 465 / -1 C 565 / +1 C 615`, +100.7% | bear call spread `-1 C 490 / +1 C 545`, +195.9% | long call `+1 C 675`, +374.8% |
| MSFT | 2026-12-31 (41d) | long call `+1 C 525`, +277.6% | bull put spread `-1 P 535 / +1 P 495`, +90.7% | iron condor `-1 P 480 / +1 P 435 / -1 C 525 / +1 C 570`, +40.6% | iron condor `-1 P 445 / +1 P 410 / -1 C 490 / +1 C 525`, +80.1% | long put `+1 P 480`, +163.8% | long call `+1 C 555`, +272.4% |
| NVDA | 2026-12-31 (41d) | long call `+1 C 155`, +372.8% | bull call spread `+1 C 130 / -1 C 140`, +105.6% | iron condor `-1 P 120 / +1 P 110 / -1 C 145 / +1 C 155`, +60.4% | iron condor `-1 P 110 / +1 P 100 / -1 C 130 / +1 C 140`, +98.9% | bear put spread `+1 P 110 / -1 P 100`, +191.9% | long strangle `+1 P 110 / +1 C 140`, +186.6% |
| SPY | 2026-12-31 (41d) | long call `+1 C 759`, +436.9% | bull call spread `+1 C 717 / -1 C 731`, +129.1% | iron condor `-1 P 683 / +1 P 669 / -1 C 731 / +1 C 745`, +77.5% | iron condor `-1 P 662 / +1 P 635 / -1 C 690 / +1 C 717`, +169.2% | bear put spread `+1 P 676 / -1 P 621`, +212.9% | long call `+1 C 759`, +530.3% |
| TSLA | 2026-12-31 (41d) | long call `+1 C 400`, +335.7% | bull call spread `+1 C 365 / -1 C 390`, +102.0% | iron condor `-1 P 340 / +1 P 310 / -1 C 375 / +1 C 405`, +57.6% | iron condor `-1 P 305 / +1 P 275 / -1 C 350 / +1 C 380`, +77.4% | bear put spread `+1 P 325 / -1 P 295`, +181.1% | long call `+1 C 415`, +348.7% |
| XLF | 2026-12-31 (41d) | long call `+1 C 57`, +204.9% | long call `+1 C 53`, +29.6% | bear call spread `-1 C 57 / +1 C 60`, -1.4% | bear call spread `-1 C 56 / +1 C 60`, +0.8% | bear put spread `+1 P 56 / -1 P 51`, +13.0% | long strangle `+1 P 53 / +1 C 57`, +20.7% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-20)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | GOOGL | 2026-11-20 | 2026-12-04 | 14 | 262.5/260 | 1.20 | 0.25 | 62.4% | 57.3% | 24.74% | 31716.5% |
| 2 | NVDA | 2026-11-20 | 2026-12-04 | 14 | 122/118 | 1.50 | 0.55 | 74.3% | 67.4% | 19.04% | 9314.1% |
| 3 | NVDA | 2026-11-20 | 2026-12-04 | 14 | 121/118 | 1.12 | 0.20 | 74.3% | 67.4% | 19.04% | 9314.1% |
| 4 | NVDA | 2026-11-20 | 2026-12-04 | 14 | 123/118 | 1.82 | 1.00 | 74.3% | 67.4% | 17.17% | 6126.7% |
| 5 | NVDA | 2026-11-20 | 2026-12-04 | 14 | 113/110 | 1.05 | 0.60 | 74.3% | 68.4% | 16.05% | 4746.6% |
| 6 | GOOGL | 2026-11-20 | 2026-12-04 | 14 | 257.5/250 | 2.40 | 1.00 | 77.3% | 72.2% | 14.82% | 3568.9% |
| 7 | GOOGL | 2026-11-20 | 2026-12-04 | 14 | 265/260 | 2.22 | 0.95 | 62.4% | 57.3% | 14.69% | 3467.0% |
| 8 | AAPL | 2026-11-20 | 2026-12-04 | 14 | 342.5/335 | 2.72 | 1.55 | 70.1% | 64.4% | 14.68% | 3455.3% |
| 9 | AMZN | 2026-11-20 | 2026-12-04 | 14 | 232.5/227.5 | 1.47 | 0.40 | 79.7% | 75.0% | 13.92% | 2890.0% |
| 10 | NVDA | 2026-11-20 | 2026-12-04 | 14 | 122/115 | 2.40 | 1.50 | 74.3% | 67.4% | 13.23% | 2450.4% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-20)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-04 | 550/515 | 0.44 | 0.38 | 0.09 | +0.35 | 80.4% | 99.7% | 98.3% | 98.8% | +1.0 pp | 0.22 |
| 2 | SPY | 2026-12-04 | 570/515 | 0.82 | 0.75 | 0.18 | +0.64 | 77.9% | 99.4% | 97.6% | 98.5% | +0.9 pp | 0.23 |
| 3 | SPY | 2026-12-04 | 570/550 | 0.38 | 0.31 | 0.10 | +0.29 | 74.9% | 99.4% | 97.6% | 98.1% | +1.3 pp | 0.22 |
| 4 | SPY | 2026-12-04 | 585/550 | 0.79 | 0.72 | 0.25 | +0.54 | 67.9% | 98.4% | 96.8% | 97.7% | +0.7 pp | 0.21 |
| 5 | SPY | 2026-12-18 | 550/515 | 0.85 | 0.74 | 0.29 | +0.56 | 65.5% | 98.4% | 96.8% | 97.6% | +0.8 pp | 0.19 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 73 breaches in 53,934, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,294 eligible spreads of the latest session the median annualised return is 1.5% under the risk-neutral CDF and 89.7% after calibration, against a cash rate of 3.6%.

## Caveats

- **Correlated samples.** Each snapshot contributes up to 13 nested targets, on average 37.8 snapshots share an expiration, and the market moves together on an expiration date. The interval above resamples expiration dates for that reason.
- **Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above the bid are used; 6 snapshots with fewer than 4 usable puts are excluded and counted above.
- **Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a spread whose long strike lies below the lowest knot is ineligible. Share of snapshots with a flagged tail: left tail uncovered 12.0%, right tail uncovered 15.2%.
- **Splits and unadjusted closes.** Closes are as traded. 214 snapshots whose window contains a daily move beyond 0.4 in log terms are excluded.
- **Ticker reuse.** 0 snapshots predate the current company behind a reused symbol.
- **Hindsight in the universe.** The watchlist is today's large caps, which biases the realised downside frequency low and makes the calibrated map optimistic. This is the most important caveat here.
- **Prices.** Mids are indicative end-of-day values, so credits are mid credits; the natural credit is shown and must be positive. Quote and close times can differ. American-style puts carry an early-exercise premium that slightly overstates P(S < K) deep in the money, and the risk-free rate is the constant 4.5%.
- **Coverage gaps.** The vendor history misses some sessions, which affects sampling, not labels. One pooled map serves every underlying and expiry; the segment tables show the differences.
- **Derived data only.** This report holds derived statistics and a few derived spread rows, never raw vendor quotes.
