{% docs calibration_snapshot %}
One row per chain snapshot: an underlying, a trade date and an expiration, with the number of
usable puts and calls (a positive bid and an ask at or above the bid), the settlement from
`fct_expiration_outcome` and a `status`. `status` is `ok` when the snapshot can enter the
calibration sample, otherwise the first rule that failed, in this order: `ticker_reused` (before the
ticker's valid-from date), `too_short` (fewer than 7 days to expiration), `no_close`,
`too_few_puts` (fewer than 4 usable puts), `unsettled`, and `split_in_window` (a daily move beyond
0.4 in log terms between the trade date and settlement, which the unadjusted closes would read as
a crash). The exclusions are counted, never silently dropped. This is a Python model over the pure
`oap.analytics` package and runs on DuckDB only; Phase 4 will run it as a Snowpark Python model.
{% enddocs %}

{% docs calibration_prediction %}
The calibration sample before any calibration. For each `ok` snapshot the model builds the
risk-neutral CDF of the underlying at expiration from the put quotes (calls add parity forwards),
reads P(S_T < K) at 13 strikes on a moneyness grid from 0.80 to 1.10 of the close, and records
whether the settlement close was strictly below each strike. Targets outside the strike range of
the CDF are skipped, so nothing here is extrapolated. Grain: underlying x trade date x expiration x
moneyness. Probabilities are in [0, 1], prices in dollars, time in years.
{% enddocs %}

{% docs calibration_map %}
The isotonic calibration maps, one row per knot. `fold_<year>` is the map applied to predictions
traded in that year, fitted only on predictions whose expiration is before 1 January of that year
(outcomes known at the start of the fold); `production` is fitted on every settled prediction and
scores the latest session. A map fitted on fewer than 50 predictions is the identity map
(`is_identity`). Maps are stored compacted: only the knots that change the interpolated curve are
kept, so the production map holds hundreds of knots rather than one per prediction.
{% enddocs %}

{% docs calibration_sample %}
The backtest sample: every prediction with its fold map applied. `is_out_of_sample` is true when the
fold is a test year (2021 onward) and its map is not the identity, which is the set the metrics and
the reliability table use. The first fold (2020) is burn-in. The walk-forward scheme cannot leak
because a fold map's training expirations all precede the first trade date it is applied to; the
singular test `assert_calibration_out_of_sample` checks this in SQL.
{% enddocs %}

{% docs calibration_metrics %}
Out-of-sample forecast quality of the raw risk-neutral probabilities against the calibrated ones:
Brier score, log loss (nats) and expected calibration error, overall and by underlying, DTE bucket
and fold year. The overall Brier rows carry a 95% bootstrap interval that resamples expiration
dates, because predictions that resolve on the same day share one market move and are not
independent. `variant = delta` is calibrated minus raw, negative when calibration helps. Empty when
there is no out-of-sample row yet.
{% enddocs %}

{% docs calibration_bins %}
Reliability table over the out-of-sample rows: ten equal-width probability bins per variant (raw
and calibrated) with the number of predictions, the mean predicted probability and the share of
events that occurred. A calibrated forecast lies on the diagonal. Empty when there is no
out-of-sample row yet.
{% enddocs %}

{% docs spread_scores %}
Put credit spreads of the latest session in gold (the global maximum trade date, so an underlying whose feed stopped is not ranked beside fresh ones), scored twice: under the risk-neutral CDF
(`*_raw` columns) and under the CDF passed through the production calibration map. One row per
(underlying, expiration, short strike, long strike) with the mid `credit`, the `credit_natural`
(sold at the bid, bought at the ask), probabilities, expected and annualised return on max loss
(collateral equals max loss; the columns are `expected_roc` and `annualised_roc`) and the Kelly fraction. `eligible` marks spreads that are not extrapolated, have a positive natural
credit, a short strike below the close and `prob_profit` at or above 0.5; `rank` orders the eligible
ones by calibrated annualised return. Under the risk-neutral CDF built from the same mids the
expected return is roughly the cash rate by construction, so any edge comes from the calibration
map. Prices are dollars per share, rates are annual decimals, time is in years.

`fair_credit` is the expected payout of the long put spread under the CDF, `edge` is the mid
`credit` minus it (equal to `expected_payoff`), `edge_pct` is that as a share of the mid credit,
`payoff_std` is the standard deviation of the payoff and `reward_to_risk` is `edge` divided by it
per trade. `pop_implied` is `max_loss / width`, the probability of profit the price implies, and
`pop_gap` is the calibrated probability of profit minus it, the same information as `edge_pct` in
probability units (`pop_gap_raw` is the control). `rank_edge`, `rank_rr` and `rank_entry` order a
guarded subset of the eligible spreads. The honest reading: edge is the market mid credit against
the expected payout under one pooled calibration map, so it is the historical variance risk
premium applied to this chain plus whatever the mid holds above the natural price. It is not
contract-specific mispricing, it is correlated across the strikes and expiries of one underlying,
the map is in-sample for the latest session and built from a hindsight universe, and the largest
edges sit in the far tail where the map rests on the fewest breaches.
{% enddocs %}
