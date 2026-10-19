# Spec: edge, fair credit and risk-adjusted ranking for put credit spreads

This is based on main at 2413574. The return-on-max-loss rename has already landed there, so the line numbers below are from that commit. I checked everything here against the code and the live `.dbt-local/oap.duckdb` (session 2026-10-16: 4,405 rows, 1,459 eligible).

## 0. Live sanity check: what `expected_payoff / credit` looks like today
I recomputed every row read-only with `chain_cdf`, `apply_calibration` and the production map. The Simpson moments in §1 reproduce gold `credit − expected_payoff` to **1.5e-12** on all 4,405 rows.

| quantile | p1 | p5 | p25 | p50 | p75 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|---|
| edge_pct, calibrated, eligible | .143 | .183 | .211 | .255 | .389 | .752 | .835 | .857 |
| edge_pct, calibrated, all rows (min −2.05) | −.015 | .022 | .111 | .169 | .230 | .606 | .817 | .952 |
| edge_pct, raw, eligible | −.237 | −.085 | −.034 | −.017 | −.007 | .017 | .087 | |
| edge_pop, eligible | .007 | .018 | .032 | .045 | .057 | .078 | .084 | |
| reward_to_risk, eligible | .052 | .113 | .135 | .147 | .162 | .236 | .264 | .488 |
| payoff_std / width, eligible (max over all rows .4997) | .036 | .042 | .159 | .275 | .366 | .436 | .455 | |

- **The raw edge is about 0, as it should be.** It is slightly negative because fair credit is undiscounted (growth at 4.5%) and because of knot interpolation.
- **Ranking by edge picks the far tail.** All of the top 12 edge_pct rows have short moneyness 0.79–0.90 and a calibrated POP of at least 0.997 (raw about 0.985). The production map sends a raw F of 0.0113 to 0.0013.
- **That tail rests on very few events.** Out of sample, predictions with a raw probability under 2% saw 52 breaches in 52,508.
- **A credit floor does not change this.** Adding `credit ≥ 0.25` and `natural ≥ 0.5·credit` leaves the top of the edge list the same.
- **Reward/risk ranks differently.** Its Spearman correlation with edge_pct is 0.45. Its top row is XLF 55/54.5: mid 0.30, natural 0.04, fair 0.19.
- **The natural edge is a separate check.** `credit_natural − fair_credit > 0` holds for 77.9% of eligible rows.

## 1. Engine: `src/oap/engine/spread_scoring.py` (pure, numpy only)

**Derivation.** Let L = long strike, K = short strike, W = K − L. The long put spread pays h(S) = min(max(K−S, 0), W), which lies in [0, W].
- For any non-increasing φ with φ(+∞) = 0, φ(S) = ∫_S^∞ −φ′(x)dx. By Tonelli, E[φ(S)] = ∫ −φ′(x)·F(x) dx, where F(x) = P(S < x) = `prob_below`.
- This is the same measure `prob_below` and `integrate_cdf` already use (`implied_distribution.py:124-237`): flat tails put mass F(k₀) below every price and 1 − F(kₙ) above every price. The left atom therefore pays W and the right atom pays 0, so no tail term is needed.
- φ = h gives E[h] = ∫_L^K F dx. That is the existing `cdf.expected_payoff_put_spread(K, L)` (line 219).
- φ = h² gives **E[h²] = ∫_L^K 2(K−x)·F(x) dx**.
- Exact evaluation: take the grid G = {L, K} ∪ {knots strictly inside (L, K)}. F is affine on each segment [a, b], so q(x) = 2(K−x)F(x) is quadratic there and Simpson's rule is exact: ∫_a^b q = (b−a)/6·(q(a) + 4q((a+b)/2) + q(b)).
- Var = max(0, E[h²] − E[h]²), payoff_std = √Var. Since h ∈ [0, W], Var ≤ W²/4 (Popoviciu).
- Seller P&L = credit − h + interest, and interest is deterministic, so Var(P&L) = Var(h).

