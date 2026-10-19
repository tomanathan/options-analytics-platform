# 0013. Edge and risk-adjusted ranking: definitions and what they do not mean

Status: Accepted (Phase 3)
Date: 2026-10-19

## Context

`spread_scores` ranks the put credit spreads of the latest session by calibrated annualised return on max loss (ADR 0010). That number mixes two things: how rich the credit is against the calibrated distribution, and how long the trade lasts, because annualising a 14-day return multiplies it by about 26. A reader who asks "which spread pays the most for the risk" cannot read either off the table. The explorer and the report need three further views of the same scores: the credit against what the distribution says it should be, the same gap in probability units, and the expected payoff against its spread.

Two facts about the data shape what those views may claim. The calibration map is one pooled map for every underlying and expiry, fitted on a hindsight universe of today's large caps (ADR 0010), and it is in-sample for the latest session. And the far tail, where the largest gaps sit, is where the map rests on the fewest events.

## Decision

**Definitions.** All per share, in dollars, undiscounted, for a spread with short strike `K`, long strike `L`, width `W = K - L` and mid credit `c`. `F` is the CDF of the price at expiry, raw or recomposed with the production map.

- `fair_credit` is the expected payout of the long put spread that offsets the short one, `E[h]` with `h(S) = min(max(K - S, 0), W)`, which is the integral of `F` from `L` to `K` and the existing `expected_payoff_put_spread`. It lies in `[0, W]`.
- `edge` is `c - fair_credit`. It is the existing `expected_payoff`, bit for bit, and `edge_raw` is the same under the raw CDF. `edge_natural` is the natural credit minus the calibrated fair credit, and shows whether the gap survives a fill at the price that can be traded. `edge_pct` is `edge / c`, at most 1. `edge_pop` is the calibrated minus the raw probability of profit.
- `payoff_std` is the standard deviation of `h`. Interest on the collateral is deterministic, so it is also the standard deviation of the seller's profit and loss. Since `h` lies in `[0, W]` it is at most `W / 2`. `reward_to_risk` is `edge / payoff_std` per trade, not annualised; it is an excess-over-cash Sharpe ratio, because interest is the risk-free leg. It is null when the standard deviation is 0 (at or below `1e-9 * W`).
- `pop_implied` is `max_loss / width`, the probability of profit the price implies under the binary approximation. The credit and the max loss are the odds, so the breakeven probability is `max_loss / (max_loss + credit) = 1 - c / W`. `pop_gap` is the calibrated probability of profit minus it, and `pop_gap_raw` is the same under the risk-neutral CDF, which serves as the control. `pop_gap` is the same information as `edge_pct` in probability units: a positive value means the market pays more than the calibrated probability justifies. It is not an independent signal, and it is not equal to `edge_pct` because the binary approximation ignores the partial-loss region between the long strike and the breakeven.

**The Simpson derivation.** For any non-increasing `phi` with `phi(inf) = 0`, `phi(S)` is the integral of `-phi'(x)` from `S` to infinity, so by Tonelli `E[phi(S)]` is the integral of `-phi'(x) F(x)`. The CDF is flat outside its knots, which puts all the mass below the lowest knot at the left of every price and all the mass above the highest knot at the right. The left atom pays `W` and the right atom pays 0, so no tail term is needed. `phi = h` gives `E[h]` as the integral of `F` over `[L, K]`. `phi = h^2` gives `E[h^2]` as the integral of `2 (K - x) F(x)` over `[L, K]`. `F` is affine between knots, so on the grid made of both strikes and the knots strictly between them the integrand is quadratic on every segment and Simpson's rule is exact. The variance is `max(0, E[h^2] - E[h]^2)`, clamped because of cancellation. The worked example in `oap.engine.spread_scoring` (100/95 spread, credit 2.00, hand-built CDF) gives `E[h] = 2.0625`, `E[h^2] = 445/48`, a standard deviation of 2.2398498 and a reward to risk of -0.0279037.

**Ranks.** `rank` is unchanged and `return` stays the default order everywhere. `rank_edge` and `rank_rr` order one candidate set by `edge_pct` and by reward to risk (null last). The set is the eligible spreads with `credit >= 0.25` and `credit_natural >= 0.5 * credit` (`min_edge_credit` and `min_natural_fraction` in `AnalyticsConfig`). `rank_entry` is the "Top to enter" ranking: the candidates that also have a calibrated probability of profit of at least 0.65 (`entry_min_pop`), a positive natural edge, a long strike inside the quoted strikes and none of the `left_tail_uncovered`, `right_tail_uncovered`, `sparse` or `forward_unknown` flags, ordered by annualised return on max loss, then reward to risk. The rule is one sentence in the code (`oap.analytics.scoring.ENTRY_RULE`) and the API and the report print that sentence, so a reader sees what produced the order. The API orders rows by `sort` (`return`, `edge`, `reward_to_risk`, `kelly`, `pop`, `pop_gap` or `entry`) with nulls last and a stable sort.

