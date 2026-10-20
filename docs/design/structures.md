# Structures: which option structure serves an outcome

Status: specification for the `feat/structures-api` and `feat/structures-web` branches. Written against the code on `main` at `c6bfb76`.

## Goal

The explorer becomes a calculator that answers one question for a ticker, a session and an expiration: **given the outcome you expect for the underlying at expiry, which structure serves that outcome best, and when does a spread beat an outright call or put?** A second page shows the same answer across every ticker at once, so the landscape of tickers can be studied for the outcomes where spreads win.

Every number is a measurement under the calibrated distribution already built by the engine (ADR 0013). The page describes which structure *serves* an outcome; it never recommends a trade, and the wording tests of the explorer (no "buy", "sell", "recommend") stay in force.

## Vocabulary

- **Structure**: a position of one to four option legs on one expiration with a finite maximum loss. Kinds, with their direction:

  | `kind` | Legs (per share) | Direction | Premium |
  | --- | --- | --- | --- |
  | `long_call` | +1 call K | up | debit |
  | `long_put` | +1 put K | down | debit |
  | `bull_call_spread` | +1 call K1, −1 call K2, K1 < K2 | up | debit |
  | `bear_put_spread` | +1 put K2, −1 put K1, K1 < K2 | down | debit |
  | `bull_put_spread` | −1 put K2, +1 put K1, K1 < K2 | up | credit |
  | `bear_call_spread` | −1 call K1, +1 call K2, K1 < K2 | down | credit |
  | `long_straddle` | +1 call K, +1 put K | move | debit |
  | `long_strangle` | +1 put K1, +1 call K2, K1 < K2 | move | debit |
  | `iron_condor` | −1 put Kp2, +1 put Kp1, −1 call Kc1, +1 call Kc2, Kp1 < Kp2 < Kc1 < Kc2 | range | credit |

  `bull_put_spread` is the put credit spread the rest of the project scores; its numbers here must agree with `score_spread` for the same fill (see tests).
- **Fill**: `natural` (buy at the ask, sell at the bid; the default) or `mid`.
- **Max loss**: the largest loss per share at expiry, always finite for these kinds. Capital at risk equals max loss. **Return on risk** of a profit-and-loss amount is that amount divided by max loss.
- **Outcome (view)**: a set of terminal prices. Either one interval `[lo, hi)` of the price at expiry, or its complement (`outside = true`, used for "big move"). Bounds may be open (`lo = null` means no lower bound).
- **If right / if wrong**: expectations conditional on the terminal price landing inside / outside the view, under the calibrated distribution.

## Engine: `src/oap/engine/positions.py` (pure numpy, no I/O)

### Legs and positions

```python
@dataclass(frozen=True)
class Leg:
    right: Literal["C", "P"]
    strike: float  # $/sh, > 0
    quantity: int  # +1 long, -1 short; |quantity| == 1 in this version
    price: float  # fill in $/sh, >= 0


@dataclass(frozen=True)
class Position:
    kind: StructureKind
    legs: tuple[Leg, ...]  # 1 to 4 legs, strikes validated per kind
    years: float  # ACT/365, > 0
```

Properties and methods on `Position` (all per share, undiscounted, dollars):

- `net_premium`: `sum(q * price)`; positive is a debit paid, negative a credit received.
- `pnl(s: ArrayLike) -> FloatArray`: profit and loss at expiry for terminal prices `s`: `sum(q * intrinsic(right, K, s)) - net_premium`.
- `kinks`: sorted distinct strikes.
- `slopes`: `(slope_left, slope_right)`, the P&L slope below the lowest and above the highest strike (−1, 0 or +1 for these kinds, up to the leg count).
- `max_loss`, `max_gain`: evaluated on the kinks and the two open ends; `max_gain` is `inf` when `slope_right > 0` or `slope_left < 0`. `EngineInputError` if `max_loss` is not finite and positive (a structure with no risk or unbounded risk is not a structure here).
- `breakevens`: terminal prices where P&L crosses zero, from the piecewise-linear segments (both open ends included when the slope there is non-zero), ascending, 0 to 4 values.
- `legs_text`: e.g. `"-1 P 250 / +1 P 245"`, used for `legs` strings in the API.

Validation per kind happens in a `make_<kind>(...)` constructor family or one `build(kind, strikes, prices)` with the strike orderings of the table above. Prices are what the caller passed; the engine does not know bids and asks.

