# Explorer v1: implementation spec (React + FastAPI)

I checked this against the code and the real data in `.dbt-local/oap.duckdb`, opened read-only.

**Data facts that drive the design:**
- **Sessions are small.** A session has at most 266 quotes and 3 to 4 expirations. The latest SPY session has 210 quotes, 4 expirations and 25 to 27 strikes, covering moneyness 0.70 to 1.30.
- **The engine is fast.** `chain_cdf` takes about 7 ms for 3 expirations.
- **Calibrated curves have too many knots to send.** `apply_calibration` returns about 400 knots per expiry, because the production map has 368 knots. The API must evaluate the calibrated CDF at the raw knots and never send the composed knot set.
- **Loading one underlying is cheap.** All of one underlying's quotes (about 170 k rows, about 22 MB in pandas) load in 36 ms warm and 1.1 s cold. Opening and closing a read-only connection costs about 9 ms.
- **`gold.spread_scores` has extreme values.** It holds 3,253 rows, 1,141 of them eligible, for session 2026-10-02. `expected_roc` (return on max loss; collateral equals max loss) reaches 4.5e13 across all rows but stays within 0.002 to 0.37 for eligible rows. 227 rows have a return on max loss above 100%. `annualised_roc` can be infinite.
- **Calibration maps.** `gold.calibration_map` holds `fold_2020` (identity, n=0), `fold_2021` to `fold_2026`, and `production` (n=487,352). The overall metrics are raw versus calibrated: ECE 0.0352 to 0.0167, Brier 0.1267 to 0.1293.
- **Locked versions and tools.** DuckDB is 1.5.6 (`docker/requirements-dbt.txt` pins the same) and pydantic is 2.13.5. FastAPI and uvicorn are not in the lock yet. Node on this laptop is v24.
- **The writer lock is the main risk.** Any read-only connection the API holds blocks the dbt writer, and `dbt_build` has `retries=1` with a 2-minute delay. So the API opens the database rarely and briefly, and serves from memory.

## 1. Decision: visx, not Plotly
Use **visx**: `@visx/{scale,shape,axis,grid,group,tooltip,event,voronoi,responsive,curve,pattern}` plus `d3-interpolate`. Reasons:
1. **Animation.** The animation is a scrubber over sessions that are fetched lazily. `Plotly.animate` needs precomputed frames and does not tween heatmaps, whereas a React re-render per session is natural with visx.
2. **Bundle size.** `plotly.js-cartesian-dist-min` (the smallest Plotly bundle that includes a heatmap; the basic bundle has none) is about 1.3 MB minified, about 400 KB gzip. The visx subset is about 60 KB.
3. **Look.** Plotly needs heavy templating (modebar, fonts, hover boxes) to avoid the default-dashboard look. visx starts from bare SVG and the palette tokens.
4. **Tests.** visx renders SVG that Testing Library can query in jsdom. Plotly needs canvas and `URL.createObjectURL` stubs, and its output cannot be asserted on.
5. **WebGL is unnecessary.** The heaviest view is about 3.3 k scatter points and a heatmap of at most 4×41 cells.

The cost is more chart code (6 components) and voronoi hover. ADR 0011 records this.

## 2. Ownership and the integration contract
- **Implementer A (API, Python tooling, docs)** owns:
  - `src/oap/api/**`, `tests/api/**`, `scripts/export_openapi.py` and `apps/web/openapi.json` (generated).
  - `pyproject.toml`, `uv.lock`, `Makefile`, `.github/workflows/ci.yml`, `.gitignore`, `.pre-commit-config.yaml`.
  - The README, `docs/runbook.md`, `docs/architecture.md`, `docs/decisions/0011-*.md` and the CLAUDE.md layout and checks lines (only if the user confirms).
- **Implementer B (web)** owns `apps/web/**` except `openapi.json`.
- **The contract.** `apps/web/openapi.json` is produced by `scripts/export_openapi.py` with `json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"`. B generates `apps/web/src/api/schema.ts` from it with `openapi-typescript@^7` (`npm run gen:api`). Components import types only through `src/api/types.ts`, for example `export type Distribution = components["schemas"]["DistributionResponse"]`.
- **Drift is caught on both sides:**
  - `tests/api/test_openapi.py` fails `make check` if `openapi.json` is not equal to `app.openapi()`.
  - B's `npm run check:api` runs `openapi-typescript openapi.json | diff - src/api/schema.ts`.
  - `schema.ts` and `openapi.json` go in `.prettierignore`.
- **Sequencing.** A commits the models, a route skeleton and `openapi.json` first (milestone A1). B starts in parallel using fixtures typed by hand from §4 and switches to the generated types at A1. Route `name=` values are fixed so operation IDs are stable: `listUnderlyings`, `listSessions`, `getChain`, `getDistribution`, `getHeatmap`, `listSpreads`, `getSpread`, `getCalibrationSummary`, `healthz`.

## 3. API: module layout (`src/oap/api/`)
Every module gets Google docstrings stating units, must pass `mypy --strict`, and uses no `print`.

