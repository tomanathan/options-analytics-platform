"""Regime-conditional calibration: does one map per regime beat the pooled map out of sample?

Step 1 of the growth lab (``docs/design/growth-lab.md``). A one-time study, not a pipeline
step. It opens the DuckDB file read-only and reads ``gold.calibration_prediction``,
``gold.calibration_map``, ``gold.fct_underlying_daily`` and the vendor IVs of
``gold.fct_option_quote``. It computes the rule lab's regime features
(``oap.analytics.rulelab.regime_features``), fits the pooled and the per-regime walk-forward
maps (``oap.analytics.regime_calibration``), checks that the refitted pooled maps equal
``gold.calibration_map``, compares both on the out-of-sample predictions and applies the
decision rule. Steps 2 and 3 (``scripts/growth_lab.py``) read its outputs.

It writes to ``--lab-dir`` (gitignored): ``regime.parquet`` (the features),
``regime_maps.parquet`` (every map, pooled and per regime), ``comparison.csv`` and
``decision.json``; and renders ``--out`` with ``img/regime_calibration.png`` next to it.

Units: probabilities as decimals in the data and percentages in the text; the Brier score in
squared probability, the log loss in nats, the ECE in probability.

Usage: ``python -m scripts.regime_calibration [--db .dbt-local/oap.duckdb]
[--lab-dir .dbt-local/growth-lab] [--out docs/regime-calibration.md]``.
Exit codes: 0 on success; 2 when the database or a table is missing or the file is locked; 3
when the refitted pooled maps differ from ``gold.calibration_map`` or a regime map was trained
on an expiration on or after its cutoff.
"""

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

import duckdb
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from oap.analytics.backtest import maps_from_frame
from oap.analytics.config import DEFAULT_CONFIG, DTE_BUCKETS
from oap.analytics.io import read_table
from oap.analytics.regime_calibration import (
    REGIME_LABELS,
    Decision,
    RegimeMaps,
    compare_metrics,
    decide,
    paired_sample,
    regime_map_summary,
    regime_maps_to_frame,
    reliability_frame,
    walk_forward_regime_maps,
)
from oap.analytics.rulelab import ATM_MIN_DTE, IV_QUOTE_COLUMNS, atm_iv, regime_features
from oap.analytics.sample import PREDICTION_COLUMNS
from scripts.backtest_entry_rule import (
    BLUE,
    GREY,
    INK,
    INK_MUTED,
    ORANGE,
    fmt_count,
    fmt_fixed,
    fmt_table,
    missing_tables,
    save_figure,
    style_axes,
)

TABLES: Final[tuple[str, ...]] = (
    "calibration_prediction",
    "calibration_map",
    "fct_underlying_daily",
    "fct_option_quote",
)
"""Tables of the ``gold`` schema step 1 reads."""

REGIME_FILE: Final = "regime.parquet"
MAPS_FILE: Final = "regime_maps.parquet"
COMPARISON_FILE: Final = "comparison.csv"
DECISION_FILE: Final = "decision.json"
IMAGE: Final = "img/regime_calibration.png"

PREDICTIONS_SQL: Final = "select * from gold.calibration_prediction"
DAILY_SQL: Final = "select underlying, trade_date, log_return from gold.fct_underlying_daily"
IV_SQL: Final = (
    "select underlying, trade_date, expiration, cast(strike as double) as strike, "
    "option_right, cast(source_iv as double) as source_iv, "
    "cast(underlying_close as double) as underlying_close, dte_days "
    "from gold.fct_option_quote where dte_days >= {min_dte} and source_iv > 0"
)

METRIC_LABELS: Final[dict[str, str]] = {
    "brier_score": "Brier score",
    "log_loss": "Log loss (nats)",
    "expected_calibration_error": "ECE",
}


def _log(message: str) -> None:
    """Write a progress line to standard error."""
    print(message, file=sys.stderr)