### Tail-completed distribution

`RiskNeutralCdf.prob_below` is flat outside the knots: the mass `F(k_0)` below the first knot and `1 − F(k_n)` above the last one is left undistributed. A put credit spread never cares, but a long call's expected payoff does, so comparing spreads with singles on the flat CDF would understate every unbounded structure. The calculator therefore completes the tails.

```python
@dataclass(frozen=True)
class TailCompletedCdf:
    base: RiskNeutralCdf  # raw or calibrated
    sigma_lo: float  # decimal vol of the lower tail, > 0
    sigma_hi: float  # decimal vol of the upper tail, > 0
    location: float  # $/sh: base.forward, or base.quantile(0.5) when forward is nan
```

Semantics, with `t = base.years`, `f = location`, `m_lo = F(k_0)`, `m_hi = 1 − F(k_n)`, `Q_σ(x) = Φ(−d2_σ(x))` the lognormal survival with `d2_σ(x) = (ln(f / x) − σ² t / 2) / (σ √t)` and `L_σ(x) = 1 − Q_σ(x)`:

- Inside `[k_0, k_n]`: `F(x)` is the base CDF (piecewise linear).
- Above `k_n`: `1 − F(x) = m_hi · Q_σhi(x) / Q_σhi(k_n)`.
- Below `k_0`: `F(x) = m_lo · L_σlo(x) / L_σlo(k_0)`.

So `F` is continuous at both knots, monotone, `F(0) = 0`, `F(∞) = 1`. When a tail mass is zero the tail contributes nothing.

Methods:

- `prob_below(x)`, `prob_below_array(x)`, `prob_between(lo, hi)` with `lo`/`hi` optionally `None` (open). Monotone, in `[0, 1]`.
- `quantile(p)`: inverse, searching the knots first and inverting a tail analytically when `p` falls in a tail.
- `expect(position, lo=None, hi=None) -> tuple[float, float, float]`: returns `(P, E1, E2)` where `P = P(lo ≤ S < hi)`, `E1 = E[pnl(S) · 1{lo ≤ S < hi}]` and `E2 = E[pnl(S)² · 1{lo ≤ S < hi}]`. Exact:
  - Inside the knots the integration grid is the union of `lo`, `hi`, the knots and the position's kinks that fall in the range. On each segment the P&L is affine and the density is constant, so `∫ pnl · dF` and `∫ pnl² · dF` are polynomials of degree ≤ 2 in the integration variable and Simpson's rule is exact (and the mid-point rule for the degree-1 case; use Simpson for both).
  - In a tail the P&L is affine, `pnl(S) = a + b S`, so `E1` and `E2` reduce to the lognormal partial moments `M_n(a, b) = ∫_a^b S^n dF` for `n = 0, 1, 2`, scaled by `m / Q(k)` as above. With `d1 = d2 + σ√t`: `∫_x^∞ S dF_σ = f Φ(d1(x))`, `∫_x^∞ S² dF_σ = f² e^{σ² t} Φ(d1(x) + σ√t)`; the lower tail uses `1 − Φ(·)`. The agent must write these out in the docstring and test them against `numpy` quadrature on a dense grid (relative error ≤ 1e-6).
- `tail_mass() -> tuple[float, float]`: `(m_lo, m_hi)`.

### Scoring

```python
@dataclass(frozen=True)
class StructureScore:
    position: Position
    prob_profit: float  # P(pnl > 0), unconditional
    expected_pnl: float  # $/sh
    pnl_std: float  # $/sh
    expected_return: float  # expected_pnl / max_loss
    annualised_return: float  # _annualise(expected_return, years), same function as spread_scoring
    reward_to_risk: float  # expected_pnl / pnl_std, nan when std is 0
    prob_view: float  # P(S in view)
    prob_profit_given_view: float  # P(pnl > 0 | S in view); nan when prob_view == 0
    return_if_right: float  # E[pnl | S in view] / max_loss; nan when prob_view == 0
    return_if_wrong: float  # E[pnl | S not in view] / max_loss; nan when prob_view == 1
    worst_in_view: (
        float  # min over S in view of pnl(S) / max_loss (closed-form on kinks and bounds)
    )
    tail_share: float  # |E1 from the two tails| / (|E1| + 1e-12), in [0, 1]
```