| File | Contents |
|---|---|
| `__init__.py` | Package docstring. |
| `settings.py` | Frozen dataclass `ApiSettings.from_env()`. Fields: `duckdb_path` (env `OAP_DUCKDB_PATH`, default `.dbt-local/oap.duckdb`); `web_dist` (`OAP_WEB_DIST`, default `apps/web/dist`); `retry_after_s=15`; `quotes_cache=3` (underlyings); `session_cache=256`; `duckdb_config={"threads": "2", "memory_limit": "512MB", "access_mode": "READ_ONLY"}`; `cors_origins` (`OAP_API_CORS_ORIGINS`, comma list, default empty means no CORS middleware). |
| `db.py` | See the `db.py` notes below. |
| `store.py` | `GoldStore`: thread-safe caches (§3.2) and the only place `GoldReader` is called. |
| `landscape.py` | **Pure** (no I/O): `session_bundle(quotes, outcomes, cmap, map_meta, latest, config) -> SessionBundle`, holding the chain, distribution and heatmap models. Also `sessions_summary(quotes)` and `pick_map(...)`. |
| `spreads.py` | **Pure**: `filter_spreads(frame, filters)` and `spread_detail(row, bundle_expiry, maps)`, which builds the payoff curve. |
| `models.py` | Pydantic models (§4). |
| `errors.py` | `DatabaseBusy`, `DatabaseMissing`, `GoldMissing`, `NotFound`, plus exception handlers that return `ErrorBody`. |
| `routers/meta.py`, `routers/landscape.py`, `routers/spreads.py` | `APIRouter(prefix="/api")`. All handlers are sync `def`, so they run in the threadpool. |
| `static.py` | `SPAStaticFiles(StaticFiles)`. On a 404 for a path not under `api/`, it returns `index.html`. |
| `main.py` | `create_app(settings: ApiSettings | None = None) -> FastAPI` and `app = create_app()`. Steps: add `GZipMiddleware(minimum_size=1000)` and the optional CORS middleware; include the routers; add `/healthz`; if `web_dist/index.html` exists, mount `SPAStaticFiles(directory=web_dist, html=True)` at `/` **last**, otherwise `GET /` returns a JSON 404 hint "run make web-build". |

**`db.py` details:**
- `db_signature(path) -> tuple[int, int, int]` is `(mtime_ns, size, wal size or -1)`. It is computed with `os.stat` and takes no lock.
- `GoldReader.read(sql, params) -> pd.DataFrame` opens `duckdb.connect(str(path), read_only=True, config=...)`, runs one or more parameterised queries and closes in `finally`.
- Error mapping:
  - A missing path raises `DatabaseMissing`.
  - `duckdb.IOException` whose message contains "lock" (case-insensitive) raises `DatabaseBusy`.
  - `duckdb.CatalogException` raises `GoldMissing`.
- Use `?` parameters only. Never format strings into SQL.
- Validate symbols with `^[A-Z][A-Z.]{0,9}$` as a `Path(pattern=...)` constraint (422 on mismatch).

### 3.1 SQL (column names exactly as in the schema.yml files)
- **Q1 underlyings** (one query per signature):
  ```sql
  select d.symbol, d.sector, min(q.trade_date) as first_session, max(q.trade_date) as last_session, count(distinct q.trade_date) as n_sessions
  from gold.dim_underlying d join gold.fct_option_quote q on q.underlying = d.symbol
  group by d.symbol, d.sector order by d.symbol
  ```
- **Q2 quotes for one underlying** (one connection, together with Q3):
  ```sql
  select underlying, trade_date, expiration, cast(strike as double) as strike, option_right, bid, ask, mid, source_iv, source_delta, moneyness, underlying_close, dte_days
  from gold.fct_option_quote where underlying = ? order by trade_date, expiration, strike, option_right
  ```
  Cast `option_right` and `underlying` to `category`, and convert dates to `datetime64[ns]` as `io._to_ns` does.
- **Q3 outcomes:**
  ```sql
  select expiration, settlement_date, cast(settlement_close as double) as settlement_close from gold.fct_expiration_outcome where underlying = ?
  ```
- **Q4 spreads.** Build the column list from `oap.analytics.scoring.SPREAD_COLUMNS` (a single source):
  ```sql
  select {cols} from gold.spread_scores
  ```
- **Q5 maps:**
  ```sql
  select map_id, fold, train_cutoff, train_max_expiration, knot_index, predicted, calibrated, n_samples, is_identity from gold.calibration_map
  ```
  Pass the frame to `oap.analytics.backtest.maps_from_frame`, and keep `fold`, `train_cutoff`, `train_max_expiration` and `n_samples` per `map_id` as metadata.
- **Q6 metrics:**
  ```sql
  select segment_type, segment, variant, metric, value, ci_low, ci_high, n_predictions, n_snapshots, n_clusters from gold.calibration_metrics where segment_type = 'overall'
  ```
- **Q7 latest session:**
  ```sql
  select max(trade_date) from gold.fct_option_quote
  ```
  This matches `io.LATEST_QUOTES_SQL` semantics.

### 3.2 CDF path, caching and lock handling
- **The same path as the backtest.** Per expiration of a session (rows of Q2 for `(trade_date, expiration)`):
  1. `years = dte_years(trade_date.date(), expiration.date())`.
  2. `cdf = chain_cdf(chain, years=years, rate=DEFAULT_CONFIG.risk_free_apy)`.
  3. `cal = apply_calibration(cdf, cmap)`.
- **What the response sends:**
  - The raw knots `cdf.strikes`, `cdf.cdf` and `cdf.raw_cdf`.
  - `cal.prob_below_array(cdf.strikes)`.
  - The density from `cdf.density()`, and the calibrated density as `diff(cal_at_knots)/diff(knots)` at the same midpoints.
- **Expiries without a curve** get `curve=None` with a reason:
  - `dte_days < 1`: `expired`.
  - Null or non-positive close: `no_close`.
  - `chain_cdf` returns None: `too_few_puts`.
  - `EngineInputError`: `engine_error: <msg>`.
- **Short-dated expiries** (`dte_days < DEFAULT_CONFIG.min_dte_days`) are still shown with `short_dated=true`.
- **Non-finite values.** NaN forward becomes `None`.
- **Map choice** (`map` query parameter):
  - `auto` (default) uses `production` when the session equals Q7, otherwise `walk_forward`.
  - `walk_forward` uses `fold_<session year>` if present, otherwise identity.
  - `production` uses the production map.
  - `look_ahead` is true when `map_train_max_expiration` is at or after the session, meaning the map has seen this outcome.
