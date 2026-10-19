# 0010. Analytics as dbt Python models over a pure `oap.analytics` core

Status: Accepted (Phase 3)
Date: 2026-10-19

## Context

Phase 3 has to answer one question with the data already loaded: do the probabilities implied by option prices match what happened, and if not, which spreads does a corrected probability favour? The engine functions in `oap.engine` (ADR 0009) compute a risk-neutral CDF for one chain. Something has to run them over every chain in `fct_option_quote` since 2020, pair each prediction with the settlement close in `fct_expiration_outcome`, fit a calibration map without peeking at the future, score the latest session, and publish the results where the report can read them.

Four constraints shape the placement and the method. `oap.duckdb` accepts one writer at a time, and the Airflow stack already serialises it through the dbt build (ADR 0008). The outputs are derived tables, so they should have lineage, descriptions and tests like every other gold table. Calibration is an estimate from outcomes that arrive over time, so a careless split leaks the future into the map and makes the result look better than any live use could be. And the rate that discounts the strikes is a market quantity the bronze layer does not hold yet.

## Decision

**Placement.** The analytics are seven dbt Python models in `dbt/models/analytics/`, tagged `analytics`, each a thin wrapper that reads its upstream with `dbt.ref(...)`, calls a function in `src/oap/analytics/`, and returns a frame. The package holds all logic: `sample` builds snapshots and predictions, `backtest` fits maps and computes metrics, `scoring` ranks the latest session, `config` holds every parameter, and `io` is the only module that touches a relation, through a duck-typed protocol, so it needs no `duckdb` import. The models are `calibration_snapshot`, `calibration_prediction`, `calibration_map`, `calibration_sample`, `calibration_metrics`, `calibration_bins` and `spread_scores`. They run in dbt-duckdb's in-process Python runner, and `dbt_project.yml` disables them on any other target. The dbt tests (the leakage gate `assert_calibration_out_of_sample`, `assert_calibration_map_monotone`, `assert_predictions_from_ok_snapshots`, `assert_spread_rank_contiguous` and the column tests) run with them.

**Orchestration.** `dbt_build` excludes `tag:analytics`. When its models and tests pass, `publish_gold` updates the `GOLD` Dataset, and `score_spreads` runs `dbt build --select tag:analytics`, then `scripts/make_report.py`. Both DAGs run in the one-slot `duckdb_writer` pool. A failed analytics test fails the task, which has no retries because the verdict does not change on a second try.

**Calibration.** Walk-forward and annual. The map applied to predictions made in year Y is fitted only on predictions whose expiration is before 1 January of Y, so every outcome it saw was known when the year began. 2020 is burn-in: its map is the identity or thinly fitted, and its rows are excluded from every metric. The first test year is 2021. The method is monotone isotonic regression from the engine, and a map fitted on fewer than 50 predictions is the identity. A separate `production` map, fitted on every settled prediction, scores the latest session. Out-of-sample quality is reported as Brier score, log loss and expected calibration error for the raw and the calibrated probabilities, overall and by underlying, days-to-expiry bucket and fold year, with a 95% cluster-bootstrap interval that resamples expiration dates.

**Sampling.** Each usable snapshot (one underlying, trade date and expiration) is evaluated on a moneyness grid: 13 strikes from 0.800 to 1.100 times the close in steps of 0.025. The prediction at a strike is P(S_T < K) from the CDF, and the label is whether the settlement close was strictly below K. A target outside the strike range the CDF covers is skipped, never extrapolated. Snapshots are excluded, and counted by reason, when the expiration is under 7 days away, the close is missing, fewer than 4 usable puts exist, the expiration has not settled, a daily move beyond 0.4 in log terms falls inside (trade date, settlement] (an unadjusted split, ADR 0007), or the quote predates the current company behind a reused ticker (META before 2022-06-09).

