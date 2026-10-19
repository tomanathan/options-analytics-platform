"""Rule lab: score every eligible spread once, then sweep a grid of selection rules.

A one-time study, not a pipeline step, in two stages that can run together:

* ``--score`` opens the DuckDB file read-only and, for every session from ``--start`` with an
  ok snapshot, runs ``oap.analytics.strategy.backtest_session`` exactly as
  ``backtest_entry_rule.py`` does (the session's walk-forward map, never the production map),
  keeps every eligible spread with its full ``SPREAD_COLUMNS``, settles it at expiry and
  writes ``scored_trades.parquet``. It also computes the regime features of
  ``oap.analytics.rulelab`` for every underlying and session (``fct_underlying_daily`` for
  the returns, ``fct_option_quote`` for the near-the-money IV) and writes
  ``regime.parquet``. Both go to ``--lab-dir`` (gitignored).
* ``--sweep`` reads the two files, evaluates the rules of ``rule_grid`` (the first
  ``--grid-limit`` of them when given; the baseline is always first), writes every result
  to ``sweep.csv`` in ``--lab-dir``, and renders the comparison to ``--out`` with
  ``img/rule_lab_holdout.png`` next to it. Rules are chosen on the dev years only (before
  ``--holdout-year``) and reported on the hold-out.

Units: credits and payoffs in dollars per share, returns as decimals in the data and
percentages in the text (return on max loss over the holding period), volatility as a
decimal, time in calendar days.

Usage: ``python -m scripts.rule_lab --score [--db .dbt-local/oap.duckdb] [--start 2021-01-01]``
then ``python -m scripts.rule_lab --sweep [--out docs/rule-lab.md] [--grid-limit N]
[--holdout-year 2025] [--min-dev-trades 400]``, both with ``[--lab-dir .dbt-local/rule-lab]``.
Exit codes: 0 on success; 2 when the database, a table or a cache file is missing or the
database is locked; 3 when a scored trade used a map that could have seen its outcome.
"""

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import duckdb
import pandas as pd
from matplotlib.figure import Figure

from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.io import read_table
from oap.analytics.rulelab import (
    ATM_MIN_DTE,
    BASELINE_RULE,
    IV_QUOTE_COLUMNS,
    Picks,
    PreparedTrades,
    Rule,
    atm_iv,
    describe_rule,
    evaluate_positions,
    flatten,
    pick_rules,
    prepare,
    regime_features,
    rule_fields,
    rule_grid,
    select_positions,
)
from oap.analytics.strategy import (
    ELIGIBLE_ALL,
    SETTLED_COLUMNS,
    backtest_session,
    equity_curve,
    leaking_trades,
    settle_trades,
)
from scripts.backtest_entry_rule import (
    BLUE,
    GREY,
    INK,
    INK_MUTED,
    ORANGE,
    REQUIRED_TABLES,
    fmt_count,
    fmt_day,
    fmt_fixed,
    fmt_missing,
    fmt_percent,
    fmt_table,
    load_inputs,
    missing_tables,
    month_quotes,
    months,
    ok_sessions,
    save_figure,
    style_axes,
)

LAB_TABLES: Final[tuple[str, ...]] = (*REQUIRED_TABLES, "fct_underlying_daily")
"""Tables of the ``gold`` schema the rule lab reads."""

SCORED_FILE: Final = "scored_trades.parquet"
REGIME_FILE: Final = "regime.parquet"
SWEEP_FILE: Final = "sweep.csv"
HOLDOUT_IMAGE: Final = "img/rule_lab_holdout.png"
SCORE_PROGRESS_EVERY: Final = 100
SWEEP_PROGRESS_EVERY: Final = 100
TOP_RULES: Final = 10

_DAILY_SQL: Final = "select underlying, trade_date, log_return from gold.fct_underlying_daily"
_QUOTE_DATES_SQL: Final = "select distinct trade_date from gold.fct_option_quote order by 1"
_IV_SQL: Final = (
    "select underlying, trade_date, expiration, cast(strike as double) as strike, "
    "option_right, cast(source_iv as double) as source_iv, "
    "cast(underlying_close as double) as underlying_close, dte_days from quotes "
    "where dte_days >= {min_dte} and source_iv > 0 "
    "and trade_date >= DATE '{first}' and trade_date <= DATE '{last}'"
)