**Worked example** (add to the module docstring; hand CDF, 100/95 spread, credit 2.00):
- E[h] = 2.0625, so fair_credit = 2.0625.
- E[h²] = 6.458333 + 2.8125 = 445/48 = 9.2708333.
- Var = 5.0169271, payoff_std = 2.2398498.
- edge = −0.0625, edge_pct = −0.03125, reward_to_risk = −0.0279037.

**Signatures**
```python
RankBy = Literal["return", "edge", "reward_to_risk"]
_STD_FLOOR: Final = 1e-9  # payoff_std <= _STD_FLOOR * width is treated as 0


def put_spread_payoff_moments(
    cdf: RiskNeutralCdf, k_short: float, k_long: float
) -> tuple[float, float]:
    """(E[h], E[h**2]) in $/sh and ($/sh)**2; E[h] is cdf.expected_payoff_put_spread(k_short, k_long) verbatim."""
```
- `SpreadScore` (line 137): add required fields after `kelly_fraction`:
  - `fair_credit: float`, in $/sh, in [0, W]
  - `edge_pct: float` = expected_payoff / credit, ≤ 1
  - `payoff_std: float`, in $/sh, in [0, W/2]
  - `reward_to_risk: float` = expected_payoff / payoff_std; nan when std is 0. It is per trade and not annualised. It is effectively an excess-over-cash Sharpe ratio, because interest is the risk-free leg.
- `score_spread` (line 189):
  - Call the moments function once.
  - Set `expected_payoff = spread.credit - fair_credit`. This must stay bit-identical to line 220 so the scale-invariance tests keep passing.
  - Floor: if std ≤ 1e-9·W, then std = 0.0 and reward_to_risk = nan.
  - Kelly is unchanged.
  - No new `edge` field: edge is `expected_payoff`.
- `rank_spreads(scores, *, min_prob_profit=0.0, by: RankBy = "return")` (line 309):
  - `return` keeps today's key.
  - `edge` sorts by `(-edge_pct, -prob_profit, -short, long)`.
  - `reward_to_risk` sorts by `(isnan(rr), -rr, -prob_profit, -short, long)`, so nan goes last.

**Tests** (`tests/engine/test_spread_scoring.py`; update the `_score` helper at line 157 for the new fields):
1. **Worked example:** the numbers above, to rel 1e-12.
2. **Constant F:** both strikes below the lowest knot, F ≡ c = 0.2. Expect fair = cW, E[h²] = cW², Var = c(1−c)W².
3. **Degenerate case:** F ≡ 0 on [L, K]. Expect fair 0, std 0, reward_to_risk nan, edge_pct exactly 1.
4. **Brute force** (hypothesis over `_lognormal_chain`, raw CDF plus a fitted non-identity `CalibrationMap`):
   - Stieltjes midpoint sum over 20,000 cells on [L, K] plus the atom F(L)·W².
   - |E[h] − bf| ≤ 1e-6·W, and |E[h²] − bf| and |Var − bf| ≤ 1e-6·W².
   - Keep the grid on [L, K] only. A wide grid misses the tolerance (error is about Δ²/12).
5. **Bounds (property):**
   - −1e-12·W ≤ fair ≤ W(1 + 1e-12)
   - edge_pct ≤ 1
   - 0 ≤ std ≤ W/2·(1 + 1e-12)
   - |fair + expected_payoff − credit| ≤ 1e-12·max(1, W)
   - sign(rr) = sign(expected_payoff) when std > 0
6. **Own-CDF fairness:**
   - Conditions: rate 0 (the credit is discounted while the fair credit is not), step_frac ∈ [0.05, 0.1], and only spreads with `long ≥ cdf.strikes[0]`.
   - Assert |edge| ≤ 2e-3·W, and |edge_pct| ≤ 0.03 when credit ≥ 0.05·W.
   - Measured worst case: 7.6e-4·W and 0.0133.
   - With step 0.25 the error reaches 4.6e-3·W, so do not widen the strategy.
