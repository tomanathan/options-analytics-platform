"""Backtest the "Top N to enter" rule on every historical session of the gold schema.

A one-time study, not a pipeline step. It opens the DuckDB file read-only, reads
``gold.calibration_snapshot``, ``gold.fct_expiration_outcome`` and ``gold.calibration_map`` once
and ``gold.fct_option_quote`` one month at a time, and for each session runs
``oap.analytics.strategy.backtest_session``: the session is ranked by the live scoring path
with the walk-forward map of its year (never the production map), the three strategies are
selected, and every trade is held to expiry and settled at the settlement close. It writes a
markdown summary and ``img/strategy_equity.png`` next to it, and logs progress every 100
sessions.

Units: credits and payoffs in dollars per share, returns as decimals in the data and
percentages in the text (return on max loss over the holding period), time in calendar days.

Usage: ``backtest_entry_rule.py [--db .dbt-local/oap.duckdb] [--out docs/backtest-entry-rule.md]
[--top 10] [--start 2021-01-01]``.
Exit codes: 0 on success; 2 when the database or a table is missing or the file is locked; 3
when a trade used a map that could have seen its outcome (the out-of-sample check failed).
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
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from oap.analytics.backtest import maps_from_frame
from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.io import QUOTE_SELECT, read_outcomes, read_table
from oap.analytics.sample import SnapshotStatus
from oap.analytics.scoring import ENTRY_RULE, ENTRY_RULE_SINCE, PREVIOUS_ENTRY_RULE
from oap.analytics.strategy import (
    SETTLED_COLUMNS,
    backtest_session,
    equity_curve,
    leaking_trades,
    settle_trades,
    strategy_metrics,
    strategy_names,
)
from oap.engine.calibration import CalibrationMap

REQUIRED_TABLES: Final[tuple[str, ...]] = (
    "fct_option_quote",
    "fct_expiration_outcome",
    "calibration_map",
    "calibration_snapshot",
)
"""Tables of the ``gold`` schema the backtest reads."""

PREVIOUS_RULE_RESULT: Final = (
    "10,458 out-of-sample trades from 2021-01-04 to 2026-10-05 that won 64.1% against 73.0% "
    "predicted and returned -2.04% on capital at risk"
)
"""What this backtest measured for ``PREVIOUS_ENTRY_RULE`` on 2026-10-19, before the change."""

EQUITY_IMAGE: Final = "img/strategy_equity.png"
PROGRESS_EVERY: Final = 100
WORST_TRADES: Final = 10

# Categorical slots of the reference palette used by scripts/make_report.py, one line style
# per series so identity never rests on colour alone; the baseline is the neutral grey.
BLUE: Final = "#2a78d6"
ORANGE: Final = "#eb6834"
GREY: Final = "#6b6a66"
INK: Final = "#0b0b0b"
INK_MUTED: Final = "#52514e"
IMAGE_DPI: Final = 120

SNAPSHOT_SQL: Final = (
    "select underlying, trade_date, expiration, status from gold.calibration_snapshot"
)
SESSIONS_SQL: Final = (
    "select distinct trade_date from gold.calibration_snapshot where status = '{ok}' "
    "and trade_date >= DATE '{start}' order by trade_date"
)
MONTH_SQL: Final = (
    QUOTE_SELECT + " where trade_date >= DATE '{first}' and trade_date <= DATE '{last}'"
)


@dataclass(frozen=True)
class BacktestSummary:
    """Everything the markdown and the figure are rendered from.

    Attributes:
        top_n: Spreads per session of the top-``N`` strategies.
        first_session: First session scored, or None when none was.
        last_session: Last session scored, or None.
        sessions: Sessions scored (with at least one ok snapshot).
        sessions_with_trades: Sessions where ``entry_top<N>`` selected at least one spread.
        unsettled: Trades dropped because their expiration has no settlement close.
        metrics: Output of ``strategy_metrics``.
        trades: Settled trades of the recommendation strategy (all sessions), for the
            worst-trade table.
        oos_trades: Out-of-sample settled trades per strategy name.
        runtime_seconds: Wall time of the backtest loop, in seconds.
    """

    top_n: int
    first_session: date | None
    last_session: date | None
    sessions: int
    sessions_with_trades: int
    unsettled: int
    metrics: pd.DataFrame
    trades: pd.DataFrame
    oos_trades: dict[str, int]
    runtime_seconds: float


# --- formatting ------------------------------------------------------------------------------


def fmt_missing(value: object) -> bool:
    """Say whether a scalar is missing (None, NaN, NA or NaT)."""
    return value is None or bool(pd.isna(value))  # type: ignore[call-overload]


def fmt_percent(value: object, digits: int = 1) -> str:
    """Format a decimal as a percentage, or ``n/a`` when it is missing."""
    return "n/a" if fmt_missing(value) else f"{float(value) * 100:.{digits}f}%"  # type: ignore[arg-type]


def fmt_points(value: object) -> str:
    """Format a probability difference as signed percentage points, or ``n/a``."""
    return "n/a" if fmt_missing(value) else f"{float(value) * 100:+.1f} pp"  # type: ignore[arg-type]


def fmt_fixed(value: object, digits: int = 2) -> str:
    """Format a number with fixed decimals, or ``n/a`` when it is missing."""
    return "n/a" if fmt_missing(value) else f"{float(value):.{digits}f}"  # type: ignore[arg-type]


def fmt_count(value: object) -> str:
    """Format a count with thousands separators, or ``n/a`` when it is missing."""
    return "n/a" if fmt_missing(value) else f"{round(float(value)):,}"  # type: ignore[arg-type]


def fmt_day(value: object) -> str:
    """Format a date as ISO 8601, or ``n/a`` when it is missing."""
    return "n/a" if fmt_missing(value) else pd.Timestamp(str(value)).date().isoformat()


def fmt_table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], *, left: Sequence[int] = (0,)
) -> str:
    """Render a markdown table; the columns in ``left`` are left-aligned, the rest right."""
    rule = ["---" if i in left else "---:" for i in range(len(headers))]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(rule) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


_Index = dict[tuple[str, str, str, str], pd.Series]


def _index(metrics: pd.DataFrame) -> _Index:
    """Index metric rows by (strategy, segment_type, segment, metric)."""
    return {
        (str(r["strategy"]), str(r["segment_type"]), str(r["segment"]), str(r["metric"])): r
        for _, r in metrics.iterrows()
    }


def _value(index: _Index, key: tuple[str, str, str, str], column: str = "value") -> object:
    """Return one column of a metric row, or None when the row does not exist."""
    row = index.get(key)
    return None if row is None else row[column]


def _with_ci(index: _Index, strategy: str, metric: str) -> str:
    """Format an overall percentage metric with its bootstrap interval."""
    base = ("overall", "all")
    value = fmt_percent(_value(index, (strategy, *base, metric)))
    low = _value(index, (strategy, *base, f"{metric}_ci_low"))
    high = _value(index, (strategy, *base, f"{metric}_ci_high"))
    if fmt_missing(low) or fmt_missing(high):
        return value
    return f"{value} ({fmt_percent(low)} to {fmt_percent(high)})"


# --- markdown --------------------------------------------------------------------------------

OVERALL_HEADERS: Final[tuple[str, ...]] = (
    "Strategy",
    "Trades",
    "Sessions",
    "Win rate (95% CI)",
    "Predicted POP",
    "POP gap",
    "Mean realised return (95% CI)",
    "Mean predicted return",
    "Total return on capital at risk",
    "Median return",
    "Worst trade",
    "Max-loss rate",
    "Sharpe per trade",
    "Max drawdown ($1/trade)",
    "Max drawdown ($1/session)",
    "Avg DTE",
)

SEGMENT_HEADERS: Final[tuple[str, ...]] = (
    "Trades",
    "Sessions",
    "Win rate",
    "Predicted POP",
    "POP gap",
    "Mean realised return",
    "Mean predicted return",
    "Total return on capital at risk",
    "Max-loss rate",
    "Max drawdown ($1/trade)",
)

WORST_HEADERS: Final[tuple[str, ...]] = (
    "Session",
    "Underlying",
    "Expiration",
    "Short/long",
    "Natural credit",
    "POP calibrated",
    "Settlement close",
    "Payoff",
    "Realised return",
)

STRATEGY_LABELS: Final[dict[str, str]] = {
    "entry": "the live entry ranking: `rank_entry` (the rule above)",
    "return": "`rank` (raw annualised return on max loss, without the entry guards)",
    "eligible_all": "every eligible spread, equal weight (the no-selection baseline)",
}


def rule_change_sentence(top_n: int) -> str:
    """Say when and why the entry rule changed, from the rule constants.

    Args:
        top_n: Spreads per session of the backtest.

    Returns:
        One sentence.
    """
    return (
        f"The rule changed on {ENTRY_RULE_SINCE.isoformat()}: until then `entry_top{top_n}` "
        f'followed "{PREVIOUS_ENTRY_RULE}", which this backtest measured at '
        f"{PREVIOUS_RULE_RESULT}, so the product moved to the rule above, the rule-lab rule that "
        "held up on the 2025-2026 hold-out (`docs/rule-lab.md`)."
    )


def _overall_section(summary: BacktestSummary, index: _Index) -> str:
    """Render the overall comparison of the three strategies."""
    rows = []
    for strategy in strategy_names(summary.top_n):
        key = (strategy, "overall", "all")
        rows.append(
            [
                f"`{strategy}`",
                fmt_count(_value(index, (*key, "win_rate"), "n_trades")),
                fmt_count(_value(index, (*key, "win_rate"), "n_sessions")),
                _with_ci(index, strategy, "win_rate"),
                fmt_percent(_value(index, (*key, "mean_predicted_pop"))),
                fmt_points(_value(index, (*key, "pop_gap_realised"))),
                _with_ci(index, strategy, "mean_realised_return"),
                fmt_percent(_value(index, (*key, "mean_predicted_return")), 2),
                fmt_percent(_value(index, (*key, "total_return")), 2),
                fmt_percent(_value(index, (*key, "median_realised_return")), 2),
                fmt_percent(_value(index, (*key, "worst_trade_return"))),
                fmt_percent(_value(index, (*key, "max_loss_rate"))),
                fmt_fixed(_value(index, (*key, "sharpe_per_trade"))),
                fmt_fixed(_value(index, (*key, "max_drawdown"))),
                fmt_fixed(_value(index, (*key, "max_drawdown_session"))),
                fmt_fixed(_value(index, (*key, "avg_dte_days")), 1),
            ]
        )
    entry, by_return, baseline = strategy_names(summary.top_n)
    legend = (
        f"`{entry}` is {STRATEGY_LABELS['entry']}; `{by_return}` is the top {summary.top_n} by "
        f"{STRATEGY_LABELS['return']}; `{baseline}` is {STRATEGY_LABELS['eligible_all']}."
    )
    note = (
        "Returns are on max loss over the holding period. The realised return fills at the "
        "natural credit; the predicted return is the score's `expected_roc` (mid credit, "
        "interest on the collateral included), so part of the gap is the half-spread and the "
        "interest. The interval resamples expiration dates (trades expiring together share one "
        "market move). Drawdowns are in dollars per dollar of maximum loss, booked by session: "
        "$1/trade puts one dollar of maximum loss on every trade, $1/session splits one dollar "
        "equally across a session's trades, which puts strategies with different trade counts "
        "on one scale."
    )
    return (
        "## Out of sample, overall\n\n"
        + legend
        + "\n\n"
        + fmt_table(OVERALL_HEADERS, rows)
        + "\n\n"
        + note
    )


def _segment_section(
    summary: BacktestSummary, index: _Index, segment_type: str, label: str, title: str
) -> str:
    """Render one segment table of the recommendation strategy."""
    strategy = strategy_names(summary.top_n)[0]
    segments = sorted({k[2] for k in index if k[0] == strategy and k[1] == segment_type})
    rows = []
    for segment in segments:
        key = (strategy, segment_type, segment)
        rows.append(
            [
                segment,
                fmt_count(_value(index, (*key, "win_rate"), "n_trades")),
                fmt_count(_value(index, (*key, "win_rate"), "n_sessions")),
                fmt_percent(_value(index, (*key, "win_rate"))),
                fmt_percent(_value(index, (*key, "mean_predicted_pop"))),
                fmt_points(_value(index, (*key, "pop_gap_realised"))),
                fmt_percent(_value(index, (*key, "mean_realised_return")), 2),
                fmt_percent(_value(index, (*key, "mean_predicted_return")), 2),
                fmt_percent(_value(index, (*key, "total_return")), 2),
                fmt_percent(_value(index, (*key, "max_loss_rate"))),
                fmt_fixed(_value(index, (*key, "max_drawdown"))),
            ]
        )
    head = f"## {title} (`{strategy}`)\n\n"
    if not rows:
        return head + "No out-of-sample trades."
    return head + fmt_table((label, *SEGMENT_HEADERS), rows)


def _worst_section(summary: BacktestSummary) -> str:
    """Render the worst out-of-sample trades of the recommendation strategy."""
    strategy = strategy_names(summary.top_n)[0]
    head = f"## Worst {WORST_TRADES} trades (`{strategy}`, out of sample)\n\n"
    trades = summary.trades
    oos = trades.loc[trades["is_out_of_sample"].astype(bool)] if not trades.empty else trades
    if oos.empty:
        return head + "No out-of-sample trades."
    worst = oos.sort_values(["realised_return", "trade_date", "spread_key"], kind="stable").head(
        WORST_TRADES
    )
    rows = [
        [
            fmt_day(r["trade_date"]),
            str(r["underlying"]),
            fmt_day(r["expiration"]),
            f"{float(r['short_strike']):g}/{float(r['long_strike']):g}",
            fmt_fixed(r["credit_natural"]),
            fmt_percent(r["prob_profit"]),
            fmt_fixed(r["settlement_close"]),
            fmt_fixed(r["realised_payoff"]),
            fmt_percent(r["realised_return"]),
        ]
        for _, r in worst.iterrows()
    ]
    return head + fmt_table(WORST_HEADERS, rows, left=(0, 1, 2))


def _caveats_section() -> str:
    """Render the caveats paragraph."""
    first_test_year = DEFAULT_CONFIG.first_test_year
    return (
        "## Caveats\n\n"
        "Fills are at the natural credit (short bid minus long ask) at the end-of-day close, "
        "with no commissions, no slippage beyond that, no early management and no early "
        "assignment: every spread is held to expiry and settled at the settlement close. "
        "Positions overlap (a new set of spreads is entered every session while earlier ones "
        "are still open), and each trade is counted as one dollar of maximum loss, so the "
        "totals are not a compounded account balance. Each session uses the walk-forward map "
        f"of its year, fitted only on expirations before 1 January; sessions before "
        f"{first_test_year} are burn-in and excluded, and the production map is never used. "
        "Only snapshots the calibration sample keeps (`ok` status) are ranked, so a chain "
        "whose window contains a split is left out, which uses hindsight about the split. The "
        "universe is today's large caps (hindsight in the universe biases realised losses "
        "low), the vendor history misses some sessions, and the eligible-all baseline is a "
        "measurement, not a tradeable portfolio. This is a historical measurement of a "
        "ranking, not trade advice."
    )


def render_markdown(summary: BacktestSummary) -> str:
    """Render the backtest summary. The text is a pure function of ``summary``.

    Args:
        summary: The backtest results.

    Returns:
        The markdown, ending in a newline.
    """
    index = _index(summary.metrics)
    entry = strategy_names(summary.top_n)[0]
    oos = ", ".join(f"`{k}` {fmt_count(v)}" for k, v in summary.oos_trades.items()) or "none"
    head = (
        f"# Strategy backtest: the Top {summary.top_n} rule applied historically\n\n"
        f"`{entry}` takes, on every session, the spreads the live ranking would have listed "
        f'under "Top {summary.top_n} to enter": {ENTRY_RULE} Each session is scored by the '
        "same code as the latest one, with only the calibration map that existed at the time. "
        f"{rule_change_sentence(summary.top_n)}\n\n"
        f"Sessions scored: {fmt_count(summary.sessions)} ({fmt_day(summary.first_session)} to "
        f"{fmt_day(summary.last_session)}); with at least one `{entry}` trade: "
        f"{fmt_count(summary.sessions_with_trades)}. Trades dropped as unsettled: "
        f"{fmt_count(summary.unsettled)}. Out-of-sample trades: {oos}."
    )
    if summary.metrics.empty:
        body = [
            head,
            "## Out of sample, overall\n\nNo out-of-sample trades: every scored session is "
            "burn-in or used an identity map.",
        ]
    else:
        body = [
            head,
            _overall_section(summary, index),
            _segment_section(summary, index, "year", "Year", "By year"),
            _segment_section(summary, index, "underlying", "Underlying", "By underlying"),
            _worst_section(summary),
        ]
    figure = (
        f"![Cumulative realised return]({EQUITY_IMAGE})\n\n"
        "Cumulative realised return on max loss of the out-of-sample trades, one dollar of "
        f"maximum loss per session split across its trades; the shading is the drawdown of "
        f"`{entry}` below its running peak."
    )
    return "\n\n".join([*body, figure, _caveats_section()]) + "\n"


# --- figure ----------------------------------------------------------------------------------


def style_axes(ax: Axes) -> None:
    """Apply a recessive grid and spines."""
    ax.grid(True, color="#e6e5e0", linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9c8c2")
    ax.tick_params(colors=INK_MUTED, labelsize=9)


def save_figure(fig: Figure, path: Path) -> None:
    """Write a figure as a PNG with no software metadata, creating the directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=IMAGE_DPI, metadata={"Software": None}, facecolor="white")


