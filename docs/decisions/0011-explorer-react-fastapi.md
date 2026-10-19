# 0011. The explorer is React over FastAPI, on a read-only DuckDB

Status: Accepted
Date: 2026-10-19

## Context

The report (`docs/results.md`) shows two figures and a table. It cannot show what the calibration does to one chain on one day, how the implied distribution moves from session to session, or why one spread ranks above another. Those questions need an interactive view: the risk-neutral CDF of each expiration beside its calibrated CDF, a heatmap of P(S < K), the volatility smile, and the ranked spreads with the payoff of each. The data is already in the `gold` schema of `.dbt-local/oap.duckdb`, and every number can be computed by the tested functions in `oap.engine` and `oap.analytics`.

Four constraints shape the design. The view must animate through years of sessions, so scrubbing has to be fast and cannot wait for a database. The calibration code must not be duplicated: a number on screen has to be the number the backtest produced. `oap.duckdb` accepts one writer, and `dbt_build` and `score_spreads` own it (ADR 0008, ADR 0010), so any reader that keeps the file open can make a build fail. And the data is derived from vendor quotes that are for personal analysis only, so the service must not be reachable from the network.

Measurements on the real file decided the details. A session has at most 266 quotes and 3 to 4 expirations. `chain_cdf` takes about 7 ms for three expirations. All of one underlying's quotes (about 170,000 rows, about 22 MB in pandas) load in about a second cold and tens of milliseconds warm, and opening and closing a read-only connection takes about 9 ms. Composing the production calibration map with a CDF gives about 400 knots per expiration, because the map has 368.

## Decision

**React and a FastAPI service, not Streamlit or Marimo.** Streamlit reruns the script on each interaction and Marimo is reactive per cell; neither gives a scrubber that plays through lazily fetched sessions with prefetch and a stable layout, and both put the chart code in Python where it cannot be tested with a DOM. The API is a thin layer over `oap.analytics`: the same `chain_cdf` the backtest calls, and `apply_calibration` evaluated at the raw knots. The web app is `apps/web` (Vite, React 18, TypeScript, TanStack Query), and its types are generated from the API's OpenAPI document so the two cannot drift: `scripts/export_openapi.py` writes `apps/web/openapi.json`, a pytest compares it with the live app, and `npm run check:api` compares the generated types with it.

**visx, not Plotly.** The animation is a scrubber over sessions that are fetched lazily; `Plotly.animate` needs precomputed frames and does not tween heatmaps, while a React render per session is natural with visx. The smallest Plotly bundle with a heatmap is about 400 KB gzipped; the visx subset is about 60 KB. Plotly needs heavy templating to avoid its default dashboard look, and its output cannot be queried in jsdom, whereas visx renders SVG that Testing Library can assert on. The heaviest view is about 3,300 scatter points and a heatmap of at most 4 by 41 cells, so WebGL is unnecessary. The cost is more chart code, six chart components, and a voronoi for hover.

**Host processes, not a container.** `make app` and `make serve` run `uvicorn` and Vite on the host, bound to `127.0.0.1`. A container would add an image, a port mapping and a bind mount across which DuckDB's file locks may not propagate, for a tool used by one person on one machine. The binding is deliberate: the data is for personal analysis only, so nothing but the local user can reach the service. `.dockerignore` is an allowlist (`*` then `!src/...`), so `apps/` is already excluded from every image and needs no change.

**A read-only DuckDB with short-lived connections.** `GoldReader` opens the file with `read_only=True`, runs its parameterised queries and closes the connection in the same call. `GoldStore` is the only caller. One `RLock` guards the caches and the database reads, so at most one connection is ever open. Entries are keyed by the file signature (modification time, size, WAL size), taken with `os.stat` and no lock. Per signature, the table groups (underlyings, spreads, maps, metrics) load once, one underlying's quotes and outcomes live in a 3-entry LRU, and computed sessions (chain, distributions, heatmap) in a 256-entry LRU of about 40 KB each. After the first load of an underlying, scrubbing and playing never touch the database.

**Locked means 503 or stale, never a hang.** When a writer holds the lock, a read raises `DatabaseBusy`. If the signature changed but an entry exists for the last good signature, the store serves it with the header `X-OAP-Data-Stale: 1`. Otherwise the API returns `503` with `Retry-After: 15` and `{"code": "database_busy"}`. A missing file is `503` `database_missing` and a missing gold table is `503` `gold_missing`. `/healthz` always answers `200` and reports `db` as `ok`, `busy` or `missing`. The web app retries only `database_busy`, at most 8 times, and keeps the last frame, so a build running behind it shows a message and then recovers.

