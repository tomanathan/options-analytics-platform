"""Growth lab: score every long call and put once, then sweep growth-sized selection rules.

Steps 2 and 3 of the growth lab (``docs/design/growth-lab.md``); step 1 is
``scripts/regime_calibration.py``, whose decision and maps this script reads from
``--lab-dir``. A one-time study, not a pipeline step, in two stages that can run together:

* ``--score`` opens the DuckDB file read-only and, for every session from ``--start`` with an
  ok snapshot, runs ``oap.analytics.growth.score_session``: every usable call and put inside
  the CDF knots is scored at the ask under the step-1 map of its trade date's year (and
  regime, when the regime maps won; the pooled map is then scored alongside), and settled at
  expiry. The scored options go to ``scored_options.parquet/`` in ``--lab-dir`` as one parquet
  part per year, with ``score_meta.json``.
* ``--sweep`` reads the parts (only the columns it needs), evaluates the rules of
  ``oap.analytics.growth_rules.rule_grid`` (the first ``--grid-limit`` when given), writes every
  result to ``sweep.csv`` in ``--lab-dir`` and renders ``--out`` with
  ``img/growth_lab_holdout.png`` next to it. Rules are chosen on the dev years only (before
  ``--holdout-year``) and reported on the hold-out.

Units: prices in dollars per share; returns on premium, growth and drawdowns as decimals in
the data and percentages in the text; log growth in nats per session; time in calendar days.

Usage: ``python -m scripts.growth_lab --score [--db .dbt-local/oap.duckdb] [--start
2021-01-04]`` then ``python -m scripts.growth_lab --sweep [--out docs/growth-lab.md]
[--grid-limit N] [--holdout-year 2025] [--min-dev-trades 400]``, both with ``[--lab-dir
.dbt-local/growth-lab]``.
Exit codes: 0 on success; 2 when the database, a table, a step-1 file or the cache is missing
or the database is locked; 3 when a scored option used a map that could have seen its outcome.
"""

import argparse
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from oap.analytics.backtest import maps_from_frame
from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.growth import (
    F_MAX,
    POOLED_SUFFIX,
    QUOTE_IV_COLUMNS,
    leaking_options,
    score_session,
)
from oap.analytics.growth_rules import (
    OPTION_COLUMNS,
    TOP_NS,
    VARIANT_COLUMNS,
    GrowthRule,
    Picks,
    PreparedOptions,
    Sizing,
    beat_counts,
    describe_rule,
    evaluate_positions,
    flatten,
    holdout_line,
    pick_rules,
    prepare,
    random_positions,
    ranked_positions,
    rule_fields,
    rule_grid,
    select_positions,
)
from oap.analytics.io import QUOTE_SELECT, read_outcomes, read_table
from oap.analytics.regime_calibration import REGIME_LABELS
from scripts.backtest_entry_rule import (
    BLUE,
    GREY,
    INK,
    INK_MUTED,
    ORANGE,
    fmt_count,
    fmt_fixed,
    fmt_missing,
    fmt_percent,
    fmt_table,
    missing_tables,
    months,
    ok_sessions,
    save_figure,
    style_axes,
)
from scripts.regime_calibration import DECISION_FILE, MAPS_FILE, REGIME_FILE

TABLES: Final[tuple[str, ...]] = (
    "fct_option_quote",
    "fct_expiration_outcome",
    "calibration_snapshot",
)
"""Tables of the ``gold`` schema the scoring stage reads."""

SCORED_DIR: Final = "scored_options.parquet"
META_FILE: Final = "score_meta.json"
SWEEP_FILE: Final = "sweep.csv"
HOLDOUT_IMAGE: Final = "img/growth_lab_holdout.png"
SCORE_PROGRESS_EVERY: Final = 50
SWEEP_PROGRESS_EVERY: Final = 2000
TOP_RULES: Final = 10
RANDOM_LABEL: Final = "random"
RANDOM_CALLS_LABEL: Final = "random calls"

SNAPSHOT_SQL: Final = (
    "select underlying, trade_date, expiration, status from gold.calibration_snapshot"
)
MONTH_SQL: Final = (
    QUOTE_SELECT.replace(" from quotes", ", cast(source_iv as double) as source_iv from quotes")
    + " where trade_date >= DATE '{first}' and trade_date <= DATE '{last}'"
)
SUMMARY_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "right",
    "regime",
    "expected_return",
    "growth_rate",
    "growth_rate_market",
    "kelly_fraction",
    "realised_return",
    "tail_share",
    "is_out_of_sample",
)


def _log(message: str) -> None:
    """Write a progress line to standard error."""
    print(message, file=sys.stderr)


# --- step-1 inputs ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepOneOutputs:
    """What step 2 needs from step 1.

    Attributes:
        chosen: ``pooled`` or ``regime``.
        decision: The decision file's content.
        map_table: Every map, pooled and per regime (``regime_maps_to_frame``).
        features: Regime features.
    """

    chosen: str
    decision: dict[str, object]
    map_table: pd.DataFrame
    features: pd.DataFrame


def read_step_one(lab_dir: Path) -> StepOneOutputs | None:
    """Read step 1's decision, maps and features, or return None when a file is missing."""
    paths = [lab_dir / name for name in (DECISION_FILE, MAPS_FILE, REGIME_FILE)]
    if not all(p.exists() for p in paths):
        return None
    decision = json.loads(paths[0].read_text())
    return StepOneOutputs(
        chosen=str(decision["chosen"]),
        decision=decision,
        map_table=pd.read_parquet(paths[1]),
        features=pd.read_parquet(paths[2]),
    )


# --- scoring ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreMeta:
    """Counts and timings of the scoring stage.

    Attributes:
        chosen: The map scored (``pooled`` or ``regime``).
        sessions: Sessions scored.
        snapshots: Ok snapshots seen.
        skipped: Ok snapshots without a scored option.
        rows: Scored options.
        first_session: First session, ISO date, or None.
        last_session: Last session, ISO date, or None.
        runtime_seconds: Wall time of the scoring loop in seconds.
    """

    chosen: str
    sessions: int
    snapshots: int
    skipped: int
    rows: int
    first_session: str | None
    last_session: str | None
    runtime_seconds: float


def _write_part(scored_dir: Path, year: int, parts: list[pd.DataFrame]) -> int:
    """Write one year's scored options as a parquet part; return the row count."""
    frame = pd.concat(parts, ignore_index=True)
    frame.to_parquet(scored_dir / f"{year}.parquet", index=False)
    return len(frame)


