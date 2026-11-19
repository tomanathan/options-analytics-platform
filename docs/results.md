# Results

Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of the 2026-11-18 session.

## Data coverage

| Underlying | First session | Last session | Sessions | Chain snapshots | Settled snapshots | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 2020-01-06 | 2026-11-18 | 1,224 | 3,881 | 3,777 | 47,829 |
| AMD | 2020-01-06 | 2026-11-18 | 1,221 | 3,875 | 3,770 | 47,835 |
| AMZN | 2020-01-06 | 2026-11-18 | 1,220 | 3,870 | 3,766 | 47,524 |
| DIA | 2020-01-06 | 2026-11-18 | 1,222 | 3,889 | 3,763 | 47,223 |
| GOOGL | 2020-01-06 | 2026-11-18 | 1,215 | 3,856 | 3,752 | 47,387 |
| META | 2022-07-01 | 2026-11-18 | 855 | 2,774 | 2,668 | 33,597 |
| MSFT | 2020-01-06 | 2026-11-18 | 1,210 | 3,835 | 3,732 | 47,102 |
| NVDA | 2020-01-06 | 2026-11-18 | 1,219 | 3,858 | 3,755 | 46,958 |
| SPY | 2020-01-06 | 2026-11-18 | 1,212 | 3,885 | 3,771 | 46,801 |
| TSLA | 2021-01-04 | 2026-11-18 | 1,070 | 3,413 | 3,309 | 41,837 |
| XLF | 2020-01-06 | 2026-11-18 | 1,212 | 3,858 | 3,751 | 47,471 |

In total: 1,879,416 quotes on 538,246 contracts, in 40,994 chain snapshots (an underlying, a trade date and an expiration).

## Snapshot exclusions

Every chain snapshot is classified; only `ok` snapshots produce predictions. Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent OHLC bars, staging filters) are logged by the loaders and are not counted in this report.

| Status | Snapshots | Share | Meaning |
| --- | ---: | ---: | --- |
| `ok` | 39,579 | 96.5% | enters the calibration sample |
| `unsettled` | 1,180 | 2.9% | the expiration is after the last priced session, so there is no outcome yet |
| `too_few_puts` | 6 | 0.0% | fewer than 4 usable puts (a positive bid and an ask at or above the bid) |
| `no_close` | 15 | 0.0% | no official close of the underlying on the trade date |
| `split_in_window` | 214 | 0.5% | a split between the trade date and settlement (closes are unadjusted) |

## Calibration: risk-neutral vs calibrated

Each year's map is fitted only on predictions that had expired before 1 January of that year and applied to that year's predictions (walk-forward, refit annually); years before 2021 are burn-in and the metrics use out-of-sample rows only.

| Metric | Risk-neutral | Calibrated | Change |
| --- | ---: | ---: | ---: |
| Brier score | 0.1266 | 0.1292 | +0.0026 |
| Log loss (nats) | 0.3919 | 0.3965 | +0.0047 |
| Expected calibration error | 0.0333 | 0.0181 | -0.0152 |

Brier change +0.0026 (95% cluster-bootstrap interval -0.0005 to +0.0057, resampling expiration dates; negative means calibration helped) over 454,031 predictions, 35,664 snapshots and 895 expiration clusters. Predictions that resolve on the same date share one market move, so the effective sample is closer to the number of clusters than to the number of predictions.

### By days to expiration

| DTE bucket | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| <=20d | 144,500 | 0.1021 | 0.1047 | 0.0182 | 0.0229 |
| 21-35d | 144,654 | 0.1277 | 0.1310 | 0.0299 | 0.0234 |
| 36-50d | 85,984 | 0.1475 | 0.1493 | 0.0460 | 0.0149 |
| >50d | 78,893 | 0.1466 | 0.1489 | 0.0540 | 0.0140 |

### By underlying