`score_structure(position, dist: TailCompletedCdf, view: View) -> StructureScore`. `View` is a frozen dataclass `(lo: float | None, hi: float | None, outside: bool)` with `lo < hi` when both are set. The conditional probability of profit uses the breakevens: profit regions are the segments where P&L is positive, intersected with the view, measured with `prob_between`. `worst_in_view` evaluates the P&L on the kinks inside the view and at the bounds (and the open ends when the view is open: `−inf` becomes `pnl at the slope limit`, i.e. `−max_loss` when the slope points down, otherwise the bound value).

For `kind == bull_put_spread` with `view` over everything, `prob_profit`, `expected_pnl` (= credit − fair credit) and `pnl_std` must equal `score_spread(...)` on the same `RiskNeutralCdf` to 1e-9 when `sigma` tails carry no mass (test by passing a CDF whose outer knots hold 0 and 1), and `expected_pnl` must differ only by the tail terms otherwise.

### Enumeration: `src/oap/engine/structures.py`

```python
@dataclass(frozen=True)
class ChainSide:          # one right, strikes ascending, usable quotes only
    strikes: FloatArray
    bids: FloatArray
    asks: FloatArray

def enumerate_structures(
    calls: ChainSide, puts: ChainSide, *, close: float, years: float,
    knot_lo: float, knot_hi: float, fill: Fill, max_width_fraction: float = 0.10,
    strangle_max_moneyness: float = 0.15, max_per_kind: int = 400,
) -> list[Position]
```

Rules: every strike lies inside `[knot_lo, knot_hi]` (no extrapolated legs). Fill prices: long legs at the ask (`natural`) or mid, short legs at the bid or mid; a leg whose fill is 0 is skipped. Verticals use consecutive-or-wider strike pairs up to `max_width_fraction · close`. Straddles use every strike within ±10% of the close. Strangles use put strike < close < call strike, both within `strangle_max_moneyness` of the close. Iron condors combine a bull put spread with short strike below the close and a bear call spread with short strike above the close, equal widths, both wings within the width cap; if more than `max_per_kind` would result, keep the `max_per_kind` with short strikes nearest the close. Debit structures with `net_premium <= 0` and credit structures with `net_premium >= 0` are dropped (a free lunch is a bad quote). The function is pure; the chain side arrays come from the API layer.

### Best per kind, dominance, verdict (also in `structures.py`)

- `best_per_kind(scores, *, min_prob_profit_given_view=0.5) -> dict[StructureKind, StructureScore]`: for each kind, the score with the highest `return_if_right` among those with `prob_profit_given_view >= threshold` and finite `return_if_right`; a kind with no qualifying instance is absent. When a view is `outside` or two-sided the "if right" number still applies.
- `dominance(bests, grid) -> list[tuple[float, float, StructureKind]]`: for each grid price, the kind whose `pnl(S) / max_loss` is highest; merged into contiguous segments `(from, to, kind)`.
- `verdict(bests, view) -> Verdict`: `Verdict(best_kind, best_spread_kind | None, best_single_kind | None, spread_return_if_right, single_return_if_right, advantage, reason)` where spreads are the four verticals plus the condor and singles are the two longs (straddle and strangle count as singles for the "move" direction, since they are outright long premium). `advantage = spread_return_if_right − single_return_if_right` (nan when a side is missing). `reason` is one descriptive sentence chosen from a fixed set of templates by rules, filled with the numbers, e.g. "The view is bounded above at $K, so the long call's payoff beyond it is never collected and the bull call spread returns 2.2× on risk against 1.6×." or "The view is open above $K, so the long call's unbounded payoff outweighs the spread's cheaper entry: 3.1× against 2.4×." Templates must not contain the words buy, sell, recommend, should.

## Analytics: `src/oap/analytics/views.py`

Preset views are quantile-based so they mean the same thing for a quiet ETF and a volatile single name. `PRESETS: tuple[Preset, ...]` with `id`, `label`, `lo_q`, `hi_q`, `outside`:

| id | label | lo quantile | hi quantile | outside |
| --- | --- | ---: | ---: | --- |
| `up` | Up, above the 75th percentile | 0.75 | — | no |
| `up_moderate` | Up, moderately (55th to 85th) | 0.55 | 0.85 | no |
| `flat` | Flat (25th to 75th) | 0.25 | 0.75 | no |
| `down_moderate` | Down, moderately (15th to 45th) | 0.15 | 0.45 | no |
| `down` | Down, below the 25th percentile | — | 0.25 | no |
| `big_move` | Big move, outside the 10th to 90th | 0.10 | 0.90 | yes |