def score_all(
    con: duckdb.DuckDBPyConnection, inputs: StepOneOutputs, scored_dir: Path, *, start: date
) -> tuple[ScoreMeta, pd.DataFrame]:
    """Score every session from ``start`` and write one parquet part per year.

    Args:
        con: Read-only connection to a DuckDB file with the ``gold`` schema.
        inputs: Step 1's outputs.
        scored_dir: Directory of the parts; existing parts are replaced.
        start: First session scored.

    Returns:
        The counts and the ``(map_id, trade_date)`` pairs scored, for the leakage check.
    """
    snapshots = read_table(con.sql(SNAPSHOT_SQL))
    outcomes = read_outcomes(con.table("gold.fct_expiration_outcome"))
    maps = maps_from_frame(inputs.map_table)
    sessions = ok_sessions(con, start)
    scored_dir.mkdir(parents=True, exist_ok=True)
    for old in scored_dir.glob("*.parquet"):
        old.unlink()
    year_parts: list[pd.DataFrame] = []
    used: list[pd.DataFrame] = []
    year: int | None = None
    rows = snaps = skipped = done = 0
    began = time.monotonic()
    _log(f"scoring {len(sessions)} sessions from {start.isoformat()} with the {inputs.chosen} map")
    rel = con.table("gold.fct_option_quote")
    for month in months(sessions):
        sql = MONTH_SQL.format(first=month[0].isoformat(), last=month[-1].isoformat())
        quotes = read_table(rel.query("quotes", sql))[list(QUOTE_IV_COLUMNS)]
        for day in month:
            if year is not None and day.year != year and year_parts:
                rows += _write_part(scored_dir, year, year_parts)
                year_parts = []
            year = day.year
            session = quotes.loc[quotes["trade_date"] == pd.Timestamp(day)]
            result = score_session(
                session,
                snapshots,
                outcomes,
                inputs.features,
                maps,
                DEFAULT_CONFIG,
                chosen=inputs.chosen,
            )
            snaps += result.snapshots
            skipped += result.skipped
            if not result.options.empty:
                year_parts.append(result.options)
                used.append(result.options[["map_id", "trade_date"]].drop_duplicates())
            done += 1
            if done % SCORE_PROGRESS_EVERY == 0:
                _log(
                    f"{done}/{len(sessions)} sessions, up to {day.isoformat()}, "
                    f"{time.monotonic() - began:.0f}s"
                )
    if year is not None and year_parts:
        rows += _write_part(scored_dir, year, year_parts)
    runtime = time.monotonic() - began
    meta = ScoreMeta(
        chosen=inputs.chosen,
        sessions=done,
        snapshots=snaps,
        skipped=skipped,
        rows=rows,
        first_session=sessions[0].isoformat() if sessions else None,
        last_session=sessions[-1].isoformat() if sessions else None,
        runtime_seconds=runtime,
    )
    pairs = (
        pd.concat(used, ignore_index=True)
        if used
        else pd.DataFrame({"map_id": pd.Series(dtype=object), "trade_date": pd.Series()})
    )
    _log(f"scored {rows} options from {snaps} snapshots in {runtime:.1f}s")
    return meta, pairs


def _run_score(args: argparse.Namespace) -> int:
    """Run the scoring stage; return the exit code."""
    inputs = read_step_one(args.lab_dir)
    if inputs is None:
        _log(f"step 1 files missing in {args.lab_dir}: run scripts/regime_calibration.py first")
        return 2
    if not args.db.exists():
        _log(f"{args.db} does not exist: run `make dbt-build-local` first")
        return 2
    try:
        con = duckdb.connect(str(args.db), read_only=True)
    except duckdb.IOException as exc:
        _log(f"cannot open {args.db} (is a build writing it?): {exc}")
        return 2
    try:
        missing = missing_tables(con, TABLES)
        if missing:
            _log(f"gold tables missing: {', '.join(missing)}")
            return 2
        meta, pairs = score_all(con, inputs, args.lab_dir / SCORED_DIR, start=args.start)
    finally:
        con.close()
    leaks = leaking_options(pairs, inputs.map_table)
    if not leaks.empty:
        _log(f"{len(leaks)} session maps were trained on their own outcomes")
        return 3
    (args.lab_dir / META_FILE).write_text(json.dumps(meta.__dict__, indent=2) + "\n")
    print(
        f"wrote {meta.rows} scored options to {args.lab_dir / SCORED_DIR} "
        f"({meta.sessions} sessions, {meta.snapshots} snapshots, {meta.skipped} skipped) "
        f"in {meta.runtime_seconds:.1f}s"
    )
    return 0


# --- sweep -----------------------------------------------------------------------------------


def read_scored(scored_dir: Path, columns: Sequence[str]) -> pd.DataFrame:
    """Read the columns of every yearly part that has them, in year order.

    Args:
        scored_dir: Directory of the parts.
        columns: Columns to read; a column absent from the cache is skipped.

    Returns:
        The rows of every part.
    """
    parts = sorted(scored_dir.glob("*.parquet"))
    if not parts:
        return pd.DataFrame({c: pd.Series(dtype=object) for c in columns})
    present = set(pq.read_schema(parts[0]).names)
    keep = [c for c in columns if c in present]
    return pd.concat([pd.read_parquet(p, columns=keep) for p in parts], ignore_index=True)