| Underlying | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 42,843 | 0.1187 | 0.1196 | 0.0426 | 0.0155 |
| AMD | 42,409 | 0.1813 | 0.1858 | 0.0387 | 0.0417 |
| AMZN | 42,162 | 0.1348 | 0.1397 | 0.0283 | 0.0275 |
| DIA | 41,828 | 0.0624 | 0.0629 | 0.0263 | 0.0157 |
| GOOGL | 42,107 | 0.1329 | 0.1329 | 0.0490 | 0.0160 |
| META | 33,597 | 0.1537 | 0.1562 | 0.0415 | 0.0182 |
| MSFT | 41,994 | 0.1185 | 0.1222 | 0.0211 | 0.0273 |
| NVDA | 41,554 | 0.1589 | 0.1586 | 0.0733 | 0.0180 |
| SPY | 41,516 | 0.0687 | 0.0697 | 0.0268 | 0.0108 |
| TSLA | 41,837 | 0.1816 | 0.1912 | 0.0094 | 0.0638 |
| XLF | 42,184 | 0.0857 | 0.0871 | 0.0225 | 0.0205 |

### By fold year

| Fold | Predictions | Brier raw | Brier calibrated | ECE raw | ECE calibrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 55,189 | 0.1123 | 0.1103 | 0.0619 | 0.0385 |
| 2022 | 57,023 | 0.1663 | 0.2010 | 0.0752 | 0.1776 |
| 2023 | 61,525 | 0.1181 | 0.1135 | 0.0964 | 0.0768 |
| 2024 | 70,651 | 0.1158 | 0.1123 | 0.0534 | 0.0163 |
| 2025 | 107,205 | 0.1248 | 0.1232 | 0.0371 | 0.0118 |
| 2026 | 102,438 | 0.1265 | 0.1267 | 0.0243 | 0.0208 |

## Reliability

![Reliability diagram](img/calibration.png)

| Bin | n raw | Predicted raw | Realised raw | n calibrated | Predicted calibrated | Realised calibrated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 137,942 | 0.0363 | 0.0191 | 169,038 | 0.0316 | 0.0395 |
| 0.1-0.2 | 56,346 | 0.1469 | 0.1128 | 62,782 | 0.1481 | 0.1923 |
| 0.2-0.3 | 40,629 | 0.2471 | 0.2078 | 39,589 | 0.2568 | 0.2829 |
| 0.3-0.4 | 33,188 | 0.3502 | 0.2991 | 30,685 | 0.3606 | 0.4044 |
| 0.4-0.5 | 35,716 | 0.4517 | 0.4051 | 25,075 | 0.4464 | 0.4707 |
| 0.5-0.6 | 27,725 | 0.5529 | 0.5008 | 28,659 | 0.5471 | 0.5684 |
| 0.6-0.7 | 33,375 | 0.6504 | 0.5971 | 32,606 | 0.6544 | 0.6611 |
| 0.7-0.8 | 31,055 | 0.7481 | 0.6928 | 21,173 | 0.7503 | 0.7538 |
| 0.8-0.9 | 25,124 | 0.8481 | 0.8188 | 16,710 | 0.8509 | 0.8642 |
| 0.9-1.0 | 32,931 | 0.9620 | 0.9565 | 27,714 | 0.9674 | 0.9677 |

## Top 10 to enter (2026-11-18)

Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), 45 to 69 days to expiry, short strike 95% to below 100% of the close, ranked by annualised natural return with the POP shrunk halfway toward the market-implied POP, then annualised return on max loss and reward/risk.

On the rule lab's 2025-2026 hold-out, measured on 2026-10-19, this rule made 4,053 trades that won 73.0% of the time against 74.9% predicted, with a mean return on max loss of +7.53% per trade (95% interval -7.29% to +21.10%, so not shown to be above zero), +3.02% in total on capital at risk, a Sharpe per trade of 0.129 and 18.8% of trades at the maximum loss (docs/rule-lab.md), and over the full 2021-2026 out-of-sample backtest +10.3% per trade (0.9% to 19.0%) but -3.05% in total on capital at risk, because a few wide spreads with large maximum losses dominate the dollar total, so the per-trade figure holds only with equal risk per trade (docs/backtest-entry-rule.md).