- **Heatmap:**
  - Columns are a display grid, `moneyness = [round(0.80 + 0.01*i, 2) for i in range(41)]`, with `MONEYNESS_GRID` returned for tick marks.
  - Targets are `round(m * close, 6)`, matching `STRIKE_DECIMALS`.
  - A value is `null` outside `[knots[0], knots[-1]]`. This is the backtest's no-extrapolation rule.
- **Caches** (in `GoldStore`, one `threading.RLock`; database reads are also serialised under it, so at most one open at a time):
  - `tables[sig]` holds Q1, Q4, Q5, Q6 and Q7. They load lazily, one connection per table group.
  - An LRU of size 3 keyed by `(sig, symbol)` holds a `QuotesBundle` (quotes, outcomes, sessions summary).
  - An LRU of size 256 keyed by `(sig, symbol, session, map_id)` holds a `SessionBundle`, about 40 KB each.
  - Write a small generic `_Lru[K, V]` on `OrderedDict`; add no dependency.
  - As a result, scrubbing and animation never touch the database after the first load of an underlying.
- **Stale and busy logic.** On each request, compute `sig = db_signature()`.
  - If `sig` changed and the load raises `DatabaseBusy`, but an entry exists for the last good signature, serve it with the header `X-OAP-Data-Stale: 1`.
  - Otherwise return **503** with `ErrorBody(code="database_busy", detail="The DuckDB file is locked by a writer (dbt_build or score_spreads). Retry shortly.")` and `Retry-After: 15`.
  - `DatabaseMissing` returns 503 with code `database_missing` and detail "run make dbt-build-local", with no Retry-After.
  - `GoldMissing` returns 503 with code `gold_missing`.
  - When the signature changes, drop the entries for older signatures.
- **`/healthz`** always returns 200: `{status:"ok", db:"ok"|"busy"|"missing", db_path, last_good_signature_at}`.

## 4. Pydantic models (`models.py`)
- **Base class:** `class ApiModel(BaseModel): model_config = ConfigDict(frozen=True, ser_json_inf_nan="null")`.
- **Field descriptions carry the units:** dollars per share ($/sh), decimals, 1/$.
- **Any float that can be non-finite** is typed `float | None` and converted to `None` in code.

| Model | Fields |
|---|---|
| `Underlying` | `symbol: str`, `sector: str`, `first_session: date`, `last_session: date`, `n_sessions: int` |
| `UnderlyingsResponse` | `underlyings: list[Underlying]`, `latest_session: date` |
| `SessionSummary` | `session: date`, `underlying_close: float \| None` ($), `n_expirations: int`, `n_quotes: int`, `atm_iv: float \| None` (decimal; the OTM put with minimum `\|moneyness−1\|` and `source_iv > 0` in the shortest expiry with `dte_days ≥ 7`) |
| `SessionsResponse` | `symbol`, `sessions: list[SessionSummary]` (ascending) |
| `ChainQuote` | `strike` ($), `option_right: Literal["C","P"]`, `bid`, `ask`, `mid` ($/sh, nullable), `iv` (decimal, nullable; null when ≤ 0), `delta` (nullable), `moneyness` (nullable), `usable: bool` (from `usable_mask`) |
| `ChainExpiry` | `expiration: date`, `dte_days: int`, `quotes: list[ChainQuote]` (strike asc, then C, then P) |
| `ChainResponse` | `symbol`, `session`, `underlying_close`, `expirations: list[ChainExpiry]` |
| `DistributionCurve` | `knots` ($), `moneyness`, `cdf`, `raw_cdf` (pre-repair, may leave [0,1]), `cdf_calibrated`, `density_mid` ($), `density` (1/$), `density_calibrated` (1/$). All `list[float]`. |
| `ExpiryDistribution` | `expiration`, `dte_days`, `years` (ACT/365), `forward: float \| None` ($), `underlying_close`, `n_quotes: int`, `n_knots: int`, `flags: list[str]` (sorted `QualityFlag` values), `short_dated: bool`, `curve: DistributionCurve \| None`, `unavailable_reason: str \| None`, `settlement_date: date \| None`, `settlement_close: float \| None`, `prob_below_settlement` and `prob_below_settlement_calibrated: float \| None` |
| `DistributionResponse` | `symbol`, `session`, `map_choice: Literal["auto","production","walk_forward"]`, `map_id: str`, `map_is_identity: bool`, `map_train_max_expiration: date \| None`, `look_ahead: bool`, `risk_free_apy: float`, `expirations: list[ExpiryDistribution]` |
| `HeatmapRow` | `expiration`, `dte_days`, `target_strikes: list[float]` ($), `prob_below`, `prob_below_calibrated: list[float \| None]`, `forward_moneyness: float \| None` |
| `HeatmapResponse` | `symbol`, `session`, `map_id`, `moneyness: list[float]`, `backtest_grid: list[float]`, `rows: list[HeatmapRow]` |
| `SpreadRow` | `spread_key`, `underlying`, `expiration`, `dte_days`, `short_strike`, `long_strike`, `width`, `credit`, `credit_natural`, `max_loss`, `breakeven` ($/sh), `short_moneyness`, `prob_profit`, `prob_profit_raw`, `prob_max_loss`, `expected_roc`, `expected_roc_raw`, `annualised_roc` (nullable), `kelly_fraction`, `eligible: bool`, `rank: int \| None`, `extrapolated: bool`, `flags: list[str]` |
| `SpreadsResponse` | `as_of: date \| None`, `source: Literal["gold","recomputed"]`, `total: int`, `matched: int`, `min_prob_profit: float` (config), `underlyings: list[str]`, `expirations: list[date]`, `rows: list[SpreadRow]` (rank asc, nulls last, then `annualised_roc` desc) |
| `PayoffPoint` | `price` ($), `payoff` ($/sh at expiry, before interest) |
| `SpreadDetail` | Every `SPREAD_COLUMNS` field (`SpreadRow` plus `trade_date`, `years`, `underlying_close`, `expected_payoff`, `interest`, `annualised_roc_raw`, `calibrated`, `map_id`, `cash_apy`, `risk_free_apy`); `forward`; `payoff: list[PayoffPoint]`; `density_mid`, `density_raw`, `density_calibrated`; `regions` with `prob_max_loss`, `prob_partial_loss`, `prob_profit`, each as `{raw, calibrated}`; `knot_range: tuple[float, float]` |
| `MetricValue` | `metric`, `variant` (`raw`, `calibrated` or `delta`), `value`, `ci_low`, `ci_high` (nullable) |
| `CalibrationSummary` | `map_id="production"`, `n_samples`, `train_max_expiration`, `first_test_year`, `n_predictions`, `n_snapshots`, `n_clusters`, `metrics: list[MetricValue]` |
| `ErrorBody` | `detail: str`, `code: Literal["database_busy","database_missing","gold_missing","not_found","invalid"]` |