def load_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Compute the rule lab's regime features of every underlying and session.

    Args:
        con: Read-only connection to a DuckDB file with the ``gold`` schema.

    Returns:
        Rows with ``REGIME_COLUMNS`` of ``oap.analytics.rulelab``.
    """
    daily = read_table(con.sql(DAILY_SQL))
    quotes = read_table(con.sql(IV_SQL.format(min_dte=ATM_MIN_DTE)))
    return regime_features(daily, atm_iv(quotes[list(IV_QUOTE_COLUMNS)]), DEFAULT_CONFIG)


@dataclass(frozen=True)
class StepOne:
    """Everything step 1 computes; the report and the files are rendered from it.

    Attributes:
        features: Regime features.
        maps: Pooled and per-regime walk-forward maps.
        summary: ``regime_map_summary`` of the maps.
        comparison: ``compare_metrics`` output.
        reliability: ``reliability_frame`` output.
        decision: The decision.
        n_predictions: Prediction rows read.
        mismatched: Pooled fold maps that differ from ``gold.calibration_map``.
        leaking: Regime map ids whose training expirations reach their cutoff.
        runtime_seconds: Wall time in seconds.
    """

    features: pd.DataFrame
    maps: RegimeMaps
    summary: pd.DataFrame
    comparison: pd.DataFrame
    reliability: pd.DataFrame
    decision: Decision
    n_predictions: int
    mismatched: tuple[str, ...]
    leaking: tuple[str, ...]
    runtime_seconds: float


def _mismatched(maps: RegimeMaps, gold: pd.DataFrame) -> tuple[str, ...]:
    """Return the pooled fold maps whose knots or values differ from the gold map table."""
    stored = maps_from_frame(gold)
    bad = []
    for map_id, fitted in maps.pooled.items():
        other = stored.get(map_id)
        same = (
            other is not None
            and np.array_equal(other.knots, fitted.cmap.knots)
            and np.array_equal(other.values, fitted.cmap.values)
        )
        if not same:
            bad.append(map_id)
    return tuple(bad)


def _leaking(maps: RegimeMaps) -> tuple[str, ...]:
    """Return the map ids whose latest training expiration is on or after the cutoff."""
    return tuple(
        map_id
        for map_id, fitted in {**maps.pooled, **maps.by_regime}.items()
        if fitted.train_cutoff is not None
        and fitted.train_max_expiration is not None
        and fitted.train_max_expiration >= fitted.train_cutoff
    )


def run(con: duckdb.DuckDBPyConnection) -> StepOne:
    """Fit, compare and decide.

    Args:
        con: Read-only connection to a DuckDB file with the ``gold`` schema.

    Returns:
        The step-1 results.
    """
    began = time.monotonic()
    predictions = read_table(con.sql(PREDICTIONS_SQL))[list(PREDICTION_COLUMNS)]
    features = load_features(con)
    _log(f"read {len(predictions)} predictions and {len(features)} feature rows")
    maps = walk_forward_regime_maps(predictions, features, DEFAULT_CONFIG)
    paired = paired_sample(predictions, features, maps, DEFAULT_CONFIG)
    comparison = compare_metrics(paired, DEFAULT_CONFIG)
    runtime = time.monotonic() - began
    _log(f"fitted and compared in {runtime:.1f}s")
    return StepOne(
        features=features,
        maps=maps,
        summary=regime_map_summary(maps),
        comparison=comparison,
        reliability=reliability_frame(paired, DEFAULT_CONFIG),
        decision=decide(comparison),
        n_predictions=len(predictions),
        mismatched=_mismatched(maps, read_table(con.table("gold.calibration_map"))),
        leaking=_leaking(maps),
        runtime_seconds=runtime,
    )


# --- markdown --------------------------------------------------------------------------------


def _metric(result: StepOne, segment_type: str, segment: str, metric: str) -> pd.Series | None:
    """Return one comparison row, or None."""
    c = result.comparison
    rows = c.loc[(c["segment_type"] == segment_type) & (c["segment"] == segment)]
    rows = rows.loc[rows["metric"] == metric]
    return None if rows.empty else rows.iloc[0]


def _difference(row: pd.Series | None, digits: int = 4) -> str:
    """Format a paired difference with its interval."""
    if row is None:
        return "n/a"
    return (
        f"{float(row['difference']):+.{digits}f} ({float(row['ci_low']):+.{digits}f} to "
        f"{float(row['ci_high']):+.{digits}f})"
    )


def _verdict_word(row: pd.Series | None) -> str:
    """Say which variant the interval favours."""
    if row is None:
        return "n/a"
    if float(row["ci_high"]) < 0:
        return "regime"
    if float(row["ci_low"]) > 0:
        return "pooled"
    return "neither"


def _lead(result: StepOne) -> str:
    """Render the first paragraph: the decision, with its numbers."""
    d = result.decision
    numbers = (
        f"the out-of-sample Brier score is {fmt_fixed(d.brier_regime, 4)} with the regime maps "
        f"against {fmt_fixed(d.brier_pooled, 4)} with the pooled map, a difference of "
        f"{d.difference:+.4f} (95% interval {d.ci_low:+.4f} to {d.ci_high:+.4f}, "
        f"{fmt_count(d.n_predictions)} predictions on {fmt_count(d.n_clusters)} expiration "
        "dates)"
    )
    if d.use_regime:
        return (
            "**Decision: the regime maps are used downstream.** Fitting one walk-forward "
            "calibration map per regime improves on the pooled map out of sample: "
            f"{numbers}. The interval lies below zero, which is the decision rule."
        )
    return (
        "**Decision: the pooled map is used downstream.** Fitting one walk-forward "
        "calibration map per regime does not improve on the pooled map out of sample: "
        f"{numbers}. The decision rule needs a negative difference whose interval lies below "
        "zero, so the growth lab scores every option with the pooled map of its year."
    )


OVERALL_HEADERS: Final[tuple[str, ...]] = (
    "Metric",
    "Pooled",
    "Regime",
    "Regime minus pooled (95% CI)",
    "Interval favours",
)


def _overall_section(result: StepOne) -> str:
    """Render the overall comparison table."""
    rows = []
    for metric, label in METRIC_LABELS.items():
        row = _metric(result, "overall", "all", metric)
        rows.append(
            [
                label,
                "n/a" if row is None else fmt_fixed(row["pooled"], 4),
                "n/a" if row is None else fmt_fixed(row["regime"], 4),
                _difference(row),
                _verdict_word(row),
            ]
        )
    note = (
        "Lower is better for all three metrics, so a negative difference favours the regime "
        "maps. Each interval is a 95% percentile interval from "
        f"{DEFAULT_CONFIG.bootstrap_resamples} cluster-bootstrap resamples of expiration "
        "dates on the paired per-prediction differences (for the ECE, the resampled clusters' "
        "bin sums)."
    )
    table = fmt_table(OVERALL_HEADERS, rows, left=(0, 4))
    return "## Out of sample, overall\n\n" + table + "\n\n" + note


REGIME_HEADERS: Final[tuple[str, ...]] = (
    "Regime",
    "Predictions",
    "Expiries",
    "Brier pooled",
    "Brier regime minus pooled (95% CI)",
    "Log loss regime minus pooled (95% CI)",
    "ECE regime minus pooled (95% CI)",
    "Training rows by fold",
    "Folds on the pooled map",
)


def _training(result: StepOne, regime: str) -> tuple[str, str]:
    """Format a regime's training rows per out-of-sample fold and its fallback folds."""
    s = result.summary
    rows = s.loc[(s["regime"] == regime) & (s["fold"] >= DEFAULT_CONFIG.first_test_year)]
    folds = rows["fold"].astype("int64").tolist()
    sizes = ", ".join(
        f"{fold}: {fmt_count(n)}" for fold, n in zip(folds, rows["n_train"], strict=True)
    )
    fell = [str(f) for f, b in zip(folds, rows["fallback"].astype(bool), strict=True) if b]
    return sizes or "none", ", ".join(fell) if fell else "none"