`resolve_preset(preset, dist: TailCompletedCdf) -> View` evaluates the quantiles on the calibrated, tail-completed distribution. `tail_sigmas(chain_frame) -> tuple[float, float]` picks the lower tail vol from the lowest-strike usable put with a positive `source_iv` and the upper from the highest-strike usable call with one, falling back to the nearest usable quote with a positive IV, then to the median positive IV of the expiration; raises `EngineInputError` when no positive IV exists (the API answers 422 `no_implied_vol`). `pick_expiration(expirations: Sequence[tuple[date, int]], target_dte: int, min_dte: int) -> date | None` returns the expiration whose DTE is nearest `target_dte` among those at or above `min_dte`.

## API

Router `src/oap/api/routers/structures.py`, prefix `/api/structures`, tag `structures`; pure helpers in `src/oap/api/structures.py` (frames in, response models out); store methods in `store.py` with caches keyed by `(sig, symbol, session, expiration, map_id, fill)` for scored structures (LRU 32) and `(sig, session, dte, map_id, fill)` for the map (LRU 4).

### `GET /api/structures/{symbol}/{session}` → `StructuresResponse`

Query: `expiration` (date, optional: default `pick_expiration(..., target_dte=35, min_dte=7)`), `preset` (one of the ids, optional), `lo`, `hi` (moneyness as a fraction of the close, optional, used when `preset` is absent; at least one required then), `outside` (bool, default false), `fill` (`natural` | `mid`, default `natural`), `map` (`MapChoice`, default `auto`), `min_pop_given` (float in [0, 1], default 0.5), `limit` (1–100, default 25). 404 when the symbol, session or expiration is unknown; 422 `view_required` when neither preset nor bounds are given, `view_invalid` when `lo >= hi`, `no_distribution` when the expiration has no curve (the reason from the landscape bundle is echoed), `no_implied_vol` as above.

```jsonc
{
  "symbol": "NVDA", "session": "2026-10-16", "expiration": "2026-11-20", "dte_days": 35, "years": 0.0959,
  "underlying_close": 181.2, "forward": 181.9, "fill": "natural",
  "map_id": "prod", "map_is_identity": false, "look_ahead": false,
  "tails": {"sigma_lo": 0.61, "sigma_hi": 0.42, "mass_lo": 0.012, "mass_hi": 0.009, "location": 181.9},
  "view": {"preset": "up_moderate", "lo": 186.5, "hi": 201.0, "outside": false,
           "lo_moneyness": 1.029, "hi_moneyness": 1.109,
           "prob": 0.30, "prob_market": 0.27},            // calibrated and raw risk-neutral
  "grid": [120.0, ...],                                   // terminal prices, 161 points from q0.5% to q99.5% of the calibrated distribution
  "density": [..],                                        // calibrated density at the grid, 1/$
  "kinds": [                                              // best per kind, every kind that qualifies, in table order above
    {"kind": "bull_call_spread", "direction": "up", "legs": "+1 C 185 / -1 C 195", "strikes": [185, 195],
     "net_premium": 3.10, "max_loss": 3.10, "max_gain": 6.90, "breakevens": [188.1],
     "prob_profit": 0.41, "expected_return": 0.08, "annualised_return": 1.23, "reward_to_risk": 0.05,
     "prob_profit_given_view": 0.93, "return_if_right": 1.74, "return_if_wrong": -0.62, "worst_in_view": -0.52,
     "pnl_std": 4.1, "tail_share": 0.0, "curve": [..]}    // pnl / max_loss at each grid price
  ],
  "ranking": [ ...StructureRow without curve, top `limit` by return_if_right among qualifying instances of every kind ],
  "dominance": [{"from": 120.0, "to": 171.5, "kind": "long_put"}, ...],
  "verdict": {"best_kind": "bull_call_spread", "spread_kind": "bull_call_spread", "single_kind": "long_call",
              "spread_return_if_right": 1.74, "single_return_if_right": 1.21, "advantage": 0.53,
              "reason": "The view is bounded above at $201.00, so the long call's payoff beyond it is never collected; the bull call spread returns 1.74x on risk against 1.21x."},
  "n_structures": 2140, "n_qualifying": 1312
}
```

`StructureRow` fields are exactly the keys of a `kinds` entry minus `curve`. `max_gain` is `null` when unbounded. Every float field has a `Field(description=...)` with units. Unknown enum values are rejected by pydantic.