| Rank | Underlying | Session | Expiration | DTE | Short/long | Natural credit | Mid credit | POP calibrated | Expected return on max loss | Annualised return on max loss | Edge (% of mid) | Reward/risk | Entry score (annualised) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-11-18 | 2027-01-15 | 58 | 730/710 | 6.22 | 6.32 | 73.5% | 9.41% | 76.1% | 19.1% | 0.15 | 20.4% |
| 2 | SPY | 2026-11-18 | 2027-01-15 | 58 | 725/715 | 3.02 | 3.11 | 74.7% | 8.59% | 68.0% | 17.8% | 0.13 | 19.3% |
| 3 | SPY | 2026-11-18 | 2027-01-15 | 58 | 730/725 | 1.77 | 1.86 | 69.8% | 12.00% | 104.1% | 19.3% | 0.16 | 17.6% |
| 4 | SPY | 2026-11-18 | 2027-01-15 | 58 | 725/710 | 4.39 | 4.46 | 74.7% | 8.63% | 68.4% | 19.1% | 0.14 | 16.5% |
| 5 | SPY | 2026-11-18 | 2027-01-15 | 58 | 730/700 | 8.54 | 8.64 | 74.7% | 8.23% | 64.5% | 19.0% | 0.14 | 13.0% |
| 6 | SPY | 2026-11-18 | 2027-01-15 | 58 | 715/700 | 3.57 | 3.67 | 79.7% | 6.97% | 52.8% | 19.8% | 0.13 | 12.4% |
| 7 | SPY | 2026-11-18 | 2027-01-15 | 58 | 730/715 | 4.85 | 4.97 | 70.5% | 9.66% | 78.7% | 18.4% | 0.14 | 9.7% |
| 8 | SPY | 2026-11-18 | 2027-01-15 | 58 | 700/685 | 2.66 | 2.74 | 84.6% | 5.71% | 41.8% | 23.1% | 0.12 | 7.4% |
| 9 | SPY | 2026-11-18 | 2027-01-15 | 58 | 710/700 | 2.24 | 2.32 | 79.9% | 6.13% | 45.4% | 18.4% | 0.11 | 6.3% |
| 10 | AAPL | 2026-11-18 | 2027-01-15 | 58 | 350/330 | 5.60 | 5.87 | 74.7% | 8.69% | 68.9% | 19.5% | 0.15 | 5.8% |

This is a ranking of a historical calibration, not trade advice: it orders spreads by what one pooled calibration map says happened on average, pulled halfway toward the probability the price implies, and that map is optimistic (see the caveats). Credits are dollars per share; the edge is the mid credit minus the calibrated fair credit, as a share of the mid credit; reward/risk is per trade; the entry score is the annualised return on max loss at the natural credit with that shrunk probability of profit, the number the rule ranks by.

## Which structure serves each outcome (2026-11-18)

