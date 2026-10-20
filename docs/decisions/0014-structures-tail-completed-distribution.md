# 0014. Structures: compare spreads and singles on a tail-completed distribution

Status: Accepted (Phase 3)
Date: 2026-10-19

## Context

The explorer's structure calculator ([design/structures.md](../design/structures.md)) answers one question for a ticker, a session and an expiration: given the outcome a reader expects for the price at expiry, which option structure serves it best, and when does a spread beat an outright call or put. Nine kinds are compared: long call and put, the four verticals, long straddle and strangle, and the iron condor.

`RiskNeutralCdf.prob_below` is flat outside its knots. The mass `F(k_0)` below the lowest knot and `1 - F(k_n)` above the highest is left undistributed, which is the honest choice for the put credit spread scoring of ADR 0013: a spread whose strikes are inside the knots pays the same amount everywhere beyond them, so where that mass sits does not matter. A long call is different. Its payoff keeps growing above the last quoted strike, and on the flat CDF that mass behaves as if it sat exactly at the last knot, which understates every structure with an unbounded payoff. Comparing a bull call spread with a long call on the flat CDF would build in a bias towards the spread.

The comparison also needs a metric that depends on the outcome. Unconditional expected return on max loss is the same number for every outcome, so it cannot say which structure serves "up, moderately" better than "big move". And an outcome written as a fixed percentage move means different things for a quiet ETF and a volatile single name.

## Decision

**Complete the tails with scaled lognormals.** `oap.engine.positions.TailCompletedCdf` keeps the base CDF (raw or calibrated) inside `[k_0, k_n]` and adds a lognormal tail on each side, centred on the forward (the calibrated median when the forward is unknown) and scaled to carry exactly the undistributed mass: above `k_n`, `1 - F(x) = m_hi * Q(x) / Q(k_n)` with `Q` the lognormal survival; below `k_0`, `F(x) = m_lo * L(x) / L(k_0)` with `L` its CDF. `F` is then continuous at both knots, monotone, `F(0) = 0` and `F(inf) = 1`, and a tail with no mass contributes nothing. Each tail's volatility is the source implied volatility of the outermost usable quote on its side: the lowest-strike usable put for the lower tail, the highest-strike usable call for the upper (`oap.analytics.views.tail_sigmas`, with fallbacks to the nearest usable quote and then to the expiration's median IV). The skew is therefore carried into the tails, and no new parameter is fitted. If a normaliser underflows, the tail becomes its limit, a point mass at the knot.

**Integrate exactly.** Profit and loss at expiry is piecewise linear in the price, with kinks at the strikes. On every segment between knots, kinks and outcome bounds it is affine. Inside the knots the density is constant, so Simpson's rule is exact for `pnl` and `pnl^2`. In a tail, the lognormal partial moments `M_n = integral of S^n dF` (`n = 0, 1, 2`) are closed form (`f Phi(d1)`, `f^2 e^(s^2) Phi(d1 + s)` and their lower-tail complements, written out in the module docstring). The engine scores many structures against one distribution as matrix operations over the union of the knots and every strike. The tests check these moments against dense quadrature to `1e-6` relative and reproduce `score_spread` to `1e-9` for a bull put spread.

**Compare on the conditional return.** The comparison metric is the **return if right**, `E[pnl | S in outcome] / max_loss`, alongside `P(profit | outcome)`, the return if wrong and the worst return inside the outcome. A structure qualifies when `P(profit | outcome)` reaches a threshold (0.5 by default). The best of each kind is the qualifying one with the highest return if right. The verdict compares the best spread (the four verticals and the condor) with the best outright long premium (the long call and put, and also the straddle and strangle when the outcome is a move). It explains the result in one sentence chosen by fixed rules from a fixed set of templates, none of which uses the words buy, sell, recommend or should.

**Outcomes are quantile ranges.** The six presets (`up`, `up_moderate`, `flat`, `down_moderate`, `down`, `big_move`) are quantiles of the calibrated, tail-completed distribution, so "up, moderately (55th to 85th)" carries 30% calibrated probability for every ticker. Custom outcomes are fractions of the close.