**Payoff curve.** Let `lo = min(long − 2·width, breakeven − 0.04·close)` and `hi = max(short + 2·width, close·1.04)`. Price points are `np.linspace(lo, hi, 161)` together with `{long, short, breakeven}`, sorted and unique. `payoff = credit − max(short−S,0) + max(long−S,0)`. The densities come from the `SessionBundle` for `(underlying, trade_date, expiration)` using `maps[row.map_id]`, the same map as gold.

**Endpoints** (all GET):

| Path | Returns |
|---|---|
| `/healthz` | Health status (always 200) |
| `/api/underlyings` | `UnderlyingsResponse` |
| `/api/underlyings/{symbol}/sessions` | `SessionsResponse` |
| `/api/underlyings/{symbol}/sessions/{session}/chain` | `ChainResponse` |
| `.../distribution?map=auto` | `DistributionResponse` |
| `.../heatmap?map=auto` | `HeatmapResponse` |
| `/api/spreads` | `SpreadsResponse` |
| `/api/spreads/{spread_key}` | `SpreadDetail` (the key is URL-encoded; `\|` becomes `%7C`) |
| `/api/calibration/summary` | `CalibrationSummary` |

- `/api/spreads` query parameters: `underlying: list[str]`, `expiration: date | None`, `min_width`, `max_width` ($), `min_pop` (0 to 1, default 0), `min_credit` ($, default 0), `eligible_only` (default true), `limit` (default and maximum 5000).
- An unknown symbol, a session not in the list, or an unknown `spread_key` returns 404 `not_found`.
- Measured response sizes: about 25 KB for a chain, about 11 KB for a distribution and about 3 KB for a heatmap, before gzip.
- **Stretch (only after acceptance):** `GET /api/underlyings/{symbol}/sessions/{session}/spreads` runs `oap.analytics.scoring.score_latest_session(session_quotes, walk_forward_map)` and returns `source="recomputed"`.

## 5. Web app (`apps/web/`)
- **Root files:**
  - `package.json` with `"engines": {"node": ">=22"}` and `.nvmrc` = `22`.
  - `index.html`, `vite.config.ts` (React plugin, `server.proxy` sending `/api` and `/healthz` to `http://127.0.0.1:8000`, `build.outDir="dist"`, and a `test` block with `environment: "jsdom"` and `setupFiles: ["src/test/setup.ts"]`).
  - `tsconfig.json` (`strict`, `noUncheckedIndexedAccess`), `eslint.config.js` (flat config with typescript-eslint 8 and react-hooks), `.prettierrc.json`, `.prettierignore`, `openapi.json` (owned by A).
- **Dependency majors:** react and react-dom ^18.3, react-router-dom ^6, @tanstack/react-query ^5, visx ^3, d3-interpolate ^3. Dev: vite ^6, @vitejs/plugin-react ^4, typescript ^5.6, vitest ^3, jsdom, @testing-library/{react ^16, jest-dom ^6, user-event ^14}, msw ^2, eslint ^9, prettier ^3, openapi-typescript ^7.
- **Scripts:** `dev`, `build` (`tsc -b && vite build`), `lint`, `format:check`, `typecheck` (`tsc -b --noEmit`), `test` (`vitest run`), `gen:api`, `check:api`, and `check` (= `check:api && lint && format:check && typecheck && test`).
- **`src/` layout:**
  - `main.tsx`: QueryClientProvider and BrowserRouter. Routes are `/` (redirects to `/landscape`), `/landscape` and `/spreads` (both `React.lazy`), plus `*` for NotFound.
  - `App.tsx`: the shell. The header has the wordmark "oap · explorer", NavLink tabs, `CalibrationBadge` and `DataStatus`.
  - `api/`: `schema.ts` (generated), `types.ts`, `client.ts` and `queries.ts`.
    - `client.ts` exports `fetchJson<T>(path)` and `ApiError{status, code, retryAfterS}`. It reads `X-OAP-Data-Stale` into `dataStatus`, a module store exposed through `useSyncExternalStore`.
    - `queries.ts` holds a key factory and hooks: `useUnderlyings`, `useSessions`, `useChain`, `useDistribution`, `useHeatmap`, `useSpreads`, `useSpreadDetail`, `useCalibrationSummary`.
    - Retry rule: retry only on 503 `database_busy`, at most 8 times, with delay `retryAfterS*1000` (capped at 30 s).
    - `staleTime: Infinity` for session data. `placeholderData: keepPreviousData` everywhere.
  - `state/`: `useLandscapeParams.ts`, `usePlayback.ts`, `useSpreadFilters.ts`.
  - `charts/`: `ChartFrame`, `CdfSmallMultiples`, `CdfPanel`, `ProbabilityHeatmap`, `SmileChart`, `SessionSparklines`, `SpreadScatter`, `PayoffChart`, `ChartTooltip`, `axes.ts`.
  - `components/`: `Select`, `MultiSelect`, `SegmentedToggle`, `Chip`, `DataTable` (sortable, `aria-sort`, paginated 50 per page), `Scrubber`, `StatTile`, `CalibrationBadge`, `ErrorState`, `EmptyState`, `Legend`.
  - `theme/`: `tokens.css` and `global.css`.
  - `lib/`: `format.ts` and `flags.ts`.
  - `routes/`: `LandscapePage.tsx`, `SpreadsPage.tsx`, `NotFound.tsx`.
  - `test/`: `setup.ts`, `fixtures.ts`, `server.ts` (MSW).