| Underlying | Expiry (DTE) | Up, above the 75th percentile | Up, moderately (55th to 85th) | Flat (25th to 75th) | Down, moderately (15th to 45th) | Down, below the 25th percentile | Big move, outside the 10th to 90th |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AAPL | 2026-12-18 (30d) | long call `+1 C 380`, +417.3% | bull call spread `+1 C 360 / -1 C 375`, +122.0% | iron condor `-1 P 350 / +1 P 340 / -1 C 365 / +1 C 375`, +75.9% | iron condor `-1 P 340 / +1 P 330 / -1 C 355 / +1 C 365`, +133.2% | bear put spread `+1 P 345 / -1 P 325`, +201.3% | long call `+1 C 380`, +499.5% |
| AMD | 2026-12-18 (30d) | long call `+1 C 640`, +402.0% | bull call spread `+1 C 560 / -1 C 600`, +119.0% | iron condor `-1 P 510 / +1 P 460 / -1 C 570 / +1 C 620`, +77.0% | iron condor `-1 P 480 / +1 P 440 / -1 C 540 / +1 C 580`, +110.7% | bear put spread `+1 P 480 / -1 P 440`, +185.2% | long strangle `+1 P 460 / +1 C 600`, +241.5% |
| AMZN | 2026-12-18 (30d) | long call `+1 C 290`, +387.0% | bull call spread `+1 C 275 / -1 C 285`, +130.9% | iron condor `-1 P 265 / +1 P 255 / -1 C 280 / +1 C 290`, +83.2% | iron condor `-1 P 250 / +1 P 245 / -1 C 270 / +1 C 275`, +135.2% | bear put spread `+1 P 260 / -1 P 235`, +200.8% | long call `+1 C 300`, +458.0% |
| DIA | 2026-12-18 (30d) | long call `+1 C 522`, +423.8% | bull call spread `+1 C 507 / -1 C 522`, +111.3% | iron condor `-1 P 497 / +1 P 482 / -1 C 517 / +1 C 532`, +56.3% | iron condor `-1 P 492 / +1 P 482 / -1 C 502 / +1 C 512`, +118.6% | bear call spread `-1 C 460 / +1 C 497`, +192.1% | long call `+1 C 532`, +604.7% |
| GOOGL | 2026-12-18 (30d) | bull call spread `+1 C 305 / -1 C 325`, +358.2% | bull call spread `+1 C 290 / -1 C 300`, +132.0% | iron condor `-1 P 280 / +1 P 270 / -1 C 300 / +1 C 310`, +77.8% | iron condor `-1 P 265 / +1 P 260 / -1 C 285 / +1 C 290`, +118.6% | bear put spread `+1 P 270 / -1 P 245`, +199.4% | long call `+1 C 310`, +340.9% |
| META | 2026-12-18 (30d) | bull call spread `+1 C 680 / -1 C 695`, +379.1% | bull call spread `+1 C 635 / -1 C 655`, +141.6% | iron condor `-1 P 605 / +1 P 580 / -1 C 655 / +1 C 680`, +97.2% | iron condor `-1 P 565 / +1 P 555 / -1 C 625 / +1 C 635`, +151.9% | bear put spread `+1 P 590 / -1 P 540`, +213.0% | bull call spread `+1 C 710 / -1 C 740`, +444.8% |
| MSFT | 2026-12-18 (30d) | long call `+1 C 550`, +380.3% | bull call spread `+1 C 520 / -1 C 540`, +124.3% | iron condor `-1 P 505 / +1 P 480 / -1 C 525 / +1 C 550`, +75.0% | iron condor `-1 P 490 / +1 P 470 / -1 C 510 / +1 C 530`, +119.5% | bear put spread `+1 P 495 / -1 P 455`, +197.5% | long call `+1 C 560`, +438.0% |
| NVDA | 2026-12-18 (30d) | bull call spread `+1 C 170 / -1 C 181`, +383.9% | bull call spread `+1 C 156 / -1 C 160`, +143.2% | iron condor `-1 P 146 / +1 P 142 / -1 C 166 / +1 C 170`, +93.3% | iron condor `-1 P 136 / +1 P 132 / -1 C 152 / +1 C 156`, +157.3% | bear put spread `+1 P 142 / -1 P 132`, +210.4% | bull call spread `+1 C 177 / -1 C 189`, +442.4% |
| SPY | 2026-12-18 (30d) | long call `+1 C 774`, +615.1% | bull call spread `+1 C 745 / -1 C 759`, +136.1% | iron condor `-1 P 730 / +1 P 723 / -1 C 752 / +1 C 759`, +94.6% | iron condor `-1 P 708 / +1 P 701 / -1 C 738 / +1 C 745`, +178.5% | bear put spread `+1 P 723 / -1 P 708`, +215.5% | long call `+1 C 774`, +736.9% |
| TSLA | 2026-12-18 (30d) | bull call spread `+1 C 430 / -1 C 460`, +365.2% | bull call spread `+1 C 400 / -1 C 420`, +128.3% | iron condor `-1 P 375 / +1 P 355 / -1 C 400 / +1 C 420`, +86.8% | iron condor `-1 P 360 / +1 P 345 / -1 C 385 / +1 C 400`, +138.8% | bear put spread `+1 P 360 / -1 P 325`, +196.5% | long strangle `+1 P 335 / +1 C 440`, +254.2% |
| XLF | 2026-12-18 (30d) | long call `+1 C 60`, +1186.6% | bull call spread `+1 C 58 / -1 C 59`, +92.9% | iron condor `-1 P 56 / +1 P 54 / -1 C 58 / +1 C 60`, +50.8% | bear call spread `-1 C 57 / +1 C 58`, +51.2% | bear put spread `+1 P 56 / -1 P 53`, +176.8% | long strangle `+1 P 48 / +1 C 60`, +731.1% |

Fill: natural (long legs at the ask, short legs at the bid); target 35 days to expiry, using each underlying's expiry with a distribution nearest to it; calibration map `production`. Each cell is the structure kind with the highest return if right among those whose probability of profit given the outcome is at least 50%, its legs (signed quantity, right, strike) and its return if right: the expected profit and loss on max loss when the price at expiry lands in the outcome's range. The outcomes are quantile ranges of the calibrated distribution. This is a measurement of how each structure pays under each outcome, not advice; the same numbers are on the Structures tab (`/api/structures/map`).

## Top put credit spreads (2026-11-18)