7. **Scale invariance:** fair and std scale with c; edge_pct and rr are invariant (rel 1e-6, abs 1e-9) in both helper tests.
8. **`rank_spreads(by=...)`:** ordering, tie-breaks, and nan last.

## 2. Analytics: `scoring.py`, `config.py`, `io.py`
**New columns in `SPREAD_COLUMNS`** (line 41) and `OUTPUT_SCHEMAS["spread_scores"]` (io.py:126), in the same order:
- After `kelly_fraction`, all DOUBLE:
  - `fair_credit` (calibrated)
  - `fair_credit_raw`
  - `edge` (= expected_payoff)
  - `edge_raw` (= raw.expected_payoff)
  - `edge_natural` = credit_natural − fair_credit. **I added this one; it was not in the brief.** It shows whether the gap survives a fill at the natural price. Drop it if the owner declines.
  - `edge_pct`
  - `edge_pop` = prob_profit − prob_profit_raw
  - `payoff_std` (calibrated)
  - `reward_to_risk` (NaN becomes NULL via `to_output`)
- After `rank`, both NULLABLE_BIGINT: `rank_edge`, `rank_rr`.

**Config** (`AnalyticsConfig`): add `min_edge_credit: float = 0.25` ($/sh, ≥ 0) and `min_natural_fraction: float = 0.5` (in [0, 1]), with validation.

**`_expiry_rows`** (line 96): fill the new fields from `cal`/`raw`. `edge_pop` uses the two POPs.

**`_with_ranks(rows, scores, config)`** (line 255):
- `rank` is unchanged.
- `rank_edge` and `rank_rr` are both 1..k over one candidate set: `eligible and credit >= min_edge_credit and credit_natural >= min_natural_fraction*credit`. That set is 1,265 of 1,459 today.
- Order each with `rank_spreads(by="edge" | "reward_to_risk")`.

**Module docstring:** state the interpretation that the docs and UI must also carry:
- Edge = market mid credit minus the expected payout under the *pooled* production map. It is the historical variance risk premium applied to this chain, plus whatever mid-vs-natural gap the mid holds.
- It is not contract-specific mispricing.
- It is correlated across the strikes and expiries of one underlying.
- The map is in-sample for the latest session and comes from a hindsight universe (ADR 0010).
- The largest edges sit in the far tail, where the map rests on the fewest breaches.

**Tests** (`tests/analytics/test_scoring.py`):
- New columns equal `score_spread(..., calibration=cmap)` and raw `score_spread`.
- `edge == expected_payoff`.
- Identity map gives `edge_pop == 0` and `fair_credit == fair_credit_raw`.
- `rank` is unchanged versus `rank_spreads()`.
- `rank_edge`/`rank_rr` are contiguous and follow `rank_spreads(by=)`.
- Each guard (credit floor, natural fraction, ineligible) nulls both alt ranks; parametrise the config.
- `test_io.py:248` and `tests/dbt/test_project.py:158` already enforce the column order and schema description.

## 3. dbt (`dbt/models/analytics/schema.yml` from line 280, `docs.md:55`)
Describe every new column with units; the project test requires exact coverage. Add model-level `dbt_utils.expression_is_true` tests:
```yaml
- expression: "fair_credit >= 0 and fair_credit <= width + 1e-9 and fair_credit_raw >= 0 and fair_credit_raw <= width + 1e-9"
- expression: "edge = expected_payoff and abs(fair_credit + edge - credit) <= 1e-9 * greatest(1, width)"
- expression: "edge_pct <= 1"
- expression: "payoff_std >= 0 and payoff_std <= width / 2 + 1e-9"
- expression: "payoff_std = 0 or reward_to_risk is not null"
```
- Column tests:
  - `not_null` on fair_credit, edge, edge_pct, payoff_std.
  - `accepted_range [-1, 1]` on edge_pop.
  - `unique` on rank_edge and rank_rr.