- **Chart sizing.** Charts take `width` and `height` props, wrapped by `ParentSize` only in the pages, so tests pass explicit sizes.

### 5.1 Design tokens (`theme/tokens.css`, dark only in v1, `color-scheme: dark`)
These are the reference palette's dark steps. I ran the validator: the 3 categorical slots pass all-pairs in dark mode (worst CVD ΔE 9.4), and the 4-step ordinal ramp passes `--ordinal` (light end 2.63:1).

```css
:root{--page:#0d0d0d;--surface-1:#1a1a19;--hover:rgba(255,255,255,.04);--border:rgba(255,255,255,.10);
--grid:#2c2c2a;--axis:#383835;--ink-1:#f0efec;--ink-2:#c3c2b7;--ink-muted:#898781;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;            /* categorical, max 3 (scatter) */
--ord-1:#b7d3f6;--ord-2:#6da7ec;--ord-3:#3987e5;--ord-4:#1c5cab;     /* expiries, nearest = ord-1 */
--seq-0:#0d366b;--seq-1:#104281;--seq-2:#184f95;--seq-3:#256abf;--seq-4:#3987e5;--seq-5:#6da7ec;--seq-6:#9ec5f4;--seq-7:#cde2fb; /* P 0→1 */
--raw:#898781;--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;
--font:system-ui,-apple-system,"Segoe UI",sans-serif;--gutter:16px;--radius:8px;--radius-chip:4px}
```

- **Typography.** Use `font-variant-numeric: tabular-nums` on tables and axis ticks. Text always uses the ink tokens, never a series colour.
- **Layout.** Max width 1440 px on a 12-column grid with 16 px gutters. Cards use `--surface-1` with a 1 px `--border`. Below 768 px the layout is a single column and the scrubber is sticky at the bottom.
- **Status colours** appear only on flag chips and always with an icon and a label.
- **SVG fills** use `var(--…)` directly, so the tokens are the single source of colour.

### 5.2 Landscape view (`/landscape?u=SPY&d=YYYY-MM-DD&map=auto&view=both&layout=multiples&x=moneyness&exp=…`)
**Data sources.** `useSessions(u)` supplies the scrubber. The distribution, heatmap and chain queries are keyed by `(u, d, map)`.

**Control row**, one row above all content:
- Underlying `Select`.
- Map toggle: Auto | Production | Walk-forward.
- View toggle: Raw | Calibrated | Both.
- Layout toggle: Small multiples | Overlay.
- X-axis toggle: Moneyness | Strike $.
- When `look_ahead` is true, show the chip "in-sample map: fitted on outcomes after this session". When `map_is_identity` is true, show "no calibration (2020 burn-in)".

**(a) CDF and density.**
- **Grid.** 4 fixed slots, so the layout never jumps; an empty slot reads "No expiration in this slot".
- **Panel header.** "Oct 16 · 14d" plus the flag chips from `lib/flags.ts`:
  - `clipped` and `monotonicity_repaired` are info chips (neutral, ⓘ).
  - `left_tail_uncovered`, `right_tail_uncovered`, `sparse`, `forward_unknown` and `no_calls` are warning chips (⚠ with `--warning`).
  - Each chip has a tooltip with a one-line meaning.
- **Top plot, CDF:**
  - y from 0 to 100%. x domain fixed at moneyness 0.70 to 1.30, or the union of the session's knots in $.
  - The calibrated curve is a 2 px solid line in the expiry's `--ord-n`. The raw curve is a 1.5 px dashed `--raw` line.
  - Vertical hairlines mark the forward ("F 512.70", dashed `--ink-2`) and the close ("S", dotted).
  - When settled, a diamond marks the settlement close on the curve, labelled "settled $498.20 · P=0.31".
- **Bottom plot, density** (35% of the height, sharing x):
  - A step area at 0.25 opacity with a 2 px edge in the same ordinal colour, and the raw density as a dashed outline.
  - In moneyness mode, density is multiplied by the close (per unit of moneyness).
  - Two stacked plots, never a dual axis.
- **Hover.** A crosshair snaps to the nearest knot. One tooltip shows the value first: P cal, P raw, density, then the strike, moneyness and DTE.
- **Overlay layout.** All expiries share one CDF plot, with direct labels ("14d") at the right ends of the lines.

**(b) Heatmap.**
- Rows are expirations (nearest at the top) and columns are the 41 moneyness cells.
- Fill uses the sequential `--seq-0` to `--seq-7` ramp, interpolated with `interpolateLab`. Low values sit near the surface.
- Cells have a 2 px surface gap. Null cells get the 45° hatch from `@visx/pattern` and the tooltip "outside quoted strikes, not extrapolated".
- Ticks at `backtest_grid`. A 1.00 column outline marks ATM. A small tick marks each row's `forward_moneyness`.
- A colour-bar legend shows 0 to 100%.
- The variant follows the view toggle; "Both" shows the calibrated values.
- Per-cell tooltip: "P(S<K) 23.4% · K $585 · m 0.95 · Oct 16".