### `GET /api/structures/map` → `OutcomeMapResponse`

Query: `session` (date or `latest`, default `latest`), `target_dte` (int 7–120, default 35), `fill`, `map`, `min_pop_given`. For every underlying with that session, the expiration from `pick_expiration`, and every preset: the verdict numbers.

```jsonc
{"session": "2026-10-16", "target_dte": 35, "fill": "natural", "map_id": "prod",
 "presets": [{"id": "up", "label": "Up, above the 75th percentile"}, ...],
 "rows": [{"symbol": "NVDA", "expiration": "2026-11-20", "dte_days": 35, "underlying_close": 181.2,
           "cells": [{"preset": "up", "lo": 190.1, "hi": null, "prob": 0.25, "prob_market": 0.22,
                      "best_kind": "long_call", "best_return_if_right": 2.9, "best_legs": "+1 C 190",
                      "spread_kind": "bull_call_spread", "spread_return_if_right": 2.1,
                      "single_kind": "long_call", "single_return_if_right": 2.9, "advantage": -0.8}, ...]},
          ...]}
```

A ticker whose session lacks a usable expiration is listed with `cells: []` and `unavailable_reason`.

### Contract and tooling

`make api-schema` regenerates `apps/web/openapi.json`; the API agent commits it in the first push so the web agent can generate `src/api/schema.ts`. `tests/api/test_openapi.py` keeps the drift check. Response models go in `models.py` next to the existing ones; the `kind`, `direction`, `fill` and `preset` literals are shared `Literal` aliases exported from `models.py`.

## Web: `apps/web`

Two routes join the nav: **Structures** (`/structures`) and **Outcome map** (`/outcomes`). Both use the existing shell, theme tokens, `Measured`, `DataTable`, `Select`, `SegmentedToggle`, `Chip`, `StatTile`, `ErrorState`/`EmptyState`, busy-retry queries, and the `format.ts` helpers. New files live under `routes/`, `charts/`, `components/`, `state/` beside their peers; every chart and hook gets a test like its neighbours.

### `/structures`

URL state (`state/useStructureParams.ts`, same style as `useLandscapeParams`): `symbol`, `session`, `expiration`, `preset | lo,hi,outside`, `fill`, `map`, `kind` (selected row), `minPop`.

Layout, top to bottom:

1. **Controls row**: underlying select, session select (latest first, from `/sessions`), expiration select (from `/distribution`; label `expiryLabel`; expirations without a curve disabled with the reason), fill toggle (Natural / Mid), map toggle (Auto / Raw), min P(profit | view) slider (0–0.9, step 0.05).
2. **Outcome row**: six preset chips (selected one filled) and a custom range: two number inputs in percent of the close (`lo %`, `hi %`, blank = open) and an "outside" switch. Choosing a preset fills the inputs with the resolved bounds (read-only until the user edits, which switches to custom). A sentence under the row states the resolved bounds in dollars and both probabilities: "Above $186.50 and below $201.00: 30.0% calibrated, 27.0% market-implied."
3. **Stat tiles**: close, forward, DTE, P(view) calibrated vs market with the difference in points, tail vols, structures scored / qualifying.
4. **`StructurePayoffChart`** (visx, full width, ~420 px): x terminal price over `grid`; y P&L per dollar of max loss (return on risk), clamped to [−1, max over kinds of the 95th-percentile curve value or 4, whichever is smaller, with an "off scale" marker when clipped). Faint calibrated density area under the lines (secondary axis, no ticks). The view region shaded; outside-views shade both sides. One line per kind in `kinds` (kind colours below), the selected kind thick and the others at 60% opacity; breakeven ticks on the zero line for the selected kind; the zero line and the close marked. Below the x-axis, a **dominance strip** 12 px tall coloured by the winning kind of each segment, with a legend. Tooltip on hover: terminal price, then every kind's return at that price sorted descending, winner first.
5. **`VerdictCard`**: headline "For this outcome, {best kind} serves best" with its legs and return if right; then the spread vs single line with both numbers and the `reason` sentence; the advantage shown as a signed multiple (e.g. "+0.53× for the spread"). When one side is missing, say which kinds did not qualify.
6. **`KindsTable`** (`DataTable`): one row per kind: kind (with its colour swatch and direction glyph ↑ ↓ ↔ ⇄), legs, premium (debit/credit, signed), max loss, max gain (∞ when null), breakevens, P(profit | view), **return if right**, return if wrong, worst in view, expected return, annualised, P(profit), reward/risk, tail share (chip "tail" when > 25%). Default sort by return if right. Clicking a row selects the kind (highlights its line, fills the detail panel).
7. **Detail panel** for the selected kind: legs as a small table (right, strike, side, fill), premium per contract (×100), max loss per contract, and the row's metrics as tiles. A collapsible **"All qualifying structures"** table shows `ranking` (top 25) with the same columns.

