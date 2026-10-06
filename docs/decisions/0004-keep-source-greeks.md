# 0004. Keep vendor implied volatility and greeks in bronze

Status: Accepted (Phase 1)
Date: 2026-10-05

## Context

Both sources deliver implied volatility and greeks with each contract: DoltHub provides `vol` (implied volatility), delta, gamma, theta, vega and rho; Alpaca's snapshot provides greeks and implied volatility alongside its quotes. Phase 3 will compute its own implied volatility and greeks from prices, with pure functions in `src/oap/engine/` whose inputs are in dollars, decimal volatility and years. It is fair to ask whether bronze should carry numbers the project will replace.

Bronze is the layer that holds the vendor response as received. Its value is that any later layer can be rebuilt from it, and that a reader can tell what the vendor said as opposed to what we derived.

## Decision

Keep `iv`, `delta`, `gamma`, `theta`, `vega` and `rho` in `bronze.option_chain` exactly as the vendor supplied them, null where the vendor did not supply them. Do not recompute or adjust them at ingest.

Reasons:

- Bronze is "as received". Dropping columns the vendor sent would make bronze a filtered view of the vendor response, and a later need for them could not be met without re-fetching.
- They let us validate our own model. Once Phase 3 computes implied volatility and greeks, the vendor values are the cross-check: large disagreement points to a bug in our pricing code, a different rate or dividend assumption, or a vendor error.
- For history, they are the only greeks available. DoltHub carries neither last price, volume nor underlying price, so a model computed from DoltHub bronze alone has to use mid quotes and an underlying price from elsewhere. The vendor greeks are the only record of what the market data said on those days.

Cost: the warehouse will contain two definitions of delta (and of the others): the vendor's and ours. They differ in model, inputs and conventions. Silver must name them `source_delta` and `model_delta` (likewise for the other greeks and `source_iv` / `model_iv`) and never a bare `delta`, so no query can confuse them.

## Consequences

- Bronze rows are wider than the engine needs. The storage cost is small next to the quotes.
- Vendor greeks are not guaranteed consistent across sources or time: DoltHub's and Alpaca's definitions and conventions may differ (for example the unit of theta). Nothing in bronze reconciles them; a comparison belongs in Phase 2 and Phase 3, with the `source` column as the join key.
- Alpaca's quotes are `indicative`-feed quotes derived from OPRA, and the greeks attached to them inherit that. Treat them as indicative, not as a reference.
- The engine does not read vendor greeks as inputs. It reads prices and computes its own.

## Alternatives considered

**Drop the vendor greeks and IV at ingest.** Smaller bronze and no ambiguity about which delta is meant. Rejected because it loses the only greeks for the DoltHub history, removes the check on our own model, and breaks the "as received" rule. A column that is costly to confuse is better solved by naming in silver than by deleting the data.

**Recompute IV and greeks at ingest.** Rejected. It mixes numerical modelling into I/O code, which violates the rule that engine math is pure functions with no I/O, and it would overwrite what the vendor said with what we think. It would also need an underlying price and a rate for DoltHub days, which bronze does not have, so the recomputation could not be done faithfully at that layer.