# --- scoring ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreResult:
    """Output of the scoring stage.

    Attributes:
        trades: Every eligible spread of every scored session, settled (``SETTLED_COLUMNS``).
        regime: Regime features (``REGIME_COLUMNS`` of ``oap.analytics.rulelab``).
        map_table: ``calibration_map`` rows, for the out-of-sample check.
        sessions: Sessions scored.
        unsettled: Spreads dropped because their expiration has no settlement close yet.
        runtime_seconds: Wall time in seconds.
    """

    trades: pd.DataFrame
    regime: pd.DataFrame
    map_table: pd.DataFrame
    sessions: int
    unsettled: int
    runtime_seconds: float


def _log(message: str) -> None:
    """Write a progress line to standard error."""
    print(message, file=sys.stderr)


def score_all(con: duckdb.DuckDBPyConnection, *, start: date) -> ScoreResult:
    """Score and settle every eligible spread from ``start`` and compute the regime features.

    Args:
        con: Read-only connection to a DuckDB file with the ``gold`` schema.
        start: First session scored. The regime features use every session, so the
            120-session IV rank is defined from the first scored session when enough history
            precedes it.

    Returns:
        The scored trades, regime features and map table.
    """
    inputs = load_inputs(con)
    sessions = ok_sessions(con, start)
    parts: list[pd.DataFrame] = []
    unsettled = done = 0
    began = time.monotonic()
    _log(f"scoring {len(sessions)} sessions from {start.isoformat()}")
    for month in months(sessions):
        quotes = month_quotes(con, month)
        for day in month:
            session = quotes.loc[quotes["trade_date"] == pd.Timestamp(day)]
            trades = backtest_session(
                session, inputs.snapshots, inputs.maps, DEFAULT_CONFIG, top_n=1
            )
            trades = trades.loc[trades["strategy"] == ELIGIBLE_ALL]
            settled, dropped = settle_trades(trades, inputs.outcomes)
            unsettled += dropped
            if not settled.empty:
                parts.append(settled)
            done += 1
            if done % SCORE_PROGRESS_EVERY == 0:
                _log(
                    f"{done}/{len(sessions)} sessions, up to {day.isoformat()}, "
                    f"{time.monotonic() - began:.0f}s"
                )
    trades = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame({c: pd.Series(dtype="object") for c in SETTLED_COLUMNS})
    )
    _log(f"scored {done} sessions, {len(trades)} eligible spreads; computing regime features")
    regime = regime_features(read_table(con.sql(_DAILY_SQL)), _atm_iv_all(con), DEFAULT_CONFIG)
    runtime = time.monotonic() - began
    _log(f"done in {runtime:.1f}s")
    return ScoreResult(
        trades=trades,
        regime=regime,
        map_table=inputs.map_table,
        sessions=done,
        unsettled=unsettled,
        runtime_seconds=runtime,
    )