def split_years(
    options: pd.DataFrame, holdout_year: int
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Split the out-of-sample trade years into dev (before ``holdout_year``) and hold-out."""
    oos = options.loc[options["is_out_of_sample"].astype(bool)]
    years = sorted({int(y) for y in pd.to_datetime(oos["trade_date"]).dt.year})
    return (
        tuple(y for y in years if y < holdout_year),
        tuple(y for y in years if y >= holdout_year),
    )


def _selection_key(rule: GrowthRule) -> tuple[object, ...]:
    """Return the fields that decide a rule's ranked candidates (not its top N or sizing)."""
    return (
        rule.rank_by,
        rule.right,
        rule.dte_band,
        rule.moneyness_band,
        rule.regime,
        rule.one_per_underlying_expiry,
        rule.min_prob_profit,
    )


def sweep(
    prepared: PreparedOptions,
    rules: Sequence[GrowthRule],
    *,
    dev_years: Sequence[int],
    holdout_years: Sequence[int],
    min_dev_trades: int,
) -> tuple[pd.DataFrame, float]:
    """Evaluate every rule, ranking each distinct candidate set once.

    Rules that differ only in top ``N`` and sizing share their ranked candidates, so each
    candidate set is computed once and cut at every ``N``. Bootstrap intervals are computed
    only for rules with at least ``min_dev_trades`` dev trades.

    Args:
        prepared: Output of ``prepare`` on the cache.
        rules: Rules to evaluate.
        dev_years: Calendar years of the development period.
        holdout_years: Calendar years of the hold-out.
        min_dev_trades: Fewest dev trades for a rule to be ranked.

    Returns:
        One row per rule, in ``rules`` order, and the wall time in seconds.
    """
    began = time.monotonic()
    rows: dict[str, dict[str, object]] = {}
    groups: dict[tuple[object, ...], list[GrowthRule]] = {}
    for rule in rules:
        groups.setdefault(_selection_key(rule), []).append(rule)
    done = 0
    for members in groups.values():
        chosen, rank = ranked_positions(prepared, members[0])
        for rule in members:
            metrics = evaluate_positions(
                prepared,
                chosen[rank < rule.top_n],
                rule.sizing,
                dev_years=dev_years,
                holdout_years=holdout_years,
                ci_min_dev_trades=min_dev_trades,
                config=DEFAULT_CONFIG,
            )
            rows[rule.rule_id] = {**rule_fields(rule), **flatten(metrics)}
            done += 1
            if done % SWEEP_PROGRESS_EVERY == 0 or done == len(rules):
                _log(f"{done}/{len(rules)} rules, {time.monotonic() - began:.1f}s")
    frame = pd.DataFrame([rows[r.rule_id] for r in rules])
    return frame, time.monotonic() - began


@dataclass(frozen=True)
class OptionSummary:
    """Step 2's distribution of the scores, out of sample.

    Attributes:
        n_options: Out-of-sample scored options.
        by_cell: Per right and regime: options, share with ``expected_return > 0``, share
            with ``growth_rate > 0``, the same share under the market distribution, mean
            ``growth_rate`` and mean realised return.
        quantiles: Quantiles of ``expected_return`` and ``growth_rate`` by right.
        mean_realised: Mean realised return on premium of every out-of-sample option.
        mean_tail_share: Mean tail share of every out-of-sample option.
    """

    n_options: int
    by_cell: pd.DataFrame
    quantiles: pd.DataFrame
    mean_realised: float
    mean_tail_share: float


QUANTILES: Final[tuple[float, ...]] = (0.05, 0.25, 0.5, 0.75, 0.95)


def _quantile_key(q: float) -> str:
    """Return the column name of a quantile, such as ``q05``."""
    return f"q{round(q * 100):02d}"


def summarise_options(options: pd.DataFrame) -> OptionSummary:
    """Summarise the out-of-sample scores by right and regime.

    Args:
        options: Scored options with ``SUMMARY_COLUMNS``.

    Returns:
        The summary; ``by_cell`` has one row per right and regime and one ``all`` row per
        right.
    """
    oos = options.loc[options["is_out_of_sample"].astype(bool)].copy()
    oos["positive_edge"] = oos["expected_return"] > 0
    oos["positive_growth"] = oos["growth_rate"] > 0
    oos["positive_growth_market"] = oos["growth_rate_market"] > 0

    def cells(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        return (
            frame.groupby(keys, sort=False)
            .agg(
                n=("growth_rate", "size"),
                share_edge=("positive_edge", "mean"),
                share_growth=("positive_growth", "mean"),
                share_growth_market=("positive_growth_market", "mean"),
                mean_growth=("growth_rate", "mean"),
                mean_realised=("realised_return", "mean"),
            )
            .reset_index()
        )

    by_regime = cells(oos, ["right", "regime"])
    overall = cells(oos, ["right"]).assign(regime="all")
    order = {r: i for i, r in enumerate((*REGIME_LABELS, "all"))}
    by_cell = pd.concat([by_regime, overall], ignore_index=True)
    by_cell = by_cell.sort_values(
        ["right", "regime"], key=lambda s: s.map(order) if s.name == "regime" else s
    ).reset_index(drop=True)
    rows = []
    for right, part in oos.groupby("right", sort=True):
        for column in ("expected_return", "growth_rate"):
            values = part[column].quantile(list(QUANTILES)).to_numpy(dtype=np.float64)
            rows.append(
                {
                    "right": right,
                    "column": column,
                    **{_quantile_key(q): float(v) for q, v in zip(QUANTILES, values, strict=True)},
                }
            )
    return OptionSummary(
        n_options=len(oos),
        by_cell=by_cell,
        quantiles=pd.DataFrame(rows),
        mean_realised=float(oos["realised_return"].mean()) if len(oos) else float("nan"),
        mean_tail_share=float(oos["tail_share"].mean()) if len(oos) else float("nan"),
    )


@dataclass(frozen=True)
class GrowthReport:
    """Everything the markdown and the figure are rendered from.

    Attributes:
        results: One row per rule: ``rule_fields`` and the ``flatten`` metrics.
        picks: Output of ``pick_rules``.
        rules: The evaluated rules keyed by ``rule_id``.
        baseline: Flattened metrics of the random equal-weight baseline.
        baseline_calls: The same baseline drawn from the calls only.
        baseline_top_n: Options per session of both baselines.
        pooled: Flattened metrics of each pick's pooled-map version, keyed by ``rule_id``;
            empty when the pooled map was chosen in step 1.
        beat_dev: Qualified rules with a higher dev growth than the baseline.
        beat_both: Of those, how many also have a higher hold-out growth.
        summary: Step 2's score distribution.
        meta: The scoring stage's counts and timings.
        decision: Step 1's decision file.
        grid_size: Rules in the full grid.
        dev_years: Calendar years of the development period.
        holdout_years: Calendar years of the hold-out.
        last_session: Last trade date in the cache, or None.
        min_dev_trades: Fewest dev trades for a rule to be ranked.
        runtime_seconds: Wall time of the sweep loop, in seconds.
    """

    results: pd.DataFrame
    picks: Picks
    rules: dict[str, GrowthRule]
    baseline: dict[str, float]
    baseline_calls: dict[str, float]
    baseline_top_n: int
    pooled: dict[str, dict[str, float]]
    beat_dev: int
    beat_both: int
    summary: OptionSummary
    meta: dict[str, object]
    decision: dict[str, object]
    grid_size: int
    dev_years: tuple[int, ...]
    holdout_years: tuple[int, ...]
    last_session: date | None
    min_dev_trades: int
    runtime_seconds: float


# --- markdown --------------------------------------------------------------------------------


def _years(years: Sequence[int]) -> str:
    """Format a run of years, such as ``2021-2024``, or ``none``."""
    if not years:
        return "none"
    return str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"


def _row(report: GrowthReport, rule_id: str) -> dict[str, object]:
    """Return the flattened metrics of a rule, the baseline or a pooled-map version."""
    if rule_id == RANDOM_LABEL:
        return dict(report.baseline)
    if rule_id == RANDOM_CALLS_LABEL:
        return dict(report.baseline_calls)
    frame = report.results.loc[report.results["rule_id"] == rule_id]
    return {str(k): v for k, v in frame.iloc[0].items()}


def _mean_return(row: Mapping[str, object], period: str) -> str:
    """Format a period's mean return on premium with its interval."""
    value = fmt_percent(row.get(f"mean_return_{period}"), 2)
    low, high = row.get(f"mean_return_ci_low_{period}"), row.get(f"mean_return_ci_high_{period}")
    if fmt_missing(low) or fmt_missing(high):
        return value
    return f"{value} ({fmt_percent(low, 2)} to {fmt_percent(high, 2)})"


def _growth(value: object) -> str:
    """Format a log growth per session as a percentage with three decimals."""
    return fmt_percent(value, 3)


HEADLINE_HEADERS: Final[tuple[str, ...]] = (
    "Pick",
    "Rule",
    "Hold-out trades",
    "Win rate",
    "Predicted POP",
    "Mean return on premium (95% CI)",
    "Log growth per session (bet line)",
    "Sharpe per session",
    "Ladder total growth",
    "Ladder max drawdown",
    "Mean tail share",
)


def _shown(report: GrowthReport, rule_id: str) -> str:
    """Name a rule, or describe a baseline, for a table cell."""
    if rule_id == RANDOM_LABEL:
        return f"random, equal weight, top {report.baseline_top_n}"
    if rule_id == RANDOM_CALLS_LABEL:
        return f"random calls, equal weight, top {report.baseline_top_n}"
    return f"`{rule_id}`"


def _headline_row(report: GrowthReport, label: str, rule_id: str) -> list[str]:
    """Render one row of the headline table (hold-out metrics)."""
    row = _row(report, rule_id)
    shown = _shown(report, rule_id)
    return [
        label,
        shown,
        fmt_count(row.get("n_trades_holdout")),
        fmt_percent(row.get("win_rate_holdout")),
        fmt_percent(row.get("mean_predicted_pop_holdout")),
        _mean_return(row, "holdout"),
        _growth(row.get("growth_per_session_holdout")),
        fmt_fixed(row.get("sharpe_per_session_holdout"), 3),
        fmt_percent(row.get("ladder_total_growth_holdout"), 1),
        fmt_percent(row.get("ladder_max_drawdown_holdout"), 1),
        fmt_percent(row.get("mean_tail_share_holdout")),
    ]


def _pooled_row(report: GrowthReport, label: str, rule_id: str) -> list[str]:
    """Render a pick's pooled-map version as a headline row."""
    row = report.pooled[rule_id]
    return [
        label,
        f"`{rule_id}` (pooled map)",
        fmt_count(row.get("n_trades_holdout")),
        fmt_percent(row.get("win_rate_holdout")),
        fmt_percent(row.get("mean_predicted_pop_holdout")),
        _mean_return(row, "holdout"),
        _growth(row.get("growth_per_session_holdout")),
        fmt_fixed(row.get("sharpe_per_session_holdout"), 3),
        fmt_percent(row.get("ladder_total_growth_holdout"), 1),
        fmt_percent(row.get("ladder_max_drawdown_holdout"), 1),
        fmt_percent(row.get("mean_tail_share_holdout")),
    ]


def _interval_sentence(row: Mapping[str, object]) -> str:
    """Say whether the hold-out interval of the mean return excludes zero."""
    low, high = row.get("mean_return_ci_low_holdout"), row.get("mean_return_ci_high_holdout")
    if fmt_missing(low) or fmt_missing(high):
        return "The hold-out has too few trades for an interval."
    if float(low) > 0:  # type: ignore[arg-type]
        return "Its hold-out interval of the mean return lies above zero."
    if float(high) < 0:  # type: ignore[arg-type]
        return "Its hold-out interval of the mean return lies below zero."
    return (
        "Its hold-out interval of the mean return includes zero, so a positive mean return is "
        "not established at 95% on the hold-out alone."
    )


def _pick_paragraph(report: GrowthReport, title: str, rule_id: str, why: str) -> str:
    """Render the paragraph stating one pick in words."""
    row = _row(report, rule_id)
    base, calls = report.baseline, report.baseline_calls
    return (
        f"**{title}: `{rule_id}`.** {describe_rule(report.rules[rule_id])} {why} On dev it "
        f"made {fmt_count(row['n_trades_dev'])} trades with a log growth of "
        f"{_growth(row['growth_per_session_dev'])} per session and a mean return on premium of "
        f"{fmt_percent(row['mean_return_dev'], 2)} (random baseline "
        f"{_growth(base['growth_per_session_dev'])} and "
        f"{fmt_percent(base['mean_return_dev'], 2)}). On the hold-out it made "
        f"{fmt_count(row['n_trades_holdout'])} trades, won "
        f"{fmt_percent(row['win_rate_holdout'])} against a predicted "
        f"{fmt_percent(row['mean_predicted_pop_holdout'])}, returned "
        f"{_mean_return(row, 'holdout')} on premium per trade, with a log growth of "
        f"{_growth(row['growth_per_session_holdout'])} per session on the bet line and a total "
        f"of {fmt_percent(row['ladder_total_growth_holdout'], 1)} on the ladder line (random "
        f"baseline {_growth(base['growth_per_session_holdout'])} and "
        f"{fmt_percent(base['ladder_total_growth_holdout'], 1)}, calls-only baseline "
        f"{_growth(calls['growth_per_session_holdout'])} and "
        f"{fmt_percent(calls['ladder_total_growth_holdout'], 1)}). {_interval_sentence(row)}"
    )


def _decision_words(report: GrowthReport) -> str:
    """Name the map step 1 chose, with its Brier difference."""
    d = report.decision
    chosen = str(d.get("chosen"))
    which = (
        "the regime maps (step 1 found them better than the pooled map)"
        if chosen == "regime"
        else "the pooled walk-forward map of the trade date's year (step 1 found the regime "
        "maps no better)"
    )
    diff, low, high = (d.get(k) for k in ("difference", "ci_low", "ci_high"))
    return (
        f"{which}: out-of-sample Brier difference regime minus pooled "
        f"{float(diff):+.4f} (95% interval {float(low):+.4f} to {float(high):+.4f})"  # type: ignore[arg-type]
    )


def _lead(report: GrowthReport) -> str:
    """Render the opening paragraph."""
    return (
        "# Growth lab: growth-optimal single options on a hold-out\n\n"
        f"Every usable long call and put of every session from {report.meta.get('first_session')} "
        f"to {report.meta.get('last_session')} was scored at the ask, with its growth-optimal "
        f"fraction of capital and growth rate, under {_decision_words(report)}. "
        f"{fmt_count(len(report.results))} rules that pick the top options by growth "
        "rate each session, size them equally or by that fraction and hold them to expiry were "
        f"ranked on the dev years ({_years(report.dev_years)}) and are reported on the hold-out "
        f"({_years(report.holdout_years)}), which no choice looked at. The answer is reported "
        "whether it is positive or negative."
    )


def _pick_labels(picks: Picks) -> list[tuple[str, str]]:
    """Return ``(label, rule_id)`` of the distinct picks, best growth first."""
    labels: list[tuple[str, str]] = []
    if picks.best_growth is not None:
        labels.append(("Best growth", picks.best_growth))
    if picks.best_low_drawdown is not None and picks.best_low_drawdown != picks.best_growth:
        labels.append(("Best growth, low drawdown", picks.best_low_drawdown))
    return labels


def _headline_section(report: GrowthReport) -> str:
    """Render the picks and the baseline on the hold-out."""
    picks = report.picks
    head = "## Headline (hold-out)\n\n"
    rows = [
        _headline_row(report, "Baseline", RANDOM_LABEL),
        _headline_row(report, "Baseline, calls only", RANDOM_CALLS_LABEL),
    ]
    if picks.best_growth is None:
        return head + (
            f"No rule has at least {fmt_count(report.min_dev_trades)} dev trades, so nothing "
            "is picked. The baselines' hold-out rows are below.\n\n"
            + fmt_table(HEADLINE_HEADERS, rows, left=(0, 1))
        )
    rows.append(_headline_row(report, "Best growth", picks.best_growth))
    paragraphs = [
        _pick_paragraph(
            report,
            "Best growth",
            picks.best_growth,
            "It has the highest dev growth per session of every rule with enough dev trades.",
        )
    ]
    if picks.best_low_drawdown is not None and picks.best_low_drawdown == picks.best_growth:
        paragraphs.append(
            "**Best growth, low drawdown:** the same rule; its dev ladder drawdown is below the "
            "median "
            f"of the qualifying rules ({fmt_percent(picks.drawdown_median)})."
        )
    elif picks.best_low_drawdown is not None:
        rows.append(_headline_row(report, "Best growth, low drawdown", picks.best_low_drawdown))
        paragraphs.append(
            _pick_paragraph(
                report,
                "Best growth, low drawdown",
                picks.best_low_drawdown,
                "It has the highest dev growth per session among the rules whose dev ladder "
                "drawdown is below the median of the qualifying rules "
                f"({fmt_percent(picks.drawdown_median)}).",
            )
        )
    note = (
        "The bet line treats each session's picks as one bet sized as the rule says, as if no "
        "other bet were open: its mean log growth per session (over every hold-out session; a "
        "session without a trade adds 0) is the realised counterpart of the growth rate and "
        "ranks the rules, and the Sharpe ratio is of its session returns. Its compounded total "
        "is not an account, because the options are held for weeks. The ladder line spreads "
        "each pick's stake over the sessions until its expiry, so about the rule's share of "
        "equity is committed at a time; its total growth and its largest fall below its running "
        "peak approximate a feasible account. The mean return is per trade on premium at the "
        "ask, held to expiry; its interval resamples expiration dates."
    )
    return (
        head
        + fmt_table(HEADLINE_HEADERS, rows, left=(0, 1))
        + "\n\n"
        + "\n\n".join([*paragraphs, note])
    )


TOP_HEADERS: Final[tuple[str, ...]] = (
    "#",
    "Rule",
    "Dev trades",
    "Dev log growth per session",
    "Dev mean return",
    "Dev ladder max drawdown",
    "Hold-out trades",
    "Hold-out win rate",
    "Hold-out predicted POP",
    "Hold-out mean return (95% CI)",
    "Hold-out log growth per session",
    "Hold-out ladder total growth",
    "Hold-out ladder max drawdown",
    "Hold-out Sharpe",
)


def _top_row(report: GrowthReport, label: str, rule_id: str) -> list[str]:
    """Render one row of the top-rules table."""
    row = _row(report, rule_id)
    shown = _shown(report, rule_id)
    return [
        label,
        shown,
        fmt_count(row.get("n_trades_dev")),
        _growth(row.get("growth_per_session_dev")),
        fmt_percent(row.get("mean_return_dev"), 2),
        fmt_percent(row.get("ladder_max_drawdown_dev"), 1),
        fmt_count(row.get("n_trades_holdout")),
        fmt_percent(row.get("win_rate_holdout")),
        fmt_percent(row.get("mean_predicted_pop_holdout")),
        _mean_return(row, "holdout"),
        _growth(row.get("growth_per_session_holdout")),
        fmt_percent(row.get("ladder_total_growth_holdout"), 1),
        fmt_percent(row.get("ladder_max_drawdown_holdout"), 1),
        fmt_fixed(row.get("sharpe_per_session_holdout"), 3),
    ]


def _top_section(report: GrowthReport) -> str:
    """Render the top rules by dev growth with their hold-out metrics, and the baseline."""
    qualified = report.picks.qualified
    ids = [str(r) for r in qualified["rule_id"].head(TOP_RULES)]
    rows = [_top_row(report, str(i), rule_id) for i, rule_id in enumerate(ids, start=1)]
    rows.append(_top_row(report, "baseline", RANDOM_LABEL))
    rows.append(_top_row(report, "baseline, calls", RANDOM_CALLS_LABEL))
    legend = (
        f"Ranked by dev growth per session among the {fmt_count(len(qualified))} rules with at "
        f"least {fmt_count(report.min_dev_trades)} dev trades; the hold-out columns are the "
        "honest numbers. Rule ids read ranking (`gr` growth rate, `gg` growth gap over the "
        "market, `er` expected return), right, DTE band (`dany` for all), strike-over-close band "
        "in percent (`many` for all), regime gate (`any`, `calm`, `up`, `ivh` high IV rank, "
        "`ivl` low IV rank), `one` option per underlying and expiry or `all`, minimum "
        "probability of profit in percent, options per session and sizing (`eq` equal, `kelly` "
        "growth-optimal fractions)."
    )
    return (
        f"## Top {TOP_RULES} rules on dev, with their hold-out results\n\n"
        + legend
        + "\n\n"
        + fmt_table(TOP_HEADERS, rows, left=(0, 1))
    )


def _regime_section(report: GrowthReport) -> str:
    """Render the regime-contribution rows, or say why there are none."""
    head = "## Regime contribution\n\n"
    if str(report.decision.get("chosen")) != "regime":
        return head + (
            "Step 1 chose the pooled map, so every option was scored with the pooled "
            "walk-forward map and no regime-conditional calibration enters any rule. There is "
            "no regime-map version to compare: the regime gates of the grid (`calm`, `up`, "
            "`ivh`, `ivl`) are the only use of the regime here."
        )
    rows = []
    for label, rule_id in _pick_labels(report.picks):
        if rule_id not in report.pooled:
            continue
        rows.append(_headline_row(report, f"{label}, regime maps", rule_id))
        rows.append(_pooled_row(report, f"{label}, pooled map", rule_id))
    return head + (
        "Each pick is re-run with every map-dependent score (probability of profit, expected "
        "return, growth rate, growth gap and fraction) taken from the pooled map instead of the "
        "regime maps, so the difference between the two rows is what the regime maps add.\n\n"
        + fmt_table(HEADLINE_HEADERS, rows, left=(0, 1))
    )


def _comparisons_section(report: GrowthReport) -> str:
    """Render the multiple-comparisons sanity check."""
    picks = report.picks
    base = report.baseline
    if picks.median_rule is None:
        median = "No rule qualifies, so there is no median dev rule."
    else:
        row = _row(report, picks.median_rule)
        median = (
            f"The median dev rule (`{picks.median_rule}`, dev growth "
            f"{_growth(row['growth_per_session_dev'])} per session) has a hold-out growth of "
            f"{_growth(row['growth_per_session_holdout'])} per session."
        )
    return (
        "## Multiple-comparisons check\n\n"
        f"Of {fmt_count(len(picks.qualified))} qualifying rules, {fmt_count(report.beat_dev)} "
        f"beat the random baseline's dev growth of {_growth(base['growth_per_session_dev'])} per "
        f"session; of those, {fmt_count(report.beat_both)} also beat its hold-out growth of "
        f"{_growth(base['growth_per_session_holdout'])}. {median} A rule that leads on dev and "
        "falls back on the hold-out is what searching many rules on the same data produces, so "
        "the hold-out column, not the dev ranking, is the estimate to quote."
    )


CELL_HEADERS: Final[tuple[str, ...]] = (
    "Right",
    "Regime",
    "Options",
    "E[R] > 0",
    "g* > 0 (calibrated)",
    "g* > 0 (market)",
    "Mean g*",
    "Mean realised return",
)


def _scores_section(report: GrowthReport) -> str:
    """Render step 2's distribution of the scores."""
    s = report.summary
    rows = [
        [
            str(r.right),
            f"`{r.regime}`" if r.regime != "all" else "all",
            fmt_count(r.n),
            fmt_percent(r.share_edge),
            fmt_percent(r.share_growth),
            fmt_percent(r.share_growth_market),
            fmt_percent(r.mean_growth, 3),
            fmt_percent(r.mean_realised, 1),
        ]
        for r in s.by_cell.itertuples()
    ]
    q = s.quantiles
    quantile_rows = [
        [
            str(r["right"]),
            f"`{r['column']}`",
            *(fmt_percent(r[_quantile_key(p)], 2) for p in QUANTILES),
        ]
        for _, r in q.iterrows()
    ]
    meta = report.meta
    return (
        "## Scored options\n\n"
        f"Step 2 scored {fmt_count(meta.get('rows'))} options from "
        f"{fmt_count(meta.get('snapshots'))} ok snapshots of {fmt_count(meta.get('sessions'))} "
        f"sessions in {float(meta.get('runtime_seconds', 0.0)):.0f}s "  # type: ignore[arg-type]
        f"({fmt_count(meta.get('skipped'))} snapshots had no scorable option); "
        f"{fmt_count(s.n_options)} are out of sample. `E[R]` is the calibrated expected return on "
        "premium at the ask and `g*` the growth-optimal log growth per holding period; the "
        "market column is the same `g*` under the raw risk-neutral distribution. Across every "
        f"out-of-sample option the mean realised return on premium is "
        f"{fmt_percent(s.mean_realised, 1)}.\n\n"
        + fmt_table(CELL_HEADERS, rows, left=(0, 1))
        + "\n\nQuantiles of the calibrated scores (5%, 25%, median, 75%, 95%):\n\n"
        + fmt_table(
            ("Right", "Score", *(f"{p:.0%}" for p in QUANTILES)), quantile_rows, left=(0, 1)
        )
    )


def _protocol_section(report: GrowthReport) -> str:
    """Render the protocol paragraph."""
    return (
        "## Protocol\n\n"
        "Every usable call and put (bid above 0, ask at least the bid) of every ok snapshot "
        "with at least 7 days to expiry, whose strike lies inside the knots of the snapshot's "
        "risk-neutral CDF, was scored once as a one-leg long position filled at the ask: the "
        "CDF is calibrated with the step-1 map of the trade date's year (fitted only on "
        "expirations before 1 January) and completed with the structures calculator's "
        "lognormal tails. `g*` maximises `E[log(1 + f R)]` over `f` in "
        f"[0, {F_MAX:.0%}] (`R` the return on premium at expiry): exact segment integrals inside "
        "the knots, 16-point Gauss-Legendre in each tail out to the 99.99% quantile, a 64-point "
        "grid of fractions refined by golden section. Each option is settled at its "
        "expiration's settlement close. "
        f"{fmt_count(len(report.results))} of the {fmt_count(report.grid_size)} grid rules were "
        f"evaluated ({report.runtime_seconds:.1f}s). A rule only chooses among out-of-sample "
        "options: its gates (right, days to expiry, strike over close, regime, minimum "
        "calibrated probability of profit), its ranking (ties by underlying, expiration, right "
        "and strike), at most one option per underlying and expiry when asked, then the top N "
        f"per session. Sizing `eq` splits {F_MAX:.0%} of the line's equity equally across a "
        "session's picks; `kelly` gives each pick its growth-optimal fraction and scales the "
        f"session down to at most {F_MAX:.0%} in all (a pick with fraction 0 is not a trade). "
        "A trade belongs to the period of its trade date's year: dev is "
        f"{_years(report.dev_years)}, the hold-out is {_years(report.holdout_years)}. Rules are "
        "ranked on dev growth per session among those with at least "
        f"{fmt_count(report.min_dev_trades)} dev trades; the low-drawdown pick is the best of "
        "those whose dev ladder drawdown is below the median. The hold-out was not used to choose "
        f"anything. The baseline draws {report.baseline_top_n} options per session uniformly "
        "at random (seeded) from every out-of-sample option and sizes them equally; the "
        "calls-only baseline does the same among the calls, because the long-call rules lead "
        "and calls and puts fared very differently in this sample. Every result is in "
        "`sweep.csv` in the lab directory."
    )


def _holdout_span(report: GrowthReport) -> str:
    """Format the hold-out length in years, from 1 January of its first year to the last session."""
    if not report.holdout_years or report.last_session is None:
        return "no sessions"
    days = (report.last_session - date(report.holdout_years[0], 1, 1)).days + 1
    return f"about {days / 365.25:.2f} years"


def _rights_sentence(summary: OptionSummary) -> str:
    """State the mean realised return of calls and of puts, and what a gap means."""
    cells = summary.by_cell.loc[summary.by_cell["regime"] == "all"]
    means = {
        str(r): float(m)
        for r, m in zip(cells["right"], cells["mean_realised"].astype("float64"), strict=True)
    }
    if not {"call", "put"} <= set(means):
        return "The universe is today's large caps, chosen with hindsight."
    call, put = means["call"], means["put"]
    text = (
        f"By right the averages differ: calls returned {fmt_percent(call, 1)} and puts "
        f"{fmt_percent(put, 1)} on premium."
    )
    if call > 0:
        text += (
            " The universe is today's large caps, chosen with hindsight (names that became large "
            "caps), which favours calls; the walk-forward calibration maps, fitted on the same "
            "names, learn that drift, so part of the calls' calibrated edge measures it."
        )
    else:
        text += " The universe is today's large caps, chosen with hindsight."
    return text


def _caveats_section(report: GrowthReport) -> str:
    """Render the caveats paragraph."""
    s = report.summary
    return (
        "## Caveats\n\n"
        "Long premium loses on average: across every out-of-sample option the mean realised "
        f"return on premium is {fmt_percent(s.mean_realised, 1)}, and most options expire "
        "worthless, so a few large payoffs carry any positive result. "
        f"{_rights_sentence(s)} The large payoffs sit in the tails, partly beyond the quoted "
        "strikes, where the lognormal tail completion, not the calibrated CDF, supplies the "
        "expected payoff (the mean tail share of every option is "
        f"{fmt_percent(s.mean_tail_share)}; the headline reports it per pick). Fills are at "
        "the ask with no commissions or further slippage, and every option is held to expiry "
        "and settled at the settlement close, with no early exercise or management. Both "
        "equity lines book a trade at its trade date rather than at expiry; the bet line "
        "ignores that positions overlap, and the ladder line only approximates the capital an "
        f"account would commit. {fmt_count(len(report.results))} rules were searched, so the "
        "best dev growth is inflated by selection; only the hold-out figures are unbiased, and "
        f"the hold-out is short ({_years(report.holdout_years)}, {_holdout_span(report)}) with "
        "overlapping positions, so its intervals are wide. A December dev trade can expire in "
        "the hold-out year. Regime features use end-of-day data of the trade date, the same "
        "close the fill is assumed at. Only ok snapshots are scored. This is a historical "
        "measurement of selection and sizing rules, not trade advice."
    )


def render_markdown(report: GrowthReport) -> str:
    """Render the growth lab report. The text is a pure function of ``report``.

    Args:
        report: The sweep results, picks and score summary.

    Returns:
        The markdown, ending in a newline.
    """
    figure = (
        "## Hold-out equity\n\n"
        f"![Hold-out equity of the picks and the baseline]({HOLDOUT_IMAGE})\n\n"
        "Equity of the one-dollar ladder line on the hold-out sessions, log scale: the two random "
        "baselines and the picks, each with its own sizing, each stake spread over the sessions "
        "until its option's expiry."
    )
    sections = [
        _lead(report),
        _headline_section(report),
        _top_section(report),
        _regime_section(report),
        _comparisons_section(report),
        _scores_section(report),
        _protocol_section(report),
        figure,
        _caveats_section(report),
    ]
    return "\n\n".join(sections) + "\n"


# --- figure ----------------------------------------------------------------------------------


def plot_holdout(lines: Sequence[tuple[str, pd.DataFrame]], path: Path) -> None:
    """Write the hold-out equity lines on a log scale.

    Args:
        lines: ``(label, holdout_line output)`` in drawing order: the two baselines first,
            then the picks. Empty lines are skipped; with none a placeholder figure is written.
        path: Where to write the PNG.
    """
    fig = Figure(figsize=(8.0, 4.6), facecolor="white", layout="constrained")
    ax = fig.subplots()
    drawn = [(label, line) for label, line in lines if not line.empty]
    if not drawn:
        ax.axis("off")
        ax.text(0.5, 0.5, "No hold-out sessions", ha="center", va="center", color=INK_MUTED)
        save_figure(fig, path)
        return
    styles = ((GREY, ":", 1.5), (GREY, "-.", 1.5), (BLUE, "-", 2.0), (ORANGE, "--", 1.75))
    for (label, line), (colour, dash, width) in zip(drawn, styles, strict=False):
        ax.plot(
            pd.to_datetime(line["trade_date"]),
            line["equity"],
            color=colour,
            linestyle=dash,
            linewidth=width,
            label=label,
        )
    ax.set_yscale("log")
    plain = FuncFormatter(lambda value, _: f"{value:g}")
    ax.yaxis.set_major_formatter(plain)
    ax.yaxis.set_minor_formatter(plain)
    ax.axhline(1.0, color=GREY, linewidth=0.8)
    ax.set_ylabel(
        "Ladder equity (dollars per starting dollar, log scale)", color=INK_MUTED, fontsize=9
    )
    ax.set_title(
        "Hold-out equity of the growth lab picks and the random baselines",
        loc="left",
        fontsize=10,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8, loc="best")
    style_axes(ax)
    save_figure(fig, path)


# --- command line ----------------------------------------------------------------------------


def _evaluate(
    prepared: PreparedOptions,
    positions: np.ndarray,
    sizing: Sizing,
    dev: Sequence[int],
    hold: Sequence[int],
) -> dict[str, float]:
    """Evaluate fixed positions with intervals, flattened."""
    return flatten(
        evaluate_positions(
            prepared,
            np.asarray(positions, dtype=np.int64),
            sizing,
            dev_years=dev,
            holdout_years=hold,
            config=DEFAULT_CONFIG,
        )
    )


def _run_sweep(args: argparse.Namespace) -> int:
    """Run the sweep stage; return the exit code."""
    scored_dir = args.lab_dir / SCORED_DIR
    inputs = read_step_one(args.lab_dir)
    meta_path = args.lab_dir / META_FILE
    if inputs is None or not meta_path.exists() or not list(scored_dir.glob("*.parquet")):
        _log(f"the cache in {args.lab_dir} is incomplete: run with --score first")
        return 2
    variant = [f"{c}{POOLED_SUFFIX}" for c in VARIANT_COLUMNS]
    columns = list(dict.fromkeys([*OPTION_COLUMNS, "strike", *SUMMARY_COLUMNS, *variant]))
    options = read_scored(scored_dir, columns)
    began = time.monotonic()
    prepared = prepare(options)
    grid = rule_grid()
    rules = list(grid if args.grid_limit is None else grid[: args.grid_limit])
    dev, hold = split_years(options, args.holdout_year)
    _log(
        f"sweeping {len(rules)} rules over {len(prepared.frame)} out-of-sample options "
        f"(prepared in {time.monotonic() - began:.1f}s)"
    )
    results, runtime = sweep(
        prepared, rules, dev_years=dev, holdout_years=hold, min_dev_trades=args.min_dev_trades
    )
    args.lab_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.lab_dir / SWEEP_FILE, index=False)
    picks = pick_rules(results, min_dev_trades=args.min_dev_trades)
    by_id = {r.rule_id: r for r in rules}
    top_n = by_id[picks.best_growth].top_n if picks.best_growth is not None else max(TOP_NS)
    random_rows = random_positions(prepared, top_n=top_n, seed=DEFAULT_CONFIG.bootstrap_seed)
    baseline = _evaluate(prepared, random_rows, "equal", dev, hold)
    is_call = (prepared.frame["right"] == "call").to_numpy(dtype=np.bool_)
    call_rows = random_positions(
        prepared, top_n=top_n, seed=DEFAULT_CONFIG.bootstrap_seed, eligible=is_call
    )
    baseline_calls = _evaluate(prepared, call_rows, "equal", dev, hold)
    chosen_ids = [rule_id for _, rule_id in _pick_labels(picks)]
    pooled: dict[str, dict[str, float]] = {}
    if inputs.chosen == "regime" and all(c in options.columns for c in variant):
        alternative = prepare(options, suffix=POOLED_SUFFIX)
        for rule_id in chosen_ids:
            rule = by_id[rule_id]
            positions = select_positions(alternative, rule)
            pooled[rule_id] = _evaluate(alternative, positions, rule.sizing, dev, hold)
    beat_dev, beat_both = (
        beat_counts(picks.qualified, baseline) if not picks.qualified.empty else (0, 0)
    )
    dates = pd.to_datetime(options["trade_date"])
    report = GrowthReport(
        results=results,
        picks=picks,
        rules=by_id,
        baseline=baseline,
        baseline_calls=baseline_calls,
        baseline_top_n=top_n,
        pooled=pooled,
        beat_dev=beat_dev,
        beat_both=beat_both,
        summary=summarise_options(options),
        meta=json.loads(meta_path.read_text()),
        decision=inputs.decision,
        grid_size=len(grid),
        dev_years=dev,
        holdout_years=hold,
        last_session=dates.max().date() if len(dates) else None,
        min_dev_trades=args.min_dev_trades,
        runtime_seconds=runtime,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(report))
    lines = [
        (f"random (top {top_n}, equal)", holdout_line(prepared, random_rows, "equal", hold)),
        (f"random calls (top {top_n}, equal)", holdout_line(prepared, call_rows, "equal", hold)),
    ]
    for label, pick in _pick_labels(picks):
        rule = by_id[pick]
        line = holdout_line(prepared, select_positions(prepared, rule), rule.sizing, hold)
        lines.append((f"{label.lower()} ({pick})", line))
    plot_holdout(lines, args.out.parent / HOLDOUT_IMAGE)
    print(
        f"wrote {args.lab_dir / SWEEP_FILE}, {args.out} and {args.out.parent / HOLDOUT_IMAGE}; "
        f"{len(rules)} rules in {runtime:.1f}s"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested stages.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        0 on success; 2 when an input is missing or locked; 3 when the out-of-sample check
        fails.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--score", action="store_true", help="score and cache every option")
    parser.add_argument("--sweep", action="store_true", help="evaluate the rule grid")
    parser.add_argument("--db", type=Path, default=Path(".dbt-local/oap.duckdb"))
    parser.add_argument("--lab-dir", type=Path, default=Path(".dbt-local/growth-lab"))
    parser.add_argument("--out", type=Path, default=Path("docs/growth-lab.md"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2021, 1, 4))
    parser.add_argument("--holdout-year", type=int, default=2025)
    parser.add_argument("--min-dev-trades", type=int, default=400)
    parser.add_argument("--grid-limit", type=int, default=None)
    args = parser.parse_args(argv)
    if not (args.score or args.sweep):
        parser.error("give --score, --sweep or both")
    if args.grid_limit is not None and args.grid_limit < 1:
        parser.error("--grid-limit must be at least 1")
    if args.score:
        code = _run_score(args)
        if code != 0:
            return code
    return _run_sweep(args) if args.sweep else 0


if __name__ == "__main__":
    sys.exit(main())