- Extend `dbt/tests/assert_spread_rank_contiguous.sql`, so `ANALYTICS_SINGULAR_TESTS` needs no change. Add a second CTE checking, for each of rank_edge and rank_rr:
  - `count = max`
  - not null implies `eligible`
  - `(rank_edge is null) = (rank_rr is null)`
- `docs.md`: add one paragraph with the definitions and the honest reading from §2.
- `dbt/models/analytics/spread_scores.py` itself is unchanged.

## 4. API (`src/oap/api/`)
**models.py**
- `SpreadSort = Literal["return","edge","reward_to_risk","kelly","pop"]`.
- `SpreadRow` (line 213) gains, with $/sh units in each description:
  - `fair_credit: float`, `edge: float`, `edge_natural: float`, `edge_pct: float`, `edge_pop: float`, `payoff_std: float`
  - `reward_to_risk: float | None`
  - `rank_edge: int | None`, `rank_rr: int | None`
- `SpreadDetail` gains `fair_credit_raw: float` and `edge_raw: float`.
- `SpreadsResponse` gains `sort: SpreadSort`. Update the `rows` description to "ordered by `sort`".

**spreads.py**
- `SpreadFilters` gains `min_edge_pct: float | None = None` and `sort: SpreadSort = "return"`.
- `filter_spreads` adds `edge_pct >= min_edge_pct`.
- New `order_spreads(frame, sort)`: stable sort, nulls last:
  - `return`: no-op; `prepare_spreads` already orders by rank then annualised_roc.
  - `edge`: rank_edge ↑, then edge_pct ↓
  - `reward_to_risk`: rank_rr ↑, then reward_to_risk ↓
  - `kelly`: kelly_fraction ↓, then rank ↑
  - `pop`: prob_profit ↓, then rank ↑
- `_row`/`spread_detail` map the fields; use `finite_or_none` for rr; `_rank` for both alt ranks.

**store.py:549** calls `order_spreads` after `filter_spreads`.

**routers/spreads.py:20** adds the query parameters:
```python
sort: Annotated[SpreadSort, Query(description="Row order.")] = "return"
min_edge_pct: Annotated[
    float | None, Query(le=1, description="Minimum edge as a share of the mid credit.")
] = None
```

**Tests** (`tests/api/test_spreads.py`, `test_routes_spreads.py`):
- Each sort's order.
- Unknown `sort` returns 422; `min_edge_pct=1.5` returns 422.
- The `min_edge_pct` filter works.
- Detail `fair_credit + edge == credit`.
- A nan rr serialises as null.
- `tests/api/gold.py` needs no change because it builds from `score_latest_session`.
- Then run `make api-schema`. It regenerates `apps/web/openapi.json` and `src/api/schema.ts`; `test_openapi.py` gates this.

## 5. Web (`apps/web`), owned by B
**State** (`useSpreadFilters.ts`):
- Add `rankBy: SpreadSort` (URL `by`, omitted when `return`) and `minEdgePct: number | null` (URL `edge`).
- `SpreadQuery` gets `sort` and `minEdgePct`.
- `spreadSearchParams` (queries.ts:65) always sets `sort`, and sets `min_edge_pct` only when it is non-null.

**Controls** (SpreadsPage.tsx:197): add a `SegmentedToggle` labelled "Rank by" with options Return on max loss | Edge | Reward/risk | Kelly | POP, plus a `NumberField` "Min edge (%)" that converts percent to decimal.

**Highlights default** (line 163): use the first 3 eligible rows in server order, which is the active sort, instead of `rank <= 3`.

