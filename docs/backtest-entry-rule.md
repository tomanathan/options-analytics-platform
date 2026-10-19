# Strategy backtest: the Top 10 rule applied historically

`entry_top10` takes, on every session, the spreads the live ranking would have listed under "Top 10 to enter": Passes every guard (eligible, calibrated POP ≥ 65%, credit ≥ $0.25, natural credit ≥ 50% of mid with positive natural edge, inside quoted strikes, no tail flags), ranked by annualised return on max loss, then reward/risk. Each session is scored by the same code as the latest one, with only the calibration map that existed at the time.

Sessions scored: 1,047 (2021-01-04 to 2026-10-05); with at least one `entry_top10` trade: 1,047. Trades dropped as unsettled: 0. Out-of-sample trades: `entry_top10` 10,458, `return_top10` 10,470, `eligible_all` 919,631.

## Out of sample, overall

`entry_top10` is the recommendation: `rank_entry` (the rule above); `return_top10` is the top 10 by `rank` (raw annualised return on max loss, without the entry guards); `eligible_all` is every eligible spread, equal weight (the no-selection baseline).

| Strategy | Trades | Sessions | Win rate (95% CI) | Predicted POP | POP gap | Mean realised return (95% CI) | Mean predicted return | Total return on capital at risk | Median return | Worst trade | Max-loss rate | Sharpe per trade | Max drawdown ($1/trade) | Max drawdown ($1/session) | Avg DTE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `entry_top10` | 10,458 | 1,047 | 64.1% (61.2% to 67.8%) | 73.0% | -8.9 pp | -1.8% (-6.0% to 3.3%) | 16.08% | -2.04% | 38.89% | -100.0% | 26.8% | -0.03 | 467.70 | 46.77 | 14.4 |
| `return_top10` | 10,470 | 1,047 | 62.5% (59.0% to 65.3%) | 70.3% | -7.8 pp | -5.1% (-10.0% to -0.7%) | 24.94% | -5.91% | 28.21% | -100.0% | 29.8% | -0.07 | 642.45 | 64.25 | 15.5 |
| `eligible_all` | 919,631 | 1,047 | 82.8% (80.5% to 84.7%) | 85.6% | -2.7 pp | 0.5% (-2.0% to 2.5%) | 6.47% | -0.43% | 6.89% | -100.0% | 9.3% | 0.01 | 19457.08 | 23.76 | 32.5 |

Returns are on max loss over the holding period. The realised return fills at the natural credit; the predicted return is the score's `expected_roc` (mid credit, interest on the collateral included), so part of the gap is the half-spread and the interest. The interval resamples expiration dates (trades expiring together share one market move). Drawdowns are in dollars per dollar of maximum loss, booked by session: $1/trade puts one dollar of maximum loss on every trade, $1/session splits one dollar equally across a session's trades, which puts strategies with different trade counts on one scale.

## By year (`entry_top10`)

| Year | Trades | Sessions | Win rate | Predicted POP | POP gap | Mean realised return | Mean predicted return | Total return on capital at risk | Max-loss rate | Max drawdown ($1/trade) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2021 | 1,480 | 148 | 66.8% | 80.7% | -13.9 pp | 2.25% | 29.94% | -0.73% | 24.2% | 103.69 |
| 2022 | 1,440 | 144 | 46.1% | 77.9% | -31.8 pp | -27.52% | 30.26% | -26.32% | 47.7% | 407.10 |
| 2023 | 1,460 | 146 | 75.8% | 69.1% | +6.7 pp | 12.84% | 5.65% | 10.57% | 15.5% | 61.62 |
| 2024 | 1,740 | 174 | 69.1% | 71.6% | -2.4 pp | 3.64% | 9.87% | 9.48% | 21.3% | 104.00 |
| 2025 | 2,478 | 249 | 62.5% | 70.9% | -8.4 pp | -1.94% | 12.94% | -5.05% | 27.8% | 268.58 |
| 2026 | 1,860 | 186 | 64.4% | 70.4% | -6.1 pp | -1.69% | 12.27% | 0.81% | 25.6% | 177.47 |

## By underlying (`entry_top10`)