def _regime_section(result: StepOne) -> str:
    """Render the per-regime table."""
    rows = []
    for regime in REGIME_LABELS:
        brier = _metric(result, "regime", regime, "brier_score")
        if brier is None:
            continue
        sizes, fell = _training(result, regime)
        rows.append(
            [
                f"`{regime}`",
                fmt_count(brier["n_predictions"]),
                fmt_count(brier["n_clusters"]),
                fmt_fixed(brier["pooled"], 4),
                _difference(brier),
                _difference(_metric(result, "regime", regime, "log_loss"), 3),
                _difference(_metric(result, "regime", regime, "expected_calibration_error")),
                sizes,
                fell,
            ]
        )
    legend = (
        "A regime is the 120-session IV rank bucket (`low` below 1/3, `mid`, `high` at or "
        "above 2/3) and the sign of the 20-session return (`down` at or below 0, `up` above "
        "0). `unknown` rows (a feature missing) always use the pooled map, so their "
        "difference is zero by construction. Training rows are the predictions of that regime "
        "whose options expired before 1 January of the fold year; a regime with fewer than "
        f"{fmt_count(DEFAULT_CONFIG.min_fit_samples)} uses the pooled map of the fold."
    )
    return "## By regime\n\n" + legend + "\n\n" + fmt_table(REGIME_HEADERS, rows)