**New chart `charts/MispricingScatter.tsx`**
- Axes: x = fair_credit, y = market (mid) credit, both `scaleLog` in $/sh. Fair credits span 0.03–12 for eligible rows, so linear axes would collapse.
- Floor values at $0.01 and pin below it with the existing triangle and "n pinned" note.
- Draw the y = x line (`data-testid="parity-line"`). Draw dashed guides for edge_pct 25/50/75%, i.e. y = x/(1−e), which are parallel lines on log-log axes.
- Point size: `scaleSqrt` on width (p95 clamp). Use the same highlight slots, shapes, voronoi hover, selection ring and legend as `SpreadScatter`.
- Extract those shared pieces into `charts/scatterLayer.tsx` rather than copying about 150 lines.
- Each point gets `data-side="above|below"`.
- Tooltip: mid, natural, fair (calibrated and raw), edge $ and %.
- Copy:
  - Region note: "Above the line: market credit exceeds the calibrated fair credit."
  - Heading: "Market vs calibrated fair credit".
  - **Deliberate deviation from the brief:** no "overpriced" or "sell candidates" wording (see §9).

**Layout:**
- The second card goes under the POP chart in the left column.
- `.detail` gets `grid-row: span 2` at the ≥ breakpoint (global.css:813).
- On phones it stacks.

**Table** (`COLUMNS`, line 38):
- First column is "#" with header `Rank · {label}`. Its value is the 1-based position in `data.rows` (map spread_key to index), so it stays stable when the user clicks a header to re-sort.
- Add Fair credit, Edge $, Edge %, Reward/risk (2 decimals; null shows –) after Natural and Ann. R/max loss.
- Remount with `key={rankBy}` so the sort state resets (`DataTable` keeps `defaultSort` in `useState`).

**Detail panel** (line 318):
- New tiles:
  - Fair credit ($/sh; sub `raw $x`)
  - Edge ($/sh; sub `x% of mid · natural ±$y`)
  - Payoff σ ($/sh)
  - Reward/risk (sub "per trade, not annualised")
- One interpretation line: "Fair credit applies one pooled calibration map to this chain: a historical average across today's large caps, not a forecast for this contract." If `edge_natural < 0`, append "At the natural credit the gap is negative."

**Fixtures and server** (`src/test/fixtures.ts:249`, `server.ts:48`):
- Add the new fields to `spread()`.
- `makeSpreads` honours `sort` and `min_edge_pct`.
- Include one row with `reward_to_risk: null`.

**Tests**
- New `useSpreadFilters.test.ts`: round-trips `by` and `edge`.
- `queries.test`: params and query key.
- `SpreadsPage.test`:
  - Rank-by sends `sort=edge` and writes `by=edge`.
  - The header and order change.
  - Min edge sends `min_edge_pct=0.2`.
  - Detail tiles render.
  - The page text contains none of `/\b(buy|sell|recommend)\b/i`.
- `MispricingScatter.test`: parity line, `data-side`, size grows with width, pinning below the floor, click selection, selection ring, legend, aria label.
- `format.test` for a `ratio()` formatter.

## 6. Report (`scripts/make_report.py`)
- Add to `_SCORES_SQL` (line 151): `fair_credit, edge, edge_natural, edge_pct, reward_to_risk, rank_edge`.
- New `_edge_section(data)` goes after `_spreads_section` (line 616):
  - Heading: "Top spreads by edge".
  - 5 rows: `scores.dropna(subset=["rank_edge"]).sort_values("rank_edge").head(5)`.
  - Columns: Rank (edge), Underlying, Expiration, Short/long, Mid credit, Natural credit, Fair credit, Edge, Edge (% of mid), POP calibrated, POP risk-neutral, Reward/risk.