| Underlying | Trades | Sessions | Win rate | Predicted POP | POP gap | Mean realised return | Mean predicted return | Total return on capital at risk | Max-loss rate | Max drawdown ($1/trade) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 522 | 394 | 66.7% | 73.7% | -7.1 pp | 0.48% | 17.13% | 3.51% | 25.7% | 30.45 |
| AMD | 2,337 | 865 | 63.9% | 72.9% | -9.0 pp | -0.97% | 16.58% | 4.11% | 26.4% | 158.49 |
| AMZN | 869 | 552 | 61.2% | 72.5% | -11.3 pp | -5.22% | 15.67% | -6.18% | 28.0% | 74.58 |
| DIA | 92 | 87 | 66.3% | 74.5% | -8.2 pp | -5.04% | 15.07% | -5.34% | 28.3% | 12.15 |
| GOOGL | 741 | 450 | 63.7% | 74.0% | -10.3 pp | -3.30% | 16.32% | -2.13% | 22.7% | 46.15 |
| META | 857 | 477 | 61.3% | 71.1% | -9.8 pp | -5.44% | 13.06% | -6.96% | 29.2% | 82.38 |
| MSFT | 387 | 307 | 68.5% | 73.5% | -5.1 pp | 0.62% | 16.05% | 5.51% | 23.0% | 24.37 |
| NVDA | 1,838 | 785 | 68.4% | 73.4% | -5.0 pp | 3.46% | 16.48% | 10.88% | 24.6% | 109.39 |
| SPY | 166 | 125 | 68.7% | 74.5% | -5.8 pp | 4.58% | 13.33% | 8.05% | 20.5% | 14.91 |
| TSLA | 2,598 | 824 | 61.7% | 72.8% | -11.1 pp | -4.70% | 16.35% | -9.15% | 30.3% | 196.71 |
| XLF | 51 | 38 | 72.5% | 81.4% | -8.9 pp | -3.17% | 20.37% | 2.67% | 17.6% | 8.04 |

## Worst 10 trades (`entry_top10`, out of sample)

| Session | Underlying | Expiration | Short/long | Natural credit | POP calibrated | Settlement close | Payoff | Realised return |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2021-01-04 | AMD | 2021-01-15 | 90.5/88.5 | 0.69 | 83.4% | 88.21 | -1.31 | -100.0% |
| 2021-01-04 | AMZN | 2021-01-15 | 3185/3125 | 22.65 | 74.5% | 3104.25 | -37.35 | -100.0% |
| 2021-01-08 | TSLA | 2021-01-22 | 880/860 | 9.40 | 66.8% | 846.64 | -10.60 | -100.0% |
| 2021-01-11 | AMD | 2021-01-22 | 95.5/93.5 | 0.77 | 74.5% | 92.79 | -1.23 | -100.0% |
| 2021-01-11 | AMD | 2021-01-22 | 97/93.5 | 1.49 | 74.5% | 92.79 | -2.01 | -100.0% |
| 2021-01-11 | AMD | 2021-01-22 | 97/95.5 | 0.66 | 69.5% | 92.79 | -0.84 | -100.0% |
| 2021-01-13 | AMD | 2021-01-29 | 88/86.5 | 0.52 | 83.4% | 85.64 | -0.98 | -100.0% |
| 2021-01-13 | AMD | 2021-01-29 | 90/86.5 | 1.38 | 74.5% | 85.64 | -2.12 | -100.0% |
| 2021-01-13 | AMD | 2021-01-29 | 90/88 | 0.80 | 74.5% | 85.64 | -1.20 | -100.0% |
| 2021-01-13 | NVDA | 2021-01-29 | 530/520 | 3.40 | 83.4% | 519.59 | -6.60 | -100.0% |

![Cumulative realised return](img/strategy_equity.png)

Cumulative realised return on max loss of the out-of-sample trades, one dollar of maximum loss per session split across its trades; the shading is the drawdown of `entry_top10` below its running peak.

## Caveats

Fills are at the natural credit (short bid minus long ask) at the end-of-day close, with no commissions, no slippage beyond that, no early management and no early assignment: every spread is held to expiry and settled at the settlement close. Positions overlap (a new set of spreads is entered every session while earlier ones are still open), and each trade is counted as one dollar of maximum loss, so the totals are not a compounded account balance. Each session uses the walk-forward map of its year, fitted only on expirations before 1 January; sessions before 2021 are burn-in and excluded, and the production map is never used. Only snapshots the calibration sample keeps (`ok` status) are ranked, so a chain whose window contains a split is left out, which uses hindsight about the split. The universe is today's large caps (hindsight in the universe biases realised losses low), the vendor history misses some sessions, and the eligible-all baseline is a measurement, not a tradeable portfolio. This is a historical measurement of a ranking, not trade advice.
