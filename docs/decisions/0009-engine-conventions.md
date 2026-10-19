# 0009. Engine conventions: APY rates, ACT/365 years, numpy only

Status: Accepted (Phase 3)
Date: 2026-10-19

## Context

The spread engine (`src/oap/engine/`) turns option mids into a distribution of the price at expiry and scores spreads on return on collateral. Its inputs come from three places that each have their own habits. The gold table `fct_option_quote` carries time to expiry as calendar days over 365. The cash rate the score uses is the figure a broker publishes: Robinhood Gold's 3.6% is an annual percentage yield. Textbook Black-Scholes uses a continuously compounded rate and a year of whatever length suits the author.

A unit mismatch here does not raise an error. It shifts a probability by a point or two, and a ranking built on those probabilities is wrong in a way no test on the code alone will show. The engine also runs inside the Airflow image, where every added dependency has to survive the lock-based install and the `pip check` gate (ADR 0006).

## Decision

One convention for the whole package, written in the docstring of `oap.engine` and repeated in every function that takes a quantity.

- **Rates are decimal annual percentage yields** (0.036 means 3.6% APY) at every public boundary: the risk-free rate in Black-Scholes and in the implied distribution, the cash rate in spread scoring. Growth over `years` is `(1 + rate) ** years` (`conventions.growth_factor`). The conversion to a continuous rate, `ln(1 + apy)` (`conventions.continuous_rate`), happens inside `black_scholes` only. A textbook continuous rate of 0.05 is passed as `math.expm1(0.05)`.
- **Time is in years on ACT/365**: calendar days between two dates divided by 365 (`conventions.dte_years`). This is the same definition as `dte_years` in `int_option_quotes` and `fct_option_quote`, so a value read from gold can be passed straight in.
- **Other units**: prices, strikes, credits and losses in dollars per share; volatility as a decimal (0.20 is 20%); probabilities as decimals in [0, 1]. Every docstring states the units of its arguments and return value.
- **Pure functions on numpy arrays.** No I/O, no clock, no global state, and no dependency beyond numpy. The normal CDF is `0.5 * erfc(-x / sqrt(2))` using `math.erfc`, and implied volatility is found by vectorised bisection on [1e-6, 10] to a width of 1e-12 within 200 iterations. An element whose price lies outside the no-arbitrage bounds, or whose volatility lies outside that range, comes back as nan, so one bad quote does not abort a chain.
- **Invalid input raises `EngineInputError`** (a `ValueError`), naming the argument. A bad quote inside an array is a value (nan or a quality flag), not an exception.

## Consequences

Good:

- There is one place where a rate changes form, and it is inside the module that needs the continuous form. Callers never convert.
- A time read from the warehouse and a time computed by the engine agree to the last digit.
- The engine adds no dependency to the image. Its 156 tests include a property test that a lognormal chain is recovered, and run in a few seconds with `hypothesis`.

Costs and risks:

- ACT/365 ignores weekends and holidays. A Friday expiry and a Monday expiry differ by the calendar, not by trading days, which is how interest accrues but not how variance accrues. The implied distribution is a statement about the price at expiry, so the choice does not enter it; a user who wants a volatility per trading day has to convert.
- APY at the boundary means a reader with a continuous rate must convert it. The docstring example says how.
- Bisection takes about 43 iterations per call where Newton takes a handful. For the size of one chain this is not a cost that matters; it would matter for millions of quotes in one call.
- `math.erfc` is applied element by element through `np.vectorize`. The function is correct but not fast.
- Numpy 2.x only. The Airflow base image ships numpy 1.26, so the engine depends on the lock-based install of ADR 0006.

## Alternatives considered

**Continuous rates at the boundary.** Rejected. The cash rate that matters is a quoted APY, and the gap between 3.6% APY and 3.54% continuous is small enough to pass unnoticed through a review. Choosing APY at every public boundary removes the conversion from callers; the one place that needs the continuous form does the conversion itself.

**scipy.** Rejected. The engine needs a normal CDF, a bracketing root finder and nothing else. scipy would be one more large compiled dependency to hold at the lock's version inside an image whose base pins numpy, and it would add to the `pip check` surface for two functions that take a few lines each.

**A trading-day year (252).** Rejected. Option expirations, the dbt `dte_years` column and interest accrual are all defined on calendar days. A 252-day year needs an exchange calendar in the engine, which would make it impure, and it gives a different `years` for the same pair of dates depending on how the holidays fall.

**A Newton solver for implied volatility.** Rejected. Newton's step divides by vega, which is near zero for deep in-the-money and far out-of-the-money options, so it needs a starting guess, a fallback and per-element convergence handling to vectorise. Bisection on a bracket always converges, and its failure modes (price outside the bounds) are detected before the loop starts.