SEGMENT_HEADERS: Final[tuple[str, ...]] = (
    "Predictions",
    "Expiries",
    "Brier pooled",
    "Brier regime",
    "Brier regime minus pooled (95% CI)",
    "Log loss regime minus pooled (95% CI)",
    "ECE regime minus pooled (95% CI)",
)


def _segment_section(result: StepOne, segment_type: str, title: str, label: str) -> str:
    """Render the per-DTE-bucket or per-year table."""
    c = result.comparison
    names = list(dict.fromkeys(c.loc[c["segment_type"] == segment_type, "segment"].astype(str)))
    if segment_type == "dte_bucket":
        names = [b for b in DTE_BUCKETS if b in names]
    rows = []
    for name in names:
        brier = _metric(result, segment_type, name, "brier_score")
        if brier is None:
            continue
        rows.append(
            [
                name,
                fmt_count(brier["n_predictions"]),
                fmt_count(brier["n_clusters"]),
                fmt_fixed(brier["pooled"], 4),
                fmt_fixed(brier["regime"], 4),
                _difference(brier),
                _difference(_metric(result, segment_type, name, "log_loss"), 3),
                _difference(_metric(result, segment_type, name, "expected_calibration_error")),
            ]
        )
    return f"## {title}\n\n" + fmt_table((label, *SEGMENT_HEADERS), rows)


def _protocol_section(result: StepOne) -> str:
    """Render the protocol paragraph."""
    fitted = result.summary.loc[~result.summary["fallback"].astype(bool)]
    grid = DEFAULT_CONFIG.moneyness_grid
    return (
        "## Protocol\n\n"
        f"The {fmt_count(result.n_predictions)} predictions of `gold.calibration_prediction` "
        "(the calibration sample: the risk-neutral probability of finishing below "
        f"{len(grid)} strikes from {grid[0]:.0%} to {grid[-1]:.0%} of the close, per ok "
        "snapshot) were labelled with the regime of their "
        "underlying on the trade date. For every fold year the pooled map is the walk-forward "
        "map of `oap.analytics.backtest` (refitted here and checked equal to "
        "`gold.calibration_map`), and each named regime gets its own isotonic map fitted on "
        "the same training rows restricted to that regime. "
        f"{fmt_count(len(fitted))} of the {fmt_count(len(result.summary))} fold-and-regime maps "
        "were fitted; the rest use the pooled map. Both variants are scored on the same "
        f"out-of-sample predictions (fold {DEFAULT_CONFIG.first_test_year} on, map not the "
        "identity), and the decision rule is fixed in advance: the regime maps are used "
        "downstream only when the overall Brier difference is negative and its 95% interval "
        f"lies below zero. The study ran in {result.runtime_seconds:.1f}s."
    )


def _caveats_section() -> str:
    """Render the caveats paragraph."""
    return (
        "## Caveats\n\n"
        "Splitting the training rows six ways leaves each regime map with a fraction of the "
        "pooled map's samples, and an isotonic fit on fewer samples has coarser steps that "
        "reach 0 or 1 more often, which the log loss punishes hardest. The regime is known only "
        "at the close of the trade date (the features use that day's close and IVs), the same "
        "time the predictions are made. The IV rank needs 120 sessions of history, so most 2020 "
        "predictions have an `unknown` regime and the 2021 regime maps are trained on few rows. "
        "Regime buckets are fixed in "
        "advance (thirds of the IV rank, the sign of the 20-session return), not tuned. The "
        "universe is today's large caps. This is a historical measurement of calibration, not "
        "trade advice."
    )