**Enumerate only quoted, fillable structures.** Every leg is a usable quote with its strike inside the knots, so no leg relies on the completed tail for its price. Fills are natural (the default: ask for long legs, bid for short) or mid. A debit structure with a non-positive debit, or a credit structure with a non-positive credit or a credit at or above its width, is a bad quote and is dropped. Each kind is capped at 400 structures, keeping those nearest the close.

## Consequences

Good:

- Bounded and unbounded payoffs are compared on one distribution that puts the mass outside the quotes somewhere plausible instead of on the last knot.
- For any structure whose strikes are inside the knots and whose payoff is flat beyond them (the four verticals and the condor), the expected profit and loss is identical to the flat CDF's, because each tail's mass meets one constant payoff either way. On the session of 2026-10-16 the API's bull put spreads on mid fills match `gold.spread_scores` to within `1e-12` in expected return, probability of profit and payoff standard deviation. The only difference from `expected_roc` is the interest on the collateral (0.27% of max loss over 28 days), which `expected_roc` includes and the calculator leaves out.
- Every response reports `tail_share`, the share of the expected profit and loss that comes from beyond the knots, and the tail volatilities and masses, so a reader can see how much an answer depends on the tail model.

Costs and risks:

- The singles' numbers depend on the tail model: the lognormal shape, the choice of the outermost quote's IV and the location. On liquid names the undistributed mass is small (NVDA's 2026-11-13 expiration: 0.13% below, 0.64% above), but on a thin chain it is not, and the tail shape then drives the long call's and long put's expected payoff. `tail_share` shows this; it is not a bound.
- For spreads `tail_share` is not a correction. A bull put spread's lower tail holds the max loss whatever the tail model, so `tail_share` is about 4% to 5% on the live NVDA and XLF spreads even though their expected profit and loss is model-free. It is defined as `|E1 tails| / (|E1 tails| + |E1 inside|)` so that it stays in `[0, 1]`.
- Mid fills on a wide quote can produce a credit spread whose credit nearly equals its width: on 2026-10-16 the XLF 59/57.5 put spread has a mid credit of 1.48 on a 1.50 width, a max loss of 0.02 and a return if right of about 10x, and it tops the mid-fill comparison for `up_moderate`. The natural fill, which is the default, does not produce it. The calculator does not filter it, because a floor on max loss would be one more parameter with no basis in the distribution.
- The calibrated CDF is a staircase. The production map comes from isotonic regression, so it is piecewise flat in probability, and composing it with a CDF gives several hundred knots: flat runs, and jumps between knots a few millionths of a dollar apart. Expectations integrate it exactly, but its point density is about 0 or a spike. On 2026-10-16 NVDA's density at the middle of the grid was 7e-13 and its largest value sat at the first grid price. The response therefore draws the grid and the density from the calibrated CDF evaluated at the raw knots (`TailCompletedCdf.coarsened`), which is the landscape's `density_calibrated` with the same tails. Some raw-knot intervals still hold no calibrated mass where the map is flat (63 of SPY's 161 grid cells for `flat` that day), and the Landscape page shows the same gaps.
- The per-kind cap keeps structures nearest the close. On a dense chain (SPY at $1 strikes) that excludes wide or far out-of-the-money verticals and condors; on the current DoltHub chains (20 to 26 strikes per side) it never binds.
- `P(profit | outcome)` thresholds and the return-if-right metric favour narrow, cheap structures whose whole payoff lies inside the outcome. That is the question asked, and the verdict sentence states the numbers rather than a preference.

## Alternatives considered

- **Flat CDF for every structure.** Rejected: it biases the comparison towards spreads by holding the unbounded payoff at the last knot.
- **Extrapolate the CDF linearly or with a Pareto tail.** Linear extrapolation needs a cut-off and has no basis. A power tail fits the far tail better but needs an index per side, which the chain cannot pin down from one or two quotes. The lognormal with the outermost IV adds no fitted parameter and is the distribution the quotes themselves are priced with.
- **Rank by unconditional expected return or by annualised return.** Rejected as the comparison metric: neither depends on the outcome. Both are still reported per structure.
- **Fixed percentage moves for the presets.** Rejected: plus 5% is a big move for XLF and a quiet month for NVDA. Quantiles mean the same thing for every ticker.