**(c) Smile.**
- x is shared with (a); y is IV in %, from 0 to the 99th percentile, nice-rounded.
- Only OTM quotes are drawn: puts for K < S, calls for K ≥ S, with `iv` non-null.
- 2 px lines in the ordinal colours with 8 px point markers and direct labels at the right ends.
- The crosshair tooltip lists every expiry.

**(d) Scrubber.**
- `SessionSparklines` shows two separate 40 px sparklines: close (`--ink-2`) and ATM IV. Both have a `--series-1` marker and a hairline at the current session; click or drag seeks.
- `Scrubber` controls: play/pause (Space), step (←/→), speed (1× = 4 fps, 2×, 4×), and stride (every session, weekly or monthly, taking the first session of each period).
- It includes `<input type=range>` with `aria-valuetext` set to the date, plus a date readout.
- **Playback state.**
  - `usePlayback({length, index, setIndex, fps, stride, isReady})` runs `setInterval(1000/fps)`.
  - If `isReady(next)` (all 3 queries are in the cache, checked with `queryClient.getQueryData`), it advances; otherwise it holds, so no blank frames.
  - It pauses at the end and does not loop.
  - On every index change it prefetches the next 6 strided sessions with `queryClient.prefetchQuery`.
  - While playing, the index lives in component state. On pause or a manual seek, it is written to the URL `d` with `replace: true`.
  - On an underlying change, it keeps `d` if present, otherwise uses the nearest earlier session (binary search).
  - Nothing autoplays, and `prefers-reduced-motion` caps speed at 1×.

**(e) Chain table.**
- Expiry tabs (a `SegmentedToggle` bound to `exp`). Straddle layout: Calls (bid, ask, mid, IV, Δ) | Strike (and moneyness) | Puts (bid, ask, mid, IV, Δ).
- The ATM row is highlighted. Unusable quotes are muted with the title "excluded: zero bid or crossed".

**While refetching**, the previous render stays at 0.6 opacity. There are no skeletons after the first load.

### 5.3 Spread explorer (`/spreads?u=…&exp=…&wmin=&wmax=&pop=&credit=&elig=1&hl=TSLA,MSFT&sel=<key>`)
**Filter row:**
- Underlying `MultiSelect`, Expiration `Select`, width min and max ($), min POP slider (0 to 1), min credit ($), and an "Eligible only" switch (default on).
- "Highlight" accepts up to 3 underlyings. The default is the distinct underlyings of the rank 1 to 3 rows.
- `CalibrationBadge` on this page reads: "ECE 3.5%→1.7% · Brier 0.127→0.129 (out of sample, 2021+)", with the confidence intervals in the tooltip.

**Scatter:**
- x = `prob_profit` (calibrated, %); y = `expected_roc` (expected return on max loss, %, holding period; the axis label reads "Expected return on max loss, holding period").
- When eligible-only is off, clamp y to [−100%, +100%]. Pin points beyond that at the edge with a ▲ or ▼ marker and the caption "n points beyond ±100% pinned".
- Size = credit: a sqrt scale from radius 4 to 12 px over [0, p95 credit].
- **Colour.** Highlighted underlyings use `--series-1/2/3` with the symbols circle, square and triangle. The slot is assigned in the order the underlying was added and kept while it stays highlighted. All other points are `--ink-muted` at 0.35 opacity and appear as "Other" in the legend.
- Reference lines: a dashed vertical line at `min_prob_profit` labelled "eligibility POP ≥ 50%", and y = 0.
- **Hover.** `@visx/voronoi` picks the nearest point within 24 px. The tooltip shows values first ("POP 70.0% · E[R/max loss] 12.9%") and then "MSFT 512.5/507.5 · Oct 16 · credit $1.90".
- **Click** selects the spread (`sel`). The selected point gets a 2 px surface ring and an ink ring.

**Table:**
- Columns: Rank, Underlying, Exp (DTE), Short/Long, Width, Credit, Natural, POP cal, POP raw, P(max loss), E[R/max loss], Ann. R/max loss, Kelly, Flags.
- Sorted by rank by default. Paginated 50 per page. Selecting a row is the same as clicking its point.

**Detail panel** (`useSpreadDetail(sel)`):
- **Stat tiles:** Credit (and natural), Max loss, Breakeven, POP cal (with raw), P(max loss), Exp. return on max loss (with raw), Interest, Kelly.
- **`PayoffChart`:**
  - Top: payoff at expiry ($/sh) as a 2 px `--ink-1` line with a zero baseline, and markers for long, short and breakeven.
  - Bottom: the calibrated density, filled `--series-2` at 0.30 left of the breakeven and `--series-1` at 0.30 right of it, with labels "P(loss) 41.9%" and "P(profit) 58.1%". The raw density is a dashed outline, the close is marked "S", and the forward "F".
  - Shared x, two stacked plots.

### 5.4 Error states
- 503 `database_busy`: "dbt is writing the database. Retrying in 15 s…". Retries are automatic and the last frame stays visible.
- `database_missing`: "No gold data yet: run `make dbt-build-local`".
- Stale data: `DataStatus` shows "Showing cached data while dbt writes".

## 6. Tests
**API (`tests/api/`, pytest with TestClient).**

`conftest.py` is a module-scoped fixture that builds `tmp_path/oap.duckdb` from pandas:
- `gold.fct_option_quote`:
  - Two symbols ("SPY", "XLF"), 3 sessions each and 3 expirations, from `tests.analytics.frames.lognormal_quotes`.
  - Add `mid=(bid+ask)/2`, `source_iv=vol`, `source_delta` from `oap.engine.black_scholes.delta` and `moneyness`.
  - Make `strike` `DECIMAL(10,3)`.
  - Include one expiry with only 3 usable puts and one with `dte_days=3`.