def render_markdown(result: StepOne) -> str:
    """Render the step-1 report. The text is a pure function of ``result``.

    Args:
        result: The step-1 results.

    Returns:
        The markdown, ending in a newline.
    """
    head = "# Regime-conditional calibration: one map per regime against the pooled map\n\n" + (
        _lead(result)
    )
    figure = (
        "## Reliability\n\n"
        f"![Reliability of the raw, pooled and regime probabilities]({IMAGE})\n\n"
        "Mean predicted probability against the realised frequency in ten equal-width bins, out "
        "of sample: the raw risk-neutral probabilities, the pooled map and the regime maps. "
        "Points on the diagonal are calibrated."
    )
    sections = [
        head,
        _overall_section(result),
        _regime_section(result),
        _segment_section(result, "dte_bucket", "By days to expiry", "DTE bucket"),
        _segment_section(result, "fold", "By year", "Year"),
        figure,
        _protocol_section(result),
        _caveats_section(),
    ]
    return "\n\n".join(sections) + "\n"


# --- figure ----------------------------------------------------------------------------------


def plot_reliability(bins: pd.DataFrame, path: Path) -> None:
    """Write the reliability diagram of the three variants.

    Args:
        bins: Output of ``reliability_frame``; an empty frame gives a placeholder figure.
        path: Where to write the PNG.
    """
    fig = Figure(figsize=(6.4, 5.6), facecolor="white", layout="constrained")
    ax = fig.subplots()
    if bins.empty:
        ax.axis("off")
        ax.text(0.5, 0.5, "No out-of-sample predictions", ha="center", va="center")
        save_figure(fig, path)
        return
    ax.plot([0, 1], [0, 1], color="#c9c8c2", linewidth=1.0, label="calibrated")
    styles = (
        ("raw", "raw (risk-neutral)", GREY, ":", "o"),
        ("pooled", "pooled map", BLUE, "-", "s"),
        ("regime", "regime maps", ORANGE, "--", "^"),
    )
    for variant, label, colour, line, marker in styles:
        part = bins.loc[(bins["variant"] == variant) & (bins["n"] > 0)]
        ax.plot(
            part["mean_predicted"],
            part["frequency_realised"],
            color=colour,
            linestyle=line,
            marker=marker,
            markersize=4,
            linewidth=1.75,
            label=label,
        )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Mean predicted probability of finishing below the strike", color=INK_MUTED)
    ax.set_ylabel("Realised frequency", color=INK_MUTED)
    ax.set_title(
        "Out-of-sample reliability: pooled against regime maps", loc="left", fontsize=10, color=INK
    )
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    style_axes(ax)
    save_figure(fig, path)


# --- command line ----------------------------------------------------------------------------


def write_outputs(result: StepOne, lab_dir: Path, out: Path) -> None:
    """Write the lab files, the markdown and the figure.

    Args:
        result: The step-1 results.
        lab_dir: The growth lab directory (gitignored).
        out: The markdown path; the figure goes to ``IMAGE`` next to it.
    """
    lab_dir.mkdir(parents=True, exist_ok=True)
    result.features.to_parquet(lab_dir / REGIME_FILE, index=False)
    regime_maps_to_frame(result.maps).to_parquet(lab_dir / MAPS_FILE, index=False)
    result.comparison.to_csv(lab_dir / COMPARISON_FILE, index=False)
    decision = {**asdict(result.decision), "chosen": result.decision.chosen}
    (lab_dir / DECISION_FILE).write_text(json.dumps(decision, indent=2) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(result))
    plot_reliability(result.reliability, out.parent / IMAGE)


def main(argv: Sequence[str] | None = None) -> int:
    """Run step 1.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        0 on success; 2 when an input is missing or locked; 3 when a check fails.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=Path(".dbt-local/oap.duckdb"))
    parser.add_argument("--lab-dir", type=Path, default=Path(".dbt-local/growth-lab"))
    parser.add_argument("--out", type=Path, default=Path("docs/regime-calibration.md"))
    args = parser.parse_args(argv)
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
        result = run(con)
    finally:
        con.close()
    if result.mismatched:
        _log(f"refitted pooled maps differ from gold.calibration_map: {list(result.mismatched)}")
        return 3
    if result.leaking:
        _log(f"maps trained on expirations at or after their cutoff: {list(result.leaking)}")
        return 3
    write_outputs(result, args.lab_dir, args.out)
    d = result.decision
    print(
        f"decision: {d.chosen} (Brier regime minus pooled {d.difference:+.5f}, 95% CI "
        f"{d.ci_low:+.5f} to {d.ci_high:+.5f}); wrote {args.out}, {args.out.parent / IMAGE} "
        f"and the files in {args.lab_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