**Rate.** One constant, `risk_free_apy = 0.045`, builds every CDF, and `cash_apy = 0.036` is the interest on spread collateral. The spread score reported to readers is the return on max loss (`expected_roc`, `annualised_roc`; collateral equals max loss), and the column names keep the shorter identifiers. The error from a constant is small: at the longest horizon in the data (about 67 days) it moves the forward by at most 0.8% relative against a zero rate, and by about 0.35% at the median horizon. The calibration map is fitted on outcomes computed with the same constant, so it absorbs the average bias. Phase 4 will load the 3-month T-bill yield (FRED DTB3) into bronze and use each trade date's rate.

## Consequences

Good:

- The statistics are testable without a warehouse. `oap.analytics` takes and returns frames, so its tests build small frames by hand, and `hypothesis` covers the engine beneath it.
- The outputs have the same lineage, descriptions and tests as the rest of gold, and `make check` builds them on synthetic data, including the report, so a schema drift between a model and the report's SQL fails the gate.
- DuckDB has one writer. The two DAGs and the host commands share one pool and one rule.
- A leak is a failing test, not a judgement call: the leakage gate compares every fold map's latest training expiration with the first trade date it is applied to.
- Every exclusion is a count in `calibration_snapshot`, so the report shows how much data each rule removed.

Costs and risks:

- The models run on DuckDB only. On Snowflake they are disabled, and nothing has been compiled or run as Snowpark Python models. Phase 4 will port them; the pure core should carry over unchanged, but the `io` module and the dbt wrappers will not.
- Samples are correlated. One snapshot contributes up to 13 nested targets, several underlyings share an expiration date, and the market moves together on that date. The bootstrap resamples expiration dates, which widens the interval honestly, but the point estimates are still means over dependent rows and the effective sample is much smaller than the row count.
- The universe has hindsight. The watchlist is today's large caps and liquid ETFs, which biases the realised downside frequency low and makes the calibrated map optimistic. The report names this as the most important caveat. A calibrated edge here is a measurement on survivors, not a forecast of live returns.
- One pooled map serves every underlying and expiry. The segment tables show where it fits worse. A per-underlying map would be fitted on a fraction of each fold's predictions; it is left for when the segment tables show the pooled map failing.
- The production map is fitted on every settled prediction, so scoring the latest session with it is in-sample by construction. The walk-forward folds are the honest evidence for it.
- A constant rate leaves a small, time-varying bias in the CDF that the map only absorbs on average.
- Python models need `numpy` and `pandas` in the dbt virtualenv and `oap` installed into it, which the Airflow image does (`docker/requirements-dbt.txt`). A run outside the image needs the same.

## Alternatives considered

**An Airflow Python task that reads gold and writes result tables to DuckDB.** Rejected. It is a second writer to `oap.duckdb` that dbt does not know about, so the results would have no lineage, no schema descriptions and no tests, and a task and a dbt run could collide on the file lock. It also splits the pipeline into a dbt half and a hand-written half, which is the structure dbt Python models exist to avoid.

**Sample every listed strike instead of a moneyness grid.** Rejected. Strike density differs by underlying and day, so deep, dense chains would dominate the sample and the pooled map would learn the chains with the most strikes. Raw strikes are also not comparable across underlyings and dates. A fixed grid of moneyness gives each snapshot the same targets and keeps the sample size per snapshot bounded, at the price of reading the CDF between strikes by interpolation, which the engine already does.

**A single train/test split.** Rejected. One cutoff date makes the result depend on where it falls, tests on a single regime, discards the later data from training, and cannot show drift. Walk-forward fits the map the way it would have been fitted at each year's start, so the yearly rows of `calibration_metrics` show whether the effect is stable or comes from one year.

**scipy for isotonic regression and the bootstrap.** Rejected, for the reason given in ADR 0009: a compiled dependency to hold at the lock's version in an image whose base pins numpy, for routines that are short in numpy. The engine already has a weighted pool-adjacent-violators implementation, and the bootstrap needs a seeded random generator and resampling, which numpy provides.

**A per-date risk-free rate now.** Deferred, not rejected. It needs a new bronze table, a loader and a decision about gaps, and the size of the bias (under 1% of the forward) does not justify holding the backtest for it. Phase 4 adds it.