- `gold.dim_underlying`.
- `gold.fct_expiration_outcome`, with the first expiry settled.
- `gold.calibration_map`: production (non-identity, fitted with `fit_isotonic_calibration` on `synthetic_predictions`), plus `fold_2024` and `fold_2020` identity, with the metadata columns.
- `gold.calibration_metrics`: overall rows.
- `gold.spread_scores`: `to_output(score_latest_session(latest_quotes, production), OUTPUT_SCHEMAS["spread_scores"])`.

The app is `create_app(ApiSettings(duckdb_path=..., web_dist=tmp_path/"dist"))`.

| File | Tests |
|---|---|
| `test_landscape.py` (pure) | <ul><li>Curve knots and cdf equal `chain_cdf(...)` exactly (the same-path contract).</li><li>`cdf_calibrated == apply_calibration(cdf, map).prob_below_array(knots)`.</li><li>An identity map gives calibrated equal to raw.</li><li>Heatmap is null outside the knots and equals `prob_below_array` inside.</li><li>`too_few_puts`, `expired` and `short_dated` are reported.</li><li>NaN forward becomes `None`.</li><li>`pick_map` chooses auto (latest → production, else fold), falls back to identity and sets `look_ahead`.</li><li>`atm_iv` selection.</li></ul> |
| `test_routes_meta.py` | `/healthz`; underlyings sorted with counts; calibration summary matches the fixture. |
| `test_routes_landscape.py` | <ul><li>Sessions ascending with the close.</li><li>Chain grouping and ordering.</li><li>Distribution and heatmap shapes.</li><li>404 for an unknown symbol or session; 422 for a bad symbol pattern or date.</li><li>Each fixture response is under 64 KB.</li><li>A second call for the same session opens no connection (count `duckdb.connect` with monkeypatch).</li></ul> |
| `test_routes_spreads.py` | <ul><li>Default `eligible_only`; each filter on its own.</li><li>Ordering.</li><li>Detail by an encoded key; 1 − calibrated F(breakeven) from the bundle equals `prob_profit` within 1e-9.</li><li>Payoff equals credit above the short strike and −max_loss below the long strike.</li><li>An infinite `annualised_roc` serialises as `null`.</li><li>404 for an unknown key.</li></ul> |
| `test_lock.py` | <ul><li>Monkeypatched connect raising `duckdb.IOException("Could not set lock on file … Conflicting lock is held")` gives 503, `Retry-After: 15` and `code=database_busy`.</li><li>**Real lock:** a subprocess `python -c "import duckdb,sys,time; c=duckdb.connect(sys.argv[1]); print('ready', flush=True); time.sleep(30)"` holds the write lock. Wait for "ready", assert 503, then terminate it.</li><li>Stale: warm the cache, then `os.utime` the file and make connect busy; expect 200 with `X-OAP-Data-Stale: 1`.</li><li>Missing file gives 503 `database_missing`.</li></ul> |
| `test_static.py` | With `dist/index.html`: `/` and `/spreads` return the HTML, and `/api/nope` returns a JSON 404. Without dist: `/` returns a JSON hint. |
| `test_openapi.py` | The committed file equals the generated one; the message says "run make api-schema". |
| `test_settings.py` | Environment defaults and parsing. |

**Web (Vitest).** Shared setup:
- `setup.ts` loads jest-dom and stubs `ResizeObserver`, `matchMedia` and `SVGElement.prototype.getComputedTextLength = () => 0`.
- The MSW node server serves the fixtures.

Test files:
- `client.test.ts`: JSON parsing; 503 maps to an `ApiError` with `retryAfterS`; 404 is not retried; the stale header updates `dataStatus`.
- `queries.test.ts`: the retry predicate and the stability of the key factory.
- `usePlayback.test.ts` (fake timers): advances by stride, holds when the next session is not ready, stops at the end, pauses.
- `useLandscapeParams.test.ts`: defaults (SPY, latest) and the nearest-earlier session on an underlying switch.
- `format.test.ts` and `flags.test.ts`.
- `ProbabilityHeatmap.test.tsx`: cell count, hatch class on nulls, `aria-label`.
- `CdfPanel.test.tsx`: both paths in "both" view, the forward label, the chips.
- `SpreadScatter.test.tsx`: highlight slots, muted others, pinned count, `onSelect`.
- `Scrubber.test.tsx`: Space and arrow keys, `aria-valuetext`.
- `DataTable.test.tsx`: sort and `aria-sort`.
- `LandscapePage.test.tsx`: renders the fixture; the 503 busy message.
- `SpreadsPage.test.tsx`: a filter change updates the request query; selecting a row opens the detail panel.

## 7. Tooling snippets
**`pyproject.toml`:**
```toml
api = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.32,<1",
    # Same DuckDB as the dbt writer (uv.lock and docker/requirements-dbt.txt); the file format must match.
    "duckdb==1.5.6",
]
```
- Add `"api"` to `[tool.uv] default-groups`.
- Add `"apps/web/node_modules"` to ruff `extend-exclude` (node_modules can contain `.py` files).
- Then run `uv lock`, `make lock-export` and `make lock-check`. The exports should not change (`--no-default-groups` and `--only-group dbt,report`), so there is no image rebuild; confirm `git diff docker/` is empty.