| Rank | Underlying | Session | Expiration | DTE | Short/long | Mid credit | Natural credit | POP calibrated | POP risk-neutral | Expected return on max loss | Annualised return on max loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | NVDA | 2026-11-18 | 2026-12-02 | 14 | 149/146 | 1.62 | 0.55 | 60.7% | 53.7% | 36.52% | 334913.0% |
| 2 | AMD | 2026-11-18 | 2026-12-02 | 14 | 530/520 | 5.12 | 0.65 | 60.7% | 55.6% | 24.52% | 30293.4% |
| 3 | NVDA | 2026-11-18 | 2026-12-02 | 14 | 149/145 | 1.80 | 1.10 | 60.7% | 53.7% | 20.08% | 11713.7% |
| 4 | GOOGL | 2026-11-18 | 2026-12-02 | 14 | 275/265 | 3.53 | 1.85 | 76.1% | 70.8% | 19.79% | 10974.3% |
| 5 | META | 2026-11-18 | 2026-12-02 | 14 | 605/590 | 5.75 | 0.75 | 70.9% | 65.0% | 18.88% | 8975.0% |
| 6 | XLF | 2026-11-18 | 2027-01-15 | 58 | 56/55 | 0.74 | 0.22 | 55.6% | 49.5% | 101.94% | 8233.0% |
| 7 | AMD | 2026-11-18 | 2026-12-02 | 14 | 525/510 | 7.20 | 3.30 | 61.0% | 56.4% | 18.28% | 7864.8% |
| 8 | AMD | 2026-11-18 | 2026-12-02 | 14 | 525/515 | 4.83 | 0.65 | 60.8% | 56.0% | 17.69% | 6879.7% |
| 9 | NVDA | 2026-11-18 | 2026-12-02 | 14 | 149/142 | 2.73 | 1.85 | 69.8% | 62.8% | 17.25% | 6232.4% |
| 10 | AMD | 2026-11-18 | 2026-12-02 | 14 | 530/510 | 9.47 | 5.50 | 60.8% | 56.0% | 16.46% | 5216.6% |

Credits are dollars per share. POP is the probability the underlying settles above the breakeven; return on max loss is the expected return over the trade as a share of the maximum loss, which is the collateral held, annualised in the last column.

![Eligible spreads](img/spread_scores.png)

## Top spreads by edge (2026-11-18)

| Rank (edge) | Underlying | Expiration | Short/long | Mid credit | Natural credit | Fair credit | Edge | Edge (% of mid) | POP calibrated | POP risk-neutral | Price-implied POP | POP gap | Reward/risk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | SPY | 2026-12-18 | 585/550 | 0.36 | 0.34 | 0.07 | +0.29 | 81.0% | 99.7% | 98.6% | 99.0% | +0.7 pp | 0.21 |
| 2 | SPY | 2026-12-18 | 600/550 | 0.59 | 0.57 | 0.11 | +0.47 | 80.9% | 99.7% | 98.2% | 98.8% | +0.8 pp | 0.22 |
| 3 | DIA | 2026-12-18 | 425/375 | 0.48 | 0.28 | 0.09 | +0.38 | 80.5% | 99.7% | 98.4% | 99.0% | +0.7 pp | 0.20 |
| 4 | AAPL | 2026-12-18 | 290/265 | 0.32 | 0.26 | 0.07 | +0.26 | 79.6% | 99.4% | 97.9% | 98.7% | +0.7 pp | 0.23 |
| 5 | DIA | 2026-12-31 | 425/375 | 0.63 | 0.38 | 0.13 | +0.50 | 79.3% | 99.4% | 97.7% | 98.7% | +0.6 pp | 0.23 |

Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up. Price-implied POP is the maximum loss over the width, the probability of profit at which the price breaks even, and the POP gap is the calibrated POP minus it: the same information as the edge in probability units. Out of sample, predictions with a raw probability under 2% saw 71 breaches in 53,722, which is how thin the evidence for the far tail is.

## How to read this

Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on max loss is roughly the cash rate by construction, so any edge comes from the calibration map, which is an estimate of the variance risk premium: the gap between the probabilities the option market implies and the frequencies that followed. Across the 1,360 eligible spreads of the latest session the median annualised return is 1.3% under the risk-neutral CDF and 74.9% after calibration, against a cash rate of 3.6%.

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