**Reading.** Edge is the market mid credit against the expected payout under one pooled map. It is the historical variance risk premium applied to this chain, plus whatever the mid holds above the natural price. It is not a contract-specific mispricing. It is correlated across the strikes and expiries of one underlying, because one map is applied to one smile. The copy in the UI and the report says "credit above or below calibrated fair credit" and avoids buying, selling and recommending words.

**Evidence that the extreme edges are the thin ones.** Measured on the session of 2026-10-16 (4,405 spreads, 1,459 eligible) and reproduced when this change was built:

| Quantity | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| `edge_pct`, calibrated, eligible | 0.143 | 0.183 | 0.211 | 0.255 | 0.389 | 0.752 | 0.835 |

- The raw edge is about 0: slightly negative, because the fair credit is undiscounted and the CDF is interpolated between knots.
- All of the top 12 rows by `edge_pct` have a short strike 0.79 to 0.90 of the close and a calibrated probability of profit of at least 0.997, against about 0.985 raw. The production map sends a raw `F` of 0.0113 to 0.0013.
- Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,508, so that part of the map rests on a few dozen events. The report prints this count from the database.
- A credit floor does not change it: `credit >= 0.25` with `natural >= 0.5 * credit` leaves the top of the edge list the same, and 1,265 of the 1,459 eligible spreads pass the guards. The reward to risk ordering differs (Spearman correlation with `edge_pct` about 0.45 across the eligible spreads).
- `credit_natural - fair_credit > 0` holds for 77.9% of eligible rows.

**Why `return` stays the default.** Ordering by edge puts deep out-of-the-money spreads with a calibrated probability of profit near 1 first, which is exactly where the map has the fewest events and survivorship bias is largest. The annualised return order has its own faults (the annualisation), but it does not make the thinnest part of the map the headline. The alternative views are one click away and carry the caveat above.

## Consequences

Good:

- The columns are computed from the same CDF as `expected_payoff`, so edge is exact, not a numerical integral, and `expected_payoff` is bit-identical to what it was (scale-invariance tests pass unchanged, and a recompute of all 4,405 live rows matches `credit - expected_payoff_put_spread` exactly).
- One definition of the entry rule serves the table, the API and the report.
- dbt tests pin the identities that must hold (`edge = expected_payoff`, `fair_credit + edge = credit`, `edge_pct <= 1`, `payoff_std <= width / 2`, `0 <= pop_implied <= 1`) and the contiguity of the three new ranks.

Costs and risks:

- A gold file built before this change lacks the columns, so `/api/spreads` answers `503 gold_missing` until `make dbt-build-local` is run (runbook). A `make pull-gold` artifact older than the merge has the same problem.
- Edge and the probability gap rank the far tail first. The mitigation is the default order, the guards, the copy and the printed evidence, not a statistic. A reader who ignores the caveat can still read an edge as mispricing.
- `reward_to_risk` is per trade and mixes 14 to 63 days to expiry. It is not comparable with an annualised figure.
- The binary approximation behind `pop_implied` ignores partial losses, so `pop_gap_raw` is not exactly 0; on the live session its median magnitude over the eligible spreads is about 3 points and its largest is 31 points. The raw gap is a control for the size of that effect, not a bound.

## Alternatives considered

- **Integrate `E[h^2]` on a grid.** Rejected: the exact Simpson evaluation is no more code and has no discretisation error to explain or test around.
- **Rank on the natural edge by default.** Rejected as the default, since it makes the order depend on a half-spread that is a property of liquidity, not of the distribution. It is shown beside the mid edge instead (`edge_natural`) and gates `rank_entry`.
- **Annualise the reward to risk.** Rejected. Annualising multiplies a noisy per-trade ratio by the square root of the number of trades per year, which differs between a 14-day and a 63-day expiry in a way unrelated to the quality of the trade. Per trade is the honest unit; it is labelled so.
- **A buy or sell signal, or a mispricing flag.** Rejected: the map is a pooled historical average, so the claim would be stronger than the evidence.