**Makefile.** Add to `.PHONY`: `api web web-install app web-build web-check api-schema serve`.
```make
API_ENV := OAP_DUCKDB_PATH=$(CURDIR)/.dbt-local/oap.duckdb
api: ## Explorer API with reload on :8000 (reads .dbt-local/oap.duckdb read-only)
	$(API_ENV) uv run uvicorn oap.api.main:app --reload --reload-dir src --host 127.0.0.1 --port 8000
web-install:
	@test -d apps/web/node_modules || npm --prefix apps/web ci
web: web-install ## Vite dev server on :5173, proxying /api to :8000
	npm --prefix apps/web run dev -- --port 5173 --strictPort
app: ## API and web dev servers together (Ctrl-C stops both)
	$(MAKE) -j2 api web
web-build: web-install ## Build apps/web/dist
	npm --prefix apps/web run build
web-check: web-install ## Web lint, format, typecheck, tests, schema drift and build
	npm --prefix apps/web run check && npm --prefix apps/web run build
api-schema: ## Regenerate apps/web/openapi.json and src/api/schema.ts
	uv run python scripts/export_openapi.py --out apps/web/openapi.json
	npm --prefix apps/web run gen:api
serve: web-build ## One process: built explorer and API on :8000
	$(API_ENV) uv run uvicorn oap.api.main:app --host 127.0.0.1 --port 8000
```
- `--reload-dir src` stops reloads when dbt writes `.dbt-local`.
- `make check` stays Python-only, so the API tests run in it.

**CI (`.github/workflows/ci.yml`), new job:**
```yaml
  web:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: apps/web } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22", cache: npm, cache-dependency-path: apps/web/package-lock.json }
      - run: npm ci
      - run: npm run check
      - run: npm run build
```

**Ignore files and pre-commit:**
- `.gitignore`: add `node_modules/`, `apps/web/dist/` (already matched by `dist/`; explicit for clarity), `apps/web/coverage/` and `*.tsbuildinfo`.
- `.dockerignore`: **no change**. It is an allowlist (`*` then `!src/…`), so `apps/` is already excluded. Say this in the ADR.
- `.pre-commit-config.yaml`:
  - Add `|apps/web/package-lock\.json` to the detect-secrets `exclude` (integrity hashes trip the entropy check).
  - Add `exclude: ^apps/web/package-lock\.json$` to `check-added-large-files`.

**Docs (A):**
- README:
  - An "Explorer" section after Results: what it shows, `make app` and `make serve`, the 127.0.0.1-only binding (vendor terms: personal analysis), and `![Explorer](docs/img/explorer.png)`.
  - Rows in the Repo layout table and the Checks table.
  - Updated test counts.
- Runbook "## Explorer": start and stop, ports, 503 and stale behaviour, "do not leave the explorer playing during `make dbt-build-local`", and how to regenerate the schema.
- Architecture: an Explorer component row.
- ADR 0011 (Nygard format, like 0010): React+FastAPI over Streamlit or Marimo; visx over Plotly; host processes instead of a container; a read-only DuckDB with short-lived connections, in-memory serving, the 503/stale contract and `Retry-After`; the auto/walk-forward map choice and `look_ahead`.
- `docs/img/explorer.png` breaks the CLAUDE.md rule that `docs/img` is generated by `make report`. Document it as the one hand-captured image (the user should confirm the CLAUDE.md edit).

## 8. Acceptance criteria and commands
1. `uv sync --all-groups --locked && make check` is green, including `tests/api`, and `make lock-check` shows no diff.
2. `make web-check` is green. Vite build output: largest JS chunk under 250 KB gzip and the landscape and spreads chunks split.
3. `make app`, then open http://localhost:5173 in the built-in browser:
   - **/landscape:** SPY at 2026-10-02 shows 4 CDF panels with F and S markers and chips, the heatmap, the smile and the straddle table.
   - **Playback:** Play from 2020-02-03 with monthly stride animates smoothly, and the network panel shows prefetches ahead of the frame.
   - **Map toggle:** switching it changes `map_id`.
   - **/spreads:** shows 1,141 eligible rows by default. Rank 1 is "TSLA 370/367.5", POP 58.1% (raw 51.1%), E[R/max loss] 14.38%. Its detail shows the payoff over the density.
4. **Busy path.** `curl -i localhost:8000/api/underlyings` while `make dbt-build-local` runs returns 503 with `Retry-After`. A warm session returns 200 with `X-OAP-Data-Stale: 1`. After the build finishes, data refreshes on its own.
5. `make serve`: http://localhost:8000/spreads loads directly through the SPA fallback.
6. The integrator captures `docs/img/explorer.png` (landscape at 1440 px wide) and commits it.

## 9. Risks
- **DuckDB lock in both directions.** A held read connection blocks the dbt writer, so connections are opened per load, closed at once and serialised. After the first load per underlying, scrubbing reads memory only. If the writer collides anyway, `dbt_build` has `retries=1`. Locks across the Colima bind mount may not propagate, so test on the host and document "pause playback during host builds".
- **Calibrated knot blow-up.** About 400 knots per expiry if sent raw, so always evaluate at the raw knots.
- **Non-finite JSON.** Use `ser_json_inf_nan="null"` and `float | None`. The test with an infinite `annualised_roc` covers it.
- **Scatter outliers.** The return on max loss reaches 4.5e13, handled by eligible-only by default plus y-clamping with pinned markers.
- **jsdom.** `ResizeObserver`, `matchMedia` and `getComputedTextLength` are stubbed. Charts take explicit sizes in tests, and there is no canvas.
- **CORS in dev.** Not needed: Vite proxies `/api`. The CORS middleware is opt-in through `OAP_API_CORS_ORIGINS`.
- **Large sessions.** The maximum is 266 quotes; `limit` caps spreads at 5000 rows, and gzip is on.
- **Node version.** v24 runs locally and CI uses 22, so `engines >=22`.
- **package-lock size and detect-secrets.** Handled by the excludes above.
- **Bundle.** visx is imported per subpackage. Never import `d3` whole.
- **Production map on history is in-sample.** Default `auto` uses walk-forward, and the `look_ahead` chip explains it.
- **Screenshot.** It shows derived vendor data. The README already publishes derived tables, so the same personal-analysis note covers it.