Kind colours (from the existing palette tokens; add them to `theme/` as `--kind-*`): singles in the warm family, verticals in the cool family, condor neutral, straddle/strangle violet. Lines must stay distinguishable with colour-vision deficiency (check pairs with the palette tool already used for the dataviz tokens).

### `/outcomes`

Controls: session (latest default), target DTE (number, 7–120, default 35), fill, map, min P(profit | view). A matrix: rows tickers (sorted by symbol), columns the six presets. Each cell shows the best kind's glyph and short name on top and its return if right below; the cell background encodes `advantage` on a diverging scale (cool when spreads win, warm when singles win, neutral near 0), with a legend. Hovering shows the full cell: bounds in dollars, both probabilities, spread and single kinds with their returns. Clicking navigates to `/structures?symbol=…&session=…&expiration=…&preset=…&fill=…&map=…`. A footer line states the session, DTE target, fill and map. Empty cells show the reason.

### Checks

`npm run check` green; new tests for `useStructureParams`, `StructurePayoffChart` (renders lines, strip and shading from a fixture), `VerdictCard` (wording and the missing-side case), `OutcomesPage` (matrix shape and link targets), `StructuresPage` (controls change the query key; preset → custom switch). Largest chunk stays under 250 KB gzip.

## Docs and repo

- This file is the spec. ADR 0014 `docs/decisions/0014-structures-tail-completed-distribution.md` records: comparing bounded and unbounded structures requires completing the tails; lognormal tails with the outermost quoted vols, scaled to the undistributed mass and continuous at the knots; conditional "if right" returns as the comparison metric; quantile presets instead of fixed percent moves; consequences (tail share reported; singles' numbers depend on the tail model; condors capped per kind).
- README: a "Structures" subsection under Explorer with one paragraph, the two routes, and a screenshot `docs/img/structures.png` (hand-captured by the integrator; add it to the `img/` sentence in `CLAUDE.md`). `docs/architecture.md` explorer row mentions the two new routes. `docs/runbook.md` gains the 422 codes.
- `CLAUDE.md` layout lines: `engine/positions.py`, `engine/structures.py`, `analytics/views.py`, the router and the two routes.

## Ownership

- **API agent** (`feat/structures-api`): everything under `src/`, `tests/`, `apps/web/openapi.json` (generated), `docs/decisions/0014-*.md`, `docs/runbook.md`, `docs/architecture.md`, `CLAUDE.md`, README prose (not the screenshot). First push within the first commits: models + router stubs returning real data for one endpoint + `openapi.json`, so the web agent can generate types.
- **Web agent** (`feat/structures-web`): everything under `apps/web/` except `openapi.json`. Starts from the JSON shapes in this file (hand-typed in `src/api/types.ts` as the other responses are), then fetches `origin/feat/structures-api:apps/web/openapi.json`, runs `npm run gen:api` and reconciles before finishing. Never edits Python.
- Integrator merges both, runs `make check` and `make web-check`, captures the screenshot, verifies in the browser, pushes `main`.

## Verification (integrator)

- `make check` and `make web-check` green; CI green on `main`.
- `curl` the NVDA latest session with `preset=up_moderate` and with `lo=1.05`: `kinds` has at least `long_call`, `bull_call_spread`, `bull_put_spread`; `bull_put_spread.expected_return` on the `mid` fill equals the `spread_scores` row's `expected_roc` for the same strikes within 1e-6 after the tail terms are removed (compare with `mass_lo = mass_hi = 0` by a test fixture, and in the live check within the reported `tail_share`).
- Browser: `/structures` for NVDA and XLF, each preset, both fills; the dominance strip changes with the view; the verdict sentence matches the table; `/outcomes` renders 11 rows × 6 columns and a cell click lands on the right `/structures` state.
- No "buy", "sell", "recommend", "should" in any new UI string or template (extend the existing wording test).