def _atm_iv_all(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Compute ``atm_iv`` for every session of ``fct_option_quote``, one month at a time."""
    dates = [pd.Timestamp(r[0]).date() for r in con.execute(_QUOTE_DATES_SQL).fetchall()]
    rel = con.table("gold.fct_option_quote")
    parts = []
    for month in months(dates):
        sql = _IV_SQL.format(
            min_dte=ATM_MIN_DTE, first=month[0].isoformat(), last=month[-1].isoformat()
        )
        parts.append(atm_iv(read_table(rel.query("quotes", sql))[list(IV_QUOTE_COLUMNS)]))
    if not parts:
        return atm_iv(pd.DataFrame({c: pd.Series(dtype="object") for c in IV_QUOTE_COLUMNS}))
    return pd.concat(parts, ignore_index=True)


# --- sweep -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class LabReport:
    """Everything the markdown and the figure are rendered from.

    Attributes:
        results: One row per rule: ``rule_fields`` and the ``flatten`` metrics.
        picks: Output of ``pick_rules``.
        rules: The evaluated rules keyed by ``rule_id``.
        grid_size: Rules in the full grid.
        dev_years: Calendar years of the development period.
        holdout_years: Calendar years of the hold-out.
        first_session: First trade date in the cache, or None.
        last_session: Last trade date in the cache, or None.
        n_scored: Settled eligible spreads in the cache.
        n_guarded: Of those, the spreads that pass every entry guard.
        min_dev_trades: Fewest dev trades for a rule to be ranked.
        runtime_seconds: Wall time of the sweep loop, in seconds.
    """

    results: pd.DataFrame
    picks: Picks
    rules: dict[str, Rule]
    grid_size: int
    dev_years: tuple[int, ...]
    holdout_years: tuple[int, ...]
    first_session: date | None
    last_session: date | None
    n_scored: int
    n_guarded: int
    min_dev_trades: int
    runtime_seconds: float


def split_years(trades: pd.DataFrame, holdout_year: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Split the out-of-sample trade years into dev (before ``holdout_year``) and hold-out.

    Args:
        trades: Settled trades with ``trade_date`` and ``is_out_of_sample``.
        holdout_year: First calendar year of the hold-out.

    Returns:
        ``(dev_years, holdout_years)``, each ascending.
    """
    oos = trades.loc[trades["is_out_of_sample"].astype(bool)]
    years = sorted({int(y) for y in pd.to_datetime(oos["trade_date"]).dt.year})
    return (
        tuple(y for y in years if y < holdout_year),
        tuple(y for y in years if y >= holdout_year),
    )


def sweep(
    prepared: PreparedTrades,
    rules: Sequence[Rule],
    *,
    dev_years: Sequence[int],
    holdout_years: Sequence[int],
) -> tuple[pd.DataFrame, float]:
    """Evaluate every rule, logging progress every ``SWEEP_PROGRESS_EVERY`` rules.

    Args:
        prepared: Output of ``prepare`` on the cache.
        rules: Rules to evaluate.
        dev_years: Calendar years of the development period.
        holdout_years: Calendar years of the hold-out.

    Returns:
        One row per rule (``rule_fields`` and ``flatten`` columns) and the wall time in
        seconds.
    """
    rows = []
    began = time.monotonic()
    for i, rule in enumerate(rules, start=1):
        metrics = evaluate_positions(
            prepared,
            select_positions(prepared, rule),
            dev_years=dev_years,
            holdout_years=holdout_years,
            config=DEFAULT_CONFIG,
        )
        rows.append({**rule_fields(rule), **flatten(metrics)})
        if i % SWEEP_PROGRESS_EVERY == 0 or i == len(rules):
            _log(f"{i}/{len(rules)} rules, {time.monotonic() - began:.1f}s")
    return pd.DataFrame(rows), time.monotonic() - began


def holdout_curves(
    prepared: PreparedTrades, series: Sequence[tuple[str, Rule]], holdout_years: Sequence[int]
) -> pd.DataFrame:
    """Return the hold-out equity curves (one dollar per session) of some rules.

    Args:
        prepared: Output of ``prepare``.
        series: ``(label, rule)`` pairs; the label becomes the ``strategy`` column.
        holdout_years: Calendar years of the hold-out.

    Returns:
        Rows of ``equity_curve`` with ``basis="session"``.
    """
    parts = []
    for label, rule in series:
        rows = prepared.frame.iloc[select_positions(prepared, rule)]
        keep = rows["is_out_of_sample"].astype(bool) & rows["trade_date"].dt.year.isin(
            list(holdout_years)
        )
        parts.append(rows.loc[keep].assign(strategy=label))
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if frame.empty:
        return frame
    return equity_curve(frame, basis="session")


# --- markdown --------------------------------------------------------------------------------


def _years(years: Sequence[int]) -> str:
    """Format a run of years, such as ``2021-2024``, or ``none``."""
    if not years:
        return "none"
    return str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"


def _result(report: LabReport, rule_id: str) -> pd.Series:
    """Return the result row of one rule."""
    return report.results.loc[report.results["rule_id"] == rule_id].iloc[0]


def _holdout_return(row: pd.Series) -> str:
    """Format the hold-out mean realised return with its interval."""
    value = fmt_percent(row["mean_realised_return_holdout"], 2)
    low, high = (
        row["mean_realised_return_ci_low_holdout"],
        row["mean_realised_return_ci_high_holdout"],
    )
    if fmt_missing(low) or fmt_missing(high):
        return value
    return f"{value} ({fmt_percent(low, 2)} to {fmt_percent(high, 2)})"


PICK_HEADERS: Final[tuple[str, ...]] = (
    "Pick",
    "Rule",
    "Hold-out trades",
    "Win rate",
    "Predicted POP",
    "Mean realised return (95% CI)",
    "Total return on capital at risk",
    "Sharpe per trade",
    "Max drawdown ($1/session)",
    "Max-loss rate",
)

TOP_HEADERS: Final[tuple[str, ...]] = (
    "#",
    "Rule",
    "Dev trades",
    "Dev Sharpe",
    "Dev mean return",
    "Dev max drawdown",
    "Hold-out trades",
    "Hold-out win rate",
    "Hold-out predicted POP",
    "Hold-out mean return (95% CI)",
    "Hold-out total return",
    "Hold-out Sharpe",
    "Hold-out max drawdown",
)


def _pick_row(report: LabReport, label: str, rule_id: str) -> list[str]:
    """Render one row of the headline table (hold-out metrics)."""
    row = _result(report, rule_id)
    return [
        label,
        f"`{rule_id}`",
        fmt_count(row["n_trades_holdout"]),
        fmt_percent(row["win_rate_holdout"]),
        fmt_percent(row["mean_predicted_pop_holdout"]),
        _holdout_return(row),
        fmt_percent(row["total_return_holdout"], 2),
        fmt_fixed(row["sharpe_per_trade_holdout"], 3),
        fmt_fixed(row["max_drawdown_holdout"]),
        fmt_percent(row["max_loss_rate_holdout"]),
    ]


def _pick_paragraph(report: LabReport, title: str, rule_id: str, why: str) -> str:
    """Render the paragraph stating one headline pick in words."""
    row = _result(report, rule_id)
    base = _result(report, BASELINE_RULE.rule_id)
    return (
        f"**{title}: `{rule_id}`.** {describe_rule(report.rules[rule_id])} {why} "
        f"On dev it made {fmt_count(row['n_trades_dev'])} trades with a Sharpe per trade of "
        f"{fmt_fixed(row['sharpe_per_trade_dev'], 3)} and a mean realised return of "
        f"{fmt_percent(row['mean_realised_return_dev'], 2)} (baseline "
        f"{fmt_fixed(base['sharpe_per_trade_dev'], 3)} and "
        f"{fmt_percent(base['mean_realised_return_dev'], 2)}). On the hold-out it made "
        f"{fmt_count(row['n_trades_holdout'])} trades, won {fmt_percent(row['win_rate_holdout'])} "
        f"against a predicted {fmt_percent(row['mean_predicted_pop_holdout'])}, and returned "
        f"{_holdout_return(row)} per trade and {fmt_percent(row['total_return_holdout'], 2)} on "
        f"capital at risk (baseline {fmt_percent(base['mean_realised_return_holdout'], 2)} and "
        f"{fmt_percent(base['total_return_holdout'], 2)}). {_interval_sentence(row)}"
    )


def _interval_sentence(row: pd.Series) -> str:
    """Say whether the hold-out interval of the mean realised return excludes zero."""
    low, high = (
        row["mean_realised_return_ci_low_holdout"],
        row["mean_realised_return_ci_high_holdout"],
    )
    if fmt_missing(low) or fmt_missing(high):
        return "The hold-out has too few trades for an interval."
    if float(low) > 0:
        return "Its hold-out interval lies above zero."
    if float(high) < 0:
        return "Its hold-out interval lies below zero."
    return (
        "Its hold-out interval includes zero, so a positive mean return is not established at "
        "95% on the hold-out alone."
    )


def _headline_section(report: LabReport) -> str:
    """Render the two headline picks against the baseline."""
    picks = report.picks
    head = "## Headline picks (hold-out)\n\n"
    if picks.best_overall is None:
        return head + (
            f"No rule has at least {fmt_count(report.min_dev_trades)} dev trades and a finite "
            "dev drawdown, so nothing is picked. The baseline's hold-out row is below.\n\n"
            + fmt_table(
                PICK_HEADERS,
                [_pick_row(report, "Baseline", BASELINE_RULE.rule_id)],
                left=(0, 1),
            )
        )
    rows = [
        _pick_row(report, "Baseline (current Top 10)", BASELINE_RULE.rule_id),
        _pick_row(report, "Best overall", picks.best_overall),
    ]
    paragraphs = [
        _pick_paragraph(
            report,
            "Best overall",
            picks.best_overall,
            "It has the highest dev Sharpe per trade of every rule with enough dev trades.",
        )
    ]
    if picks.best_roi is not None:
        rows.append(_pick_row(report, "Best ROI", picks.best_roi))
        paragraphs.append(
            _pick_paragraph(
                report,
                "Best ROI",
                picks.best_roi,
                "It has the highest dev mean realised return among those rules whose dev "
                f"drawdown is below the median of all rules ({fmt_fixed(picks.drawdown_median)}).",
            )
        )
    else:
        paragraphs.append(
            "**Best ROI:** no rule with enough dev trades has a dev drawdown below the median "
            f"of all rules ({fmt_fixed(picks.drawdown_median)})."
        )
    note = (
        "Hold-out figures are per trade on max loss at the natural fill, held to expiry; the "
        "interval resamples expiration dates. Drawdowns put one dollar of maximum loss on each "
        "session, split across its trades."
    )
    return (
        head
        + fmt_table(PICK_HEADERS, rows, left=(0, 1))
        + "\n\n"
        + "\n\n".join([*paragraphs, note])
    )


def _top_row(report: LabReport, label: str, rule_id: str) -> list[str]:
    """Render one row of the top-rules table."""
    row = _result(report, rule_id)
    return [
        label,
        f"`{rule_id}`",
        fmt_count(row["n_trades_dev"]),
        fmt_fixed(row["sharpe_per_trade_dev"], 3),
        fmt_percent(row["mean_realised_return_dev"], 2),
        fmt_fixed(row["max_drawdown_dev"]),
        fmt_count(row["n_trades_holdout"]),
        fmt_percent(row["win_rate_holdout"]),
        fmt_percent(row["mean_predicted_pop_holdout"]),
        _holdout_return(row),
        fmt_percent(row["total_return_holdout"], 2),
        fmt_fixed(row["sharpe_per_trade_holdout"], 3),
        fmt_fixed(row["max_drawdown_holdout"]),
    ]


def _top_section(report: LabReport) -> str:
    """Render the top rules by dev Sharpe with their hold-out metrics, and the baseline."""
    qualified = report.picks.qualified
    ids = [str(r) for r in qualified["rule_id"].head(TOP_RULES)]
    rows = [_top_row(report, str(i), rule_id) for i, rule_id in enumerate(ids, start=1)]
    rows.append(_top_row(report, "baseline", BASELINE_RULE.rule_id))
    legend = (
        f"Ranked by dev Sharpe per trade among the {fmt_count(len(qualified))} rules with at "
        f"least {fmt_count(report.min_dev_trades)} dev trades and a finite dev drawdown; the "
        "hold-out columns are the honest numbers. Rule ids read ranking (`rm` mid return, `rn` "
        "natural return, `rr` reward to risk, `kg` Kelly growth, `ps` shrunk-POP return), DTE "
        "band (`dany` for all), short-strike moneyness band in percent (`many` for all), `one` "
        "spread per underlying and expiry or `all`, regime (`any`, `up`, `calm`, `upcalm`, "
        "`ivr`), natural edge margin in percent and spreads per session."
    )
    return (
        f"## Top {TOP_RULES} rules on dev, with their hold-out results\n\n"
        + legend
        + "\n\n"
        + fmt_table(TOP_HEADERS, rows, left=(0, 1))
    )


def _comparisons_section(report: LabReport) -> str:
    """Render the multiple-comparisons sanity check."""
    picks = report.picks
    base = _result(report, BASELINE_RULE.rule_id)
    if picks.median_rule is None:
        median = "No rule qualifies, so there is no median dev rule."
    else:
        row = _result(report, picks.median_rule)
        median = (
            f"The median dev rule (`{picks.median_rule}`, dev Sharpe "
            f"{fmt_fixed(row['sharpe_per_trade_dev'], 3)}) has a hold-out Sharpe of "
            f"{fmt_fixed(row['sharpe_per_trade_holdout'], 3)}."
        )
    return (
        "## Multiple-comparisons check\n\n"
        f"Of {fmt_count(len(picks.qualified))} qualifying rules, {fmt_count(picks.beat_dev)} beat "
        f"the baseline's dev Sharpe of {fmt_fixed(base['sharpe_per_trade_dev'], 3)}; of those, "
        f"{fmt_count(picks.beat_both)} also beat its hold-out Sharpe of "
        f"{fmt_fixed(base['sharpe_per_trade_holdout'], 3)}. {median} A rule that leads on dev and "
        "falls back on the hold-out is what searching many rules on the same data produces, so "
        "the hold-out column, not the dev ranking, is the estimate to quote."
    )


def _protocol_section(report: LabReport) -> str:
    """Render the protocol paragraph."""
    return (
        "## Protocol\n\n"
        f"Every eligible spread of every session from {fmt_day(report.first_session)} to "
        f"{fmt_day(report.last_session)} was scored once by the live scoring path with the "
        "walk-forward calibration map of its year (fitted only on expirations before 1 January) "
        f"and settled at expiry: {fmt_count(report.n_scored)} spreads, of which "
        f"{fmt_count(report.n_guarded)} pass every entry guard. Each rule chooses only among "
        "those guarded spreads: its gates (days to expiry, short-strike moneyness, regime, "
        "natural credit over fair credit), then its ranking (ties broken by the live entry "
        "rank), then at most one spread per underlying and expiry when asked, then the top "
        f"{BASELINE_RULE.top_n} per session. {fmt_count(len(report.results))} of the "
        f"{fmt_count(report.grid_size)} grid rules were evaluated "
        f"({report.runtime_seconds:.1f}s). A trade belongs to the period of its trade date's "
        f"year: dev is {_years(report.dev_years)}, the hold-out is "
        f"{_years(report.holdout_years)}. Rules are ranked on dev only, by Sharpe per trade, "
        f"among those with at least {fmt_count(report.min_dev_trades)} dev trades and a finite "
        "dev drawdown; the best ROI pick is the highest dev mean realised return among those "
        "whose dev drawdown is below the median of all rules. The hold-out was not used to "
        "choose anything. The baseline is the current Top 10 rule "
        f"(`{BASELINE_RULE.rule_id}`), which reproduces the live `entry_top10` selection. Every "
        "result is in `sweep.csv` in the lab directory."
    )


def _holdout_span(report: LabReport) -> str:
    """Format the hold-out length in years, from 1 January of its first year to the last session."""
    if not report.holdout_years or report.last_session is None:
        return "no sessions"
    days = (report.last_session - date(report.holdout_years[0], 1, 1)).days + 1
    return f"about {days / 365.25:.2f} years"


def _caveats_section(report: LabReport) -> str:
    """Render the caveats paragraph."""
    return (
        "## Caveats\n\n"
        f"{fmt_count(len(report.results))} rules were searched, so the best dev Sharpe is "
        "inflated by selection; only the hold-out figures are unbiased, and the hold-out is "
        f"short ({_years(report.holdout_years)}, {_holdout_span(report)}) with "
        "overlapping positions, so its intervals are wide. A December dev trade can expire in "
        "the hold-out year, so the two periods share a few weeks of market moves. Regime "
        "features use end-of-day data of the trade date, the same close the fill is assumed at; "
        "a trader would see them only at the close. Fills are at the natural credit (short bid "
        "minus long ask) with no commissions or further slippage, and every spread is held to "
        "expiry and settled at the settlement close, with no early management or assignment. "
        "Only settled expiries are scored, so the last hold-out sessions hold short-dated "
        "spreads only and a long-DTE rule's hold-out ends weeks before the baseline's. "
        "The universe is today's large caps (hindsight in the universe biases realised losses "
        "low), and only ok snapshots are scored. This is a historical measurement of selection "
        "rules, not trade advice."
    )


def render_markdown(report: LabReport) -> str:
    """Render the rule lab report. The text is a pure function of ``report``.

    Args:
        report: The sweep results and picks.

    Returns:
        The markdown, ending in a newline.
    """
    head = (
        "# Rule lab: put credit spread selection rules on a hold-out\n\n"
        f"{fmt_count(len(report.results))} candidate rules for choosing put credit spreads were "
        "run through the walk-forward backtest of the entry rule. Each was ranked on the dev "
        f"years ({_years(report.dev_years)}) and is reported on the hold-out "
        f"({_years(report.holdout_years)}), which no choice looked at. The baseline is the "
        "current Top 10 rule: rank by annualised return on max loss at the mid credit."
    )
    figure = (
        "## Hold-out equity\n\n"
        f"![Hold-out cumulative realised return]({HOLDOUT_IMAGE})\n\n"
        "Cumulative realised return on max loss of the hold-out trades of the baseline and the "
        "two picks, one dollar of maximum loss per session split across its trades."
    )
    sections = [
        head,
        _headline_section(report),
        _top_section(report),
        _comparisons_section(report),
        _protocol_section(report),
        figure,
        _caveats_section(report),
    ]
    return "\n\n".join(sections) + "\n"


# --- figure ----------------------------------------------------------------------------------


def plot_holdout(curve: pd.DataFrame, path: Path, labels: Sequence[str]) -> None:
    """Write the hold-out equity curves.

    Args:
        curve: Output of ``holdout_curves``; ``strategy`` holds the labels.
        path: Where to write the PNG.
        labels: Series in drawing order: baseline, best overall, best ROI (when distinct).
            An empty ``curve`` gives a placeholder figure.
    """
    fig = Figure(figsize=(8.0, 4.6), facecolor="white", layout="constrained")
    ax = fig.subplots()
    if curve.empty:
        ax.axis("off")
        ax.text(0.5, 0.5, "No hold-out trades", ha="center", va="center", color=INK_MUTED)
        save_figure(fig, path)
        return
    styles = ((GREY, ":", 1.5), (BLUE, "-", 2.0), (ORANGE, "--", 1.75))
    for label, (colour, line, width) in zip(labels, styles, strict=False):
        part = curve.loc[curve["strategy"] == label]
        if part.empty:
            continue
        ax.plot(
            pd.to_datetime(part["trade_date"]),
            part["cumulative_return"],
            color=colour,
            linestyle=line,
            linewidth=width,
            label=label,
        )
    ax.axhline(0, color=GREY, linewidth=0.8)
    ax.set_ylabel(
        "Cumulative return (dollars per dollar of max loss per session)",
        color=INK_MUTED,
        fontsize=9,
    )
    ax.set_title(
        "Hold-out realised return of the baseline and the rule lab picks",
        loc="left",
        fontsize=10,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8, loc="best")
    style_axes(ax)
    save_figure(fig, path)


def _series(picks: Picks) -> list[tuple[str, str]]:
    """Return ``(label, rule_id)`` for the baseline and the distinct picks."""
    series = [("baseline (current Top 10)", BASELINE_RULE.rule_id)]
    if picks.best_overall is not None and picks.best_overall == picks.best_roi:
        series.append((f"best overall and best ROI ({picks.best_overall})", picks.best_overall))
        return series
    if picks.best_overall is not None:
        series.append((f"best overall ({picks.best_overall})", picks.best_overall))
    if picks.best_roi is not None:
        series.append((f"best ROI ({picks.best_roi})", picks.best_roi))
    return series


# --- command line ----------------------------------------------------------------------------


def _run_score(args: argparse.Namespace) -> int:
    """Run the scoring stage; return the exit code."""
    if not args.db.exists():
        _log(f"{args.db} does not exist: run `make dbt-build-local` first")
        return 2
    try:
        con = duckdb.connect(str(args.db), read_only=True)
    except duckdb.IOException as exc:
        _log(f"cannot open {args.db} (is a build writing it?): {exc}")
        return 2
    try:
        missing = missing_tables(con, LAB_TABLES)
        if missing:
            _log(f"gold tables missing: {', '.join(missing)}")
            return 2
        result = score_all(con, start=args.start)
    finally:
        con.close()
    if not result.trades.empty:
        leaks = leaking_trades(result.trades, result.map_table)
        if not leaks.empty:
            _log(f"{len(leaks)} trades used a map trained on their own outcomes")
            return 3
    args.lab_dir.mkdir(parents=True, exist_ok=True)
    result.trades.to_parquet(args.lab_dir / SCORED_FILE, index=False)
    result.regime.to_parquet(args.lab_dir / REGIME_FILE, index=False)
    print(
        f"wrote {args.lab_dir / SCORED_FILE} ({len(result.trades)} spreads, "
        f"{result.unsettled} unsettled dropped) and {args.lab_dir / REGIME_FILE} "
        f"({len(result.regime)} rows) in {result.runtime_seconds:.1f}s"
    )
    return 0


def _session_date(trades: pd.DataFrame, which: str) -> date | None:
    """Return the first or last trade date of the cache, or None when it is empty."""
    if trades.empty:
        return None
    dates = pd.to_datetime(trades["trade_date"])
    return (dates.min() if which == "first" else dates.max()).date()


def _run_sweep(args: argparse.Namespace) -> int:
    """Run the sweep stage; return the exit code."""
    scored, regime_path = args.lab_dir / SCORED_FILE, args.lab_dir / REGIME_FILE
    for path in (scored, regime_path):
        if not path.exists():
            _log(f"{path} does not exist: run with --score first")
            return 2
    trades = pd.read_parquet(scored)
    regime = pd.read_parquet(regime_path)
    began = time.monotonic()
    prepared = prepare(trades, regime)
    grid = rule_grid()
    rules = list(grid if args.grid_limit is None else grid[: args.grid_limit])
    dev_years, holdout_years = split_years(trades, args.holdout_year)
    _log(
        f"sweeping {len(rules)} rules over {len(prepared.frame)} guarded spreads "
        f"(prepared in {time.monotonic() - began:.1f}s)"
    )
    results, runtime = sweep(prepared, rules, dev_years=dev_years, holdout_years=holdout_years)
    args.lab_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.lab_dir / SWEEP_FILE, index=False)
    picks = pick_rules(
        results, baseline_id=BASELINE_RULE.rule_id, min_dev_trades=args.min_dev_trades
    )
    report = LabReport(
        results=results,
        picks=picks,
        rules={r.rule_id: r for r in rules},
        grid_size=len(grid),
        dev_years=dev_years,
        holdout_years=holdout_years,
        first_session=_session_date(trades, "first"),
        last_session=_session_date(trades, "last"),
        n_scored=len(trades),
        n_guarded=len(prepared.frame),
        min_dev_trades=args.min_dev_trades,
        runtime_seconds=runtime,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(report))
    series = _series(picks)
    curve = holdout_curves(
        prepared, [(label, report.rules[i]) for label, i in series], holdout_years
    )
    plot_holdout(curve, args.out.parent / HOLDOUT_IMAGE, [label for label, _ in series])
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
    parser.add_argument("--score", action="store_true", help="score and cache every spread")
    parser.add_argument("--sweep", action="store_true", help="evaluate the rule grid")
    parser.add_argument("--db", type=Path, default=Path(".dbt-local/oap.duckdb"))
    parser.add_argument("--lab-dir", type=Path, default=Path(".dbt-local/rule-lab"))
    parser.add_argument("--out", type=Path, default=Path("docs/rule-lab.md"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2021, 1, 1))
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