**Same CDF path as the backtest; the calibrated curve is evaluated at the raw knots.** Per expiration the API calls `chain_cdf` at the configured risk-free rate, then `apply_calibration`, and returns the raw knots with the raw, repaired and calibrated CDFs at those knots. It never sends the composed knots. The heatmap evaluates both curves at `moneyness * close` rounded to 1e-6 dollars and is null outside the quoted strikes, the backtest's no-extrapolation rule. A spread's detail is built from the same CDFs, so `1 - F_calibrated(breakeven)` equals the `prob_profit` in gold.

**Map choice is `auto`, and a response says when it looked ahead.** The production map is fitted on every settled prediction, so showing history through it is in-sample (ADR 0010). `auto` therefore uses `production` for the latest session and the walk-forward map `fold_<year>` for any earlier one; `production` and `walk_forward` force either. A response carries `map_id`, `map_is_identity` (the 2020 burn-in map is the identity) and `look_ahead`, which is true when the map's latest training expiration is after the session, so the app can label an in-sample view.

**`look_ahead` compares the map's training window with the session.** `look_ahead` is true when the map's latest training expiration is after the session date. An outcome that settles on the session itself was known at the close the quotes were taken, so a map trained through that expiration is not looking ahead for that session, and the flag stays false.

**`auto` keys off the global latest session.** The production map is defined on the global sample: it is fitted on every settled prediction across all underlyings, not per underlying. `auto` therefore compares the session with the latest session of the whole table, not of the selected underlying, so any earlier session is shown through the walk-forward map.

**Non-finite numbers are null.** `gold.spread_scores` holds extreme values: `expected_roc` reaches 4.5e13 across all rows, and `annualised_roc` can be infinite. Response models serialise with `ser_json_inf_nan="null"` and type any float that can be non-finite as `float | None`. The spread list is eligible-only by default, which keeps `expected_roc` between 0.002 and 0.37, and the scatter clamps the rest.

## Consequences

Good:

- Every number on screen is computed by the code the backtest ran, so the explorer cannot disagree with `docs/results.md`, and a test compares the API's output with `chain_cdf` and `apply_calibration` directly.
- The explorer cannot block a build for longer than one load, and a build cannot hang the explorer. A real lock held by a subprocess is in the test suite.
- The OpenAPI document is a committed contract. A model change that is not regenerated fails `make check`, and the web app's types follow without a hand-written client.
- The bundle stays small, and chart tests run in jsdom without canvas or WebGL stubs.

Costs and risks:

- A second toolchain. `apps/web` needs Node 22 or later and an `npm ci`; `make check` stays Python-only, and the web checks run as `make web-check` and the CI `web` job.
- More chart code than a Plotly or Streamlit version, and hover through a voronoi.
- A reader can still collide with a writer. A load that lands as a build starts can make the writer's open fail, and `dbt_build` has one retry after 2 minutes where a host build has none. The mitigation is behavioural: do not leave the explorer playing during `make dbt-build-local`.
- Locks across a Colima bind mount may not propagate, so the protection is tested for host processes; the runbook says to pause playback during container builds.
- The first load of an underlying holds the one lock for up to about a second, and requests behind it wait. That is acceptable for one user and is the price of at most one open connection.
- Memory: the caches hold about 22 MB per cached underlying (3 of them) plus the session LRU.
- `docs/img/explorer.png` is a hand-captured screenshot, the one file in `docs/img/` that `make report` does not generate. It shows derived data, which the README already publishes as tables under the same personal-analysis note.
- `look_ahead` compares the map's latest training expiration with the session, so the production map on the latest session reports `false` when its newest training expiration is that session itself: that outcome was known at the close the quotes were taken.

## Alternatives considered

**Streamlit or Marimo.** Rejected: see above. They would be quicker to write and could call `oap.analytics` directly, but the animation, the stable layout and the DOM-level tests are the point of the tool.

**Plotly (`plotly.js-cartesian-dist-min`) in React.** Rejected: about 400 KB gzipped, no tweened heatmap, canvas and `URL.createObjectURL` stubs in tests, and a heavy theme to look like anything but a default dashboard.

**Hold one read-only connection open and query per request.** Rejected: it blocks the dbt writer for as long as the service runs, and `dbt_build` and `score_spreads` would fail on every open. Short-lived connections and an in-memory cache cost one load per underlying.

**Precompute every session into static JSON during the report.** Rejected for v1: about 1,200 sessions by 11 underlyings by three maps is a large generated artefact with its own staleness, for a tool that already loads in about a second. The API can still produce it later.

**Recompute the spreads of any session in the API.** Not in v1. `gold.spread_scores` covers the latest session only. A recomputation endpoint (`score_latest_session` with the walk-forward map, `source="recomputed"`) is the planned extension once the first version is accepted.

**Containerise the API and the web app.** Rejected: see above.