def plot_equity(curve: pd.DataFrame, path: Path, *, top_n: int) -> None:
    """Write the cumulative realised return of the three strategies.

    Args:
        curve: Output of ``equity_curve`` on the out-of-sample trades (session basis). An
            empty frame gives a placeholder figure.
        path: Where to write the PNG.
        top_n: Spreads per session of the top-``N`` strategies, for the series names.
    """
    fig = Figure(figsize=(8.0, 4.6), facecolor="white", layout="constrained")
    ax = fig.subplots()
    if curve.empty:
        ax.axis("off")
        ax.text(0.5, 0.5, "No out-of-sample trades", ha="center", va="center", color=INK_MUTED)
        save_figure(fig, path)
        return
    entry, by_return, baseline = strategy_names(top_n)
    styles = ((entry, BLUE, "-", 2.0), (by_return, ORANGE, "--", 1.5), (baseline, GREY, ":", 1.5))
    for name, colour, line, width in styles:
        part = curve.loc[curve["strategy"] == name]
        if part.empty:
            continue
        dates = pd.to_datetime(part["trade_date"])
        ax.plot(
            dates,
            part["cumulative_return"],
            color=colour,
            linestyle=line,
            linewidth=width,
            label=name,
        )
        if name == entry:
            peak = part["cumulative_return"] + part["drawdown"]
            ax.fill_between(
                dates,
                part["cumulative_return"],
                peak,
                color=BLUE,
                alpha=0.15,
                linewidth=0,
                label=f"{entry} drawdown",
            )
    ax.axhline(0, color=GREY, linewidth=0.8)
    ax.set_ylabel(
        "Cumulative return (dollars per dollar of max loss per session)",
        color=INK_MUTED,
        fontsize=9,
    )
    ax.set_title(
        "Out-of-sample realised return of the entry rule and its baselines",
        loc="left",
        fontsize=10,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    style_axes(ax)
    save_figure(fig, path)


# --- command line ----------------------------------------------------------------------------


def missing_tables(
    con: duckdb.DuckDBPyConnection, required: Sequence[str] = REQUIRED_TABLES
) -> list[str]:
    """Return the names of the ``required`` tables that the ``gold`` schema lacks."""
    found = {
        str(r[0])
        for r in con.execute(
            "select table_name from information_schema.tables where table_schema = 'gold'"
        ).fetchall()
    }
    return [t for t in required if t not in found]


def months(sessions: Sequence[date]) -> list[list[date]]:
    """Group sorted session dates by calendar month, preserving order."""
    groups: dict[tuple[int, int], list[date]] = {}
    for day in sessions:
        groups.setdefault((day.year, day.month), []).append(day)
    return list(groups.values())


@dataclass(frozen=True)
class BacktestInputs:
    """The gold tables read once per run.

    Attributes:
        snapshots: ``calibration_snapshot`` rows (snapshot key and ``status``).
        outcomes: ``fct_expiration_outcome`` rows (settlement close in dollars per share).
        map_table: ``calibration_map`` rows.
        maps: The calibration maps keyed by map id.
    """

    snapshots: pd.DataFrame
    outcomes: pd.DataFrame
    map_table: pd.DataFrame
    maps: dict[str, CalibrationMap]


def load_inputs(con: duckdb.DuckDBPyConnection) -> BacktestInputs:
    """Read the snapshots, outcomes and calibration maps of the ``gold`` schema.

    Args:
        con: Connection to a DuckDB file with the ``gold`` schema.

    Returns:
        The inputs every session of the backtest shares.
    """
    map_table = read_table(con.table("gold.calibration_map"))
    return BacktestInputs(
        snapshots=read_table(con.sql(SNAPSHOT_SQL)),
        outcomes=read_outcomes(con.table("gold.fct_expiration_outcome")),
        map_table=map_table,
        maps=maps_from_frame(map_table),
    )


def ok_sessions(con: duckdb.DuckDBPyConnection, start: date) -> list[date]:
    """Return every session from ``start`` with at least one ok snapshot, ascending.

    Args:
        con: Connection to a DuckDB file with the ``gold`` schema.
        start: First session considered.

    Returns:
        The session dates.
    """
    sql = SESSIONS_SQL.format(ok=SnapshotStatus.OK.value, start=start.isoformat())
    return [pd.Timestamp(r[0]).date() for r in con.execute(sql).fetchall()]


def month_quotes(con: duckdb.DuckDBPyConnection, month: Sequence[date]) -> pd.DataFrame:
    """Read the quotes of a run of sessions, normally one calendar month.

    Args:
        con: Connection to a DuckDB file with the ``gold`` schema.
        month: Sorted session dates; the quotes from the first to the last are read.

    Returns:
        Quote rows with the columns of ``QUOTE_SELECT``.
    """
    sql = MONTH_SQL.format(first=month[0].isoformat(), last=month[-1].isoformat())
    return read_table(con.table("gold.fct_option_quote").query("quotes", sql))


def run_backtest(
    con: duckdb.DuckDBPyConnection, *, top_n: int, start: date
) -> tuple[BacktestSummary, pd.DataFrame, pd.DataFrame]:
    """Run the backtest over every session from ``start`` with an ok snapshot.

    Args:
        con: Read-only connection to a DuckDB file with the ``gold`` schema.
        top_n: Spreads per session of the top-``N`` strategies.
        start: First session considered.

    Returns:
        The summary, every settled trade and the map table.
    """
    inputs = load_inputs(con)
    snapshots, outcomes, map_table, maps = (
        inputs.snapshots,
        inputs.outcomes,
        inputs.map_table,
        inputs.maps,
    )
    sessions = ok_sessions(con, start)
    parts: list[pd.DataFrame] = []
    unsettled = done = 0
    began = time.monotonic()
    print(f"backtesting {len(sessions)} sessions from {start.isoformat()}", file=sys.stderr)
    for month in months(sessions):
        quotes = month_quotes(con, month)
        for day in month:
            session = quotes.loc[quotes["trade_date"] == pd.Timestamp(day)]
            trades = backtest_session(session, snapshots, maps, DEFAULT_CONFIG, top_n=top_n)
            settled, dropped = settle_trades(trades, outcomes)
            unsettled += dropped
            if not settled.empty:
                parts.append(settled)
            done += 1
            if done % PROGRESS_EVERY == 0:
                print(
                    f"{done}/{len(sessions)} sessions, up to {day.isoformat()}, "
                    f"{time.monotonic() - began:.0f}s",
                    file=sys.stderr,
                )
    runtime = time.monotonic() - began
    trades = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame({c: pd.Series(dtype="object") for c in SETTLED_COLUMNS})
    )
    entry = strategy_names(top_n)[0]
    entry_trades = trades.loc[trades["strategy"] == entry]
    oos = trades.loc[trades["is_out_of_sample"].astype(bool)] if not trades.empty else trades
    summary = BacktestSummary(
        top_n=top_n,
        first_session=sessions[0] if sessions else None,
        last_session=sessions[-1] if sessions else None,
        sessions=done,
        sessions_with_trades=int(entry_trades["trade_date"].nunique()),
        unsettled=unsettled,
        metrics=strategy_metrics(trades, config=DEFAULT_CONFIG),
        trades=entry_trades.reset_index(drop=True),
        oos_trades={name: int((oos["strategy"] == name).sum()) for name in strategy_names(top_n)},
        runtime_seconds=runtime,
    )
    print(f"done: {done} sessions, {len(trades)} trades in {runtime:.1f}s", file=sys.stderr)
    return summary, trades, map_table


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backtest on a DuckDB file and write the summary.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        0 on success; 2 when the database or a table is missing or the file is locked; 3 when
        the out-of-sample check fails.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=Path(".dbt-local/oap.duckdb"))
    parser.add_argument("--out", type=Path, default=Path("docs/backtest-entry-rule.md"))
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2020, 1, 1))
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top must be at least 1")
    if not args.db.exists():
        print(f"{args.db} does not exist: run `make dbt-build-local` first", file=sys.stderr)
        return 2
    try:
        con = duckdb.connect(str(args.db), read_only=True)
    except duckdb.IOException as exc:
        print(f"cannot open {args.db} (is a build writing it?): {exc}", file=sys.stderr)
        return 2
    try:
        missing = missing_tables(con)
        if missing:
            print(f"gold tables missing: {', '.join(missing)}", file=sys.stderr)
            return 2
        summary, trades, map_table = run_backtest(con, top_n=args.top, start=args.start)
    finally:
        con.close()
    leaks = leaking_trades(trades, map_table) if not trades.empty else trades
    if not leaks.empty:
        print(f"{len(leaks)} trades used a map trained on their own outcomes", file=sys.stderr)
        return 3
    oos = trades.loc[trades["is_out_of_sample"].astype(bool)] if not trades.empty else trades
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(summary))
    plot_equity(
        equity_curve(oos, basis="session"),
        args.out.parent / EQUITY_IMAGE,
        top_n=args.top,
    )
    print(f"wrote {args.out} and {args.out.parent / EQUITY_IMAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