- Caveat sentence: "Edge measures the mid credit against one pooled calibration map, so it is the historical variance risk premium applied to this chain, not a contract-specific mispricing; it is correlated across strikes, concentrated in the far tail, and partly the half-spread the natural credit gives up."
- Optional: a DB-driven tail count — `select count(*), sum(realised::int) from gold.calibration_sample where is_out_of_sample and predicted_raw < 0.02` (52 / 52,508 today).
- `readme_excerpt` and `SPREAD_HEADERS` stay unchanged, so the README excerpt does not change.
- `tests/scripts/test_make_report.py:91` `_scores_frame` gains the columns. Add tests for the new section's order, row count and caveat, and assert that the README excerpt is unchanged.

## 7. Docs
- **ADR 0013**, "Edge and risk-adjusted ranking: definitions and what they do not mean":
  - Definitions and the Simpson derivation.
  - Why `return` remains the default rank.
  - The guards.
  - The §0 numbers as evidence of tail dominance.
  - Alternatives: grid integration (rejected: inexact); ranking on natural edge (rejected as default, but shown); per-trade vs annualised R/R (per trade chosen; it mixes 14–63 DTE).
- **Runbook:** one paragraph. Adding the columns makes `/api/spreads` return 503 `gold_missing` on an older gold file. After merging, run `make dbt-build-local` before restarting the API. A `make pull-gold` artifact older than the merge has the same problem.
- **README:** one paragraph outside the results markers.
- **Other docs:** update `docs/architecture.md:124,144` and `docs/design/explorer-v1.md:309,313` (columns and tiles).
- **CLAUDE.md:** line 15 says "ADRs 0001-0012". That becomes stale, so change it to 0013 (a fact, not a convention).

## 8. Ownership, handoff, acceptance
- **A** (engine, analytics, dbt, API, report, docs):
  - Commit order: engine → analytics + config + dbt → API.
  - Run `make api-schema` and commit `openapi.json` and `schema.ts` in the same commit as the API change. That commit is the **handoff**; push it early.
  - Then report and docs.
- **B** (web):
  - Start from the field names in §4 using fixtures.
  - Rebase onto A's API commit; do not hand-edit `schema.ts`.
- **Conflicts:** both touch only disjoint files apart from `openapi.json`/`schema.ts`, which only A writes.
- **Acceptance:**
  1. `make check` (A) and `make web-check` (B) are green.
  2. Stop `make serve`/`make app`, then run `make dbt-build-local` and `make report`.
  3. Review the diff: `docs/results.md` gains the section; the README excerpt has no diff.
  4. Restart `make serve`.
  5. Read-only SQL: eligible `edge_pct` median ≈ 0.25; `count(rank_edge) = 1265` if the data is unchanged; `max(abs(fair_credit + edge - credit)) < 1e-9`.
  6. Browser at `http://127.0.0.1:8000/spreads`, checking each Rank-by mode:
     - order and header
     - `?by=edge&edge=0.3` survives a reload
     - Mispricing points lie above the parity line for positive edge
     - detail tiles and interpretation line show
     - phone width stacks
     - no console errors

## 9. Risks
- **Tail dominance.** edge_pct puts deep-OTM, POP ≈ 0.998 spreads first. The evidence behind them is thin (52 OOS breaches) and is exactly where survivorship bias is largest. Keep `return` as the default and state this in the UI, the report and the ADR.
- **Tiny or noisy credits.** These are guarded by `min_credit` 0.10 at enumeration and by the `min_edge_credit`/`min_natural_fraction` rank guards. The mid-vs-natural gap is shown, not hidden.
- **Division.** credit > 0 is enforced by `PutCreditSpread`. std = 0 gives nan rr, which becomes NULL, which becomes `None`. The rr ranking puts nan last.
- **Cancellation in Var.** Clamped at 0, floored at 1e-9·W, and tested.
- **Wording.** The brief's "overpriced (sell candidates)" conflicts with "no trade advice". Use the "credit above/below calibrated fair" copy and the no-buy/sell test. The owner should confirm that deviation.
- **Schema change.** An old gold file returns 503 until it is rebuilt (see the runbook step).
