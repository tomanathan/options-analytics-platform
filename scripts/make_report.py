"""Write the results report (markdown and two figures) from the gold schema of the DuckDB file.

The report reads the tables that ``dbt build`` leaves in the ``gold`` schema (the calibration
backtest and the spread scores) through a read-only connection. It writes ``results.md``,
``img/calibration.png`` and ``img/spread_scores.png`` below ``--out``; with ``--readme`` it also
replaces the excerpt between ``<!-- results:start -->`` and ``<!-- results:end -->`` in that
file.

The output is deterministic. The markdown carries no timestamp and the PNG files carry no
software metadata, so a second run on the same database leaves ``git diff`` empty.

Units: prices and credits in dollars per share, probabilities and returns as decimals in the
data and as percentages in the text, time in calendar days or years.

Usage: ``make_report.py [--db .dbt-local/oap.duckdb] [--out docs] [--top 10] [--readme README.md]``.
Exit codes: 0 on success, 2 when the database, a table or the README markers are missing.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import duckdb
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from oap.analytics.config import DEFAULT_CONFIG, DTE_BUCKETS

REQUIRED_TABLES: Final[tuple[str, ...]] = (
    "fct_option_quote",
    "fct_expiration_outcome",
    "calibration_snapshot",
    "calibration_sample",
    "calibration_metrics",
    "calibration_bins",
    "calibration_map",
    "spread_scores",
)
"""Tables of the ``gold`` schema the report reads."""

README_START: Final = "<!-- results:start -->"
README_END: Final = "<!-- results:end -->"
MISSING_HINT: Final = "run `make dbt-build-local` first"

STATUS_MEANINGS: Final[dict[str, str]] = {
    "ok": "enters the calibration sample",
    "unsettled": "the expiration is after the last priced session, so there is no outcome yet",
    "too_short": f"fewer than {DEFAULT_CONFIG.min_dte_days} days to expiration",
    "too_few_puts": "fewer than 4 usable puts (a positive bid and an ask at or above the bid)",
    "no_close": "no official close of the underlying on the trade date",
    "split_in_window": "a split between the trade date and settlement (closes are unadjusted)",
    "ticker_reused": "a quote from before the symbol belonged to the current company",
}
"""One-line meaning of each snapshot status, in report order."""

# Categorical slots 1-7 of the reference palette (light surface) with one marker per slot, so
# identity never rests on colour alone. Neutral greys are the raw series and the folded group.
BLUE: Final = "#2a78d6"
GREY: Final = "#6b6a66"
LIGHT_GREY: Final = "#c9c8c2"
INK: Final = "#0b0b0b"
INK_MUTED: Final = "#52514e"
SERIES_COLOURS: Final[tuple[str, ...]] = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#6250d6",
)
SERIES_MARKERS: Final[tuple[str, ...]] = ("o", "s", "^", "D", "v", "P", "X")
IMAGE_DPI: Final = 120
Y_TICKS: Final[tuple[float, ...]] = (-10, -1, -0.1, 0, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50)

CALIBRATION_IMAGE: Final = "img/calibration.png"
SPREADS_IMAGE: Final = "img/spread_scores.png"


@dataclass(frozen=True)
class ReportData:
    """Everything the markdown and the figures are rendered from.

    Attributes:
        as_of: Latest session of ``spread_scores`` (its max ``trade_date``), or None when empty.
        coverage: One row per underlying: sessions, quotes, contracts, snapshots, predictions.
        status_counts: Snapshots per ``calibration_snapshot.status``.
        metrics: ``calibration_metrics`` as stored.
        bins: ``calibration_bins`` as stored.
        maps: One row per calibration map: id, fold, training size, knots and identity flag.
        scores: The eligible spreads of the latest session, best rank first.
        flags: Share of snapshots in the sample carrying each implied-CDF quality flag.
        snapshots_per_expiration: Mean number of chain snapshots per distinct expiration date
            in ``calibration_sample`` (the cluster of the bootstrap interval), or None when
            the sample is empty.
    """

    as_of: date | None
    coverage: pd.DataFrame
    status_counts: pd.DataFrame
    metrics: pd.DataFrame
    bins: pd.DataFrame
    maps: pd.DataFrame
    scores: pd.DataFrame
    flags: pd.DataFrame
    snapshots_per_expiration: float | None


# --- loading ---------------------------------------------------------------------------------

_COVERAGE_SQL = """
with quotes as (
    select underlying, min(trade_date) as first_session, max(trade_date) as last_session,
        count(distinct trade_date) as sessions, count(*) as quotes,
        count(distinct occ_symbol) as contracts
    from gold.fct_option_quote group by underlying
),
snapshots as (
    select underlying, count(*) as snapshots,
        count(*) filter (where settlement_date is not null) as settled_snapshots
    from gold.calibration_snapshot group by underlying
),
predictions as (
    select underlying, count(*) as predictions from gold.calibration_sample group by underlying
)
select q.underlying, q.first_session, q.last_session, q.sessions, q.quotes, q.contracts,
    coalesce(s.snapshots, 0) as snapshots, coalesce(s.settled_snapshots, 0) as settled_snapshots,
    coalesce(p.predictions, 0) as predictions
from quotes as q
left join snapshots as s on s.underlying = q.underlying
left join predictions as p on p.underlying = q.underlying
order by q.underlying
"""

_STATUS_SQL = "select status, count(*) as n from gold.calibration_snapshot group by status"

_MAPS_SQL = """
select map_id, any_value(fold) as fold, max(n_samples) as n_samples, count(*) as knots,
    bool_and(is_identity) as is_identity
from gold.calibration_map
group by map_id
order by any_value(fold) nulls last, map_id
"""

_SCORES_SQL = """
select "rank", underlying, trade_date, expiration, dte_days, short_strike, long_strike, credit,
    credit_natural, prob_profit, prob_profit_raw, expected_roc, expected_roc_raw,
    annualised_roc, annualised_roc_raw, cash_apy
from gold.spread_scores
where eligible
order by "rank"
"""

_FLAGS_SQL = """
with snapshots as (
    select distinct underlying, trade_date, expiration, cdf_flags from gold.calibration_sample
),
exploded as (
    select unnest(string_split(cdf_flags, ',')) as flag from snapshots where cdf_flags <> ''
)
select flag, count(*) as n_snapshots,
    count(*) * 1.0 / (select count(*) from snapshots) as share
from exploded
group by flag
order by flag
"""


_CLUSTER_SQL = """
select count(*) * 1.0 / count(distinct expiration)
from (select distinct underlying, trade_date, expiration from gold.calibration_sample)
"""


def load_report_data(con: duckdb.DuckDBPyConnection, *, top: int) -> ReportData:
    """Read the gold tables into the frames the report is rendered from.

    Args:
        con: An open connection to a DuckDB file that holds the ``gold`` schema.
        top: How many spreads the report table lists; it must be positive. Every eligible
            spread is loaded because the figure plots all of them.

    Returns:
        The report data. A table without rows gives an empty frame.

    Raises:
        ValueError: If ``top`` is less than 1.
    """
    if top < 1:
        raise ValueError("top must be at least 1")
    row = con.execute("select max(trade_date) from gold.spread_scores").fetchone()
    cluster = con.execute(_CLUSTER_SQL).fetchone()
    return ReportData(
        as_of=None if row is None or row[0] is None else _as_date(row[0]),
        coverage=con.execute(_COVERAGE_SQL).df(),
        status_counts=con.execute(_STATUS_SQL).df(),
        metrics=con.execute("select * from gold.calibration_metrics").df(),
        bins=con.execute("select * from gold.calibration_bins order by variant, bin_index").df(),
        maps=con.execute(_MAPS_SQL).df(),
        scores=con.execute(_SCORES_SQL).df(),
        flags=con.execute(_FLAGS_SQL).df(),
        snapshots_per_expiration=None if cluster is None else _num(cluster[0]),
    )


# --- formatting helpers ----------------------------------------------------------------------


def _missing(value: object) -> bool:
    """Say whether a scalar read from a frame is missing (None, NaN, NA or NaT)."""
    return value is None or bool(pd.isna(value))  # type: ignore[call-overload]


def _as_date(value: object) -> date:
    """Return the calendar date of a ``date``, ``datetime`` or ``Timestamp``."""
    return pd.Timestamp(str(value)).date()


def _num(value: object) -> float | None:
    """Return a scalar as a float, or None when it is missing."""
    return None if _missing(value) else float(value)  # type: ignore[arg-type]


def _fixed(value: object, digits: int = 4) -> str:
    """Format a number with fixed decimals, or ``n/a`` when it is missing."""
    number = _num(value)
    return "n/a" if number is None else f"{number:.{digits}f}"


def _signed(value: object, digits: int = 4) -> str:
    """Format a number with an explicit sign, or ``n/a`` when it is missing."""
    number = _num(value)
    return "n/a" if number is None else f"{number:+.{digits}f}"


def _percent(value: object, digits: int = 1) -> str:
    """Format a decimal as a percentage, or ``n/a`` when it is missing."""
    number = _num(value)
    return "n/a" if number is None else f"{number * 100:.{digits}f}%"


def _count(value: object) -> str:
    """Format a count with thousands separators, or ``n/a`` when it is missing."""
    number = _num(value)
    return "n/a" if number is None else f"{round(number):,}"


def _day(value: object) -> str:
    """Format a date as ISO 8601, or ``n/a`` when it is missing."""
    return "n/a" if _missing(value) else _as_date(value).isoformat()


def _table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], *, left: Sequence[int] = (0,)
) -> str:
    """Render a markdown table; the columns in ``left`` are left-aligned, the rest right-aligned."""
    rule = ["---" if i in left else "---:" for i in range(len(headers))]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(rule) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


# --- metric lookups --------------------------------------------------------------------------

_Key = tuple[str, str, str, str]
_Metrics = dict[_Key, pd.Series]


def _index_metrics(metrics: pd.DataFrame) -> _Metrics:
    """Index metric rows by (segment_type, segment, variant, metric)."""
    index: _Metrics = {}
    for _, row in metrics.iterrows():
        key = (
            str(row["segment_type"]),
            str(row["segment"]),
            str(row["variant"]),
            str(row["metric"]),
        )
        index[key] = row
    return index


def _field(index: _Metrics, key: _Key, column: str = "value") -> float | None:
    """Return one column of a metric row, or None when the row does not exist."""
    row = index.get(key)
    return None if row is None else _num(row[column])


def _segment_order(segment_type: str) -> Callable[[str], tuple[int, str]]:
    """Return the sort key of a segment type: DTE buckets short to long, others by name."""
    if segment_type == "dte_bucket":
        return lambda s: (DTE_BUCKETS.index(s) if s in DTE_BUCKETS else len(DTE_BUCKETS), s)
    return lambda s: (0, s)


def _segment_table(index: _Metrics, segment_type: str, label: str) -> str:
    """Render Brier score and ECE, raw and calibrated, for every segment of one type."""
    segments = sorted(
        {k[1] for k in index if k[0] == segment_type}, key=_segment_order(segment_type)
    )
    rows = []
    for segment in segments:
        cells = [
            segment,
            _count(_field(index, (segment_type, segment, "raw", "brier_score"), "n_predictions")),
        ]
        for metric in ("brier_score", "expected_calibration_error"):
            for variant in ("raw", "calibrated"):
                cells.append(_fixed(_field(index, (segment_type, segment, variant, metric))))
        rows.append(cells)
    headers = [label, "Predictions", "Brier raw", "Brier calibrated", "ECE raw", "ECE calibrated"]
    return _table(headers, rows)


def _overall_rows(index: _Metrics) -> list[list[str]]:
    """Return the overall metric rows: name, raw, calibrated and change."""
    rows = []
    for metric, name in (
        ("brier_score", "Brier score"),
        ("log_loss", "Log loss (nats)"),
        ("expected_calibration_error", "Expected calibration error"),
    ):
        raw = _field(index, ("overall", "all", "raw", metric))
        calibrated = _field(index, ("overall", "all", "calibrated", metric))
        change = None if raw is None or calibrated is None else calibrated - raw
        rows.append([name, _fixed(raw), _fixed(calibrated), _signed(change)])
    return rows


# --- markdown --------------------------------------------------------------------------------


def _coverage_section(data: ReportData) -> str:
    """Render the data coverage table and the totals line."""
    cov = data.coverage
    rows = [
        [
            str(r["underlying"]),
            _day(r["first_session"]),
            _day(r["last_session"]),
            _count(r["sessions"]),
            _count(r["snapshots"]),
            _count(r["settled_snapshots"]),
            _count(r["predictions"]),
        ]
        for _, r in cov.iterrows()
    ]
    table = _table(
        [
            "Underlying",
            "First session",
            "Last session",
            "Sessions",
            "Chain snapshots",
            "Settled snapshots",
            "Predictions",
        ],
        rows,
    )
    totals = (
        f"In total: {_count(cov['quotes'].sum())} quotes on "
        f"{_count(cov['contracts'].sum())} contracts, in {_count(cov['snapshots'].sum())} chain "
        "snapshots (an underlying, a trade date and an expiration)."
    )
    return "## Data coverage\n\n" + table + "\n\n" + totals


def _status_section(data: ReportData) -> str:
    """Render the snapshot status counts with their meanings."""
    counts = {str(r["status"]): int(r["n"]) for _, r in data.status_counts.iterrows()}
    total = sum(counts.values())
    names = [s for s in STATUS_MEANINGS if s in counts] + sorted(set(counts) - set(STATUS_MEANINGS))
    rows = [
        [f"`{s}`", _count(counts[s]), _percent(counts[s] / total), STATUS_MEANINGS.get(s, "")]
        for s in names
    ]
    table = _table(["Status", "Snapshots", "Share", "Meaning"], rows, left=(0, 3))
    return (
        "## Snapshot exclusions\n\n"
        "Every chain snapshot is classified; only `ok` snapshots produce predictions. "
        "Snapshot exclusions are counted here. Row-level filters (crossed quotes, inconsistent "
        "OHLC bars, staging filters) are logged by the loaders and are not counted in this "
        "report.\n\n" + table
    )


def _calibration_section(data: ReportData) -> str:
    """Render the raw versus calibrated comparison, or the empty-sample message."""
    head = "## Calibration: risk-neutral vs calibrated\n\n"
    first_test_year = DEFAULT_CONFIG.first_test_year
    if data.metrics.empty:
        return head + (
            f"No out-of-sample predictions yet (needs settled history before {first_test_year})."
        )
    index = _index_metrics(data.metrics)
    overall = index.get(("overall", "all", "delta", "brier_score"))
    base = index.get(("overall", "all", "raw", "brier_score"))
    parts = [
        head
        + "Each year's map is fitted only on predictions that had expired before 1 January of that "
        + "year and applied to that year's predictions (walk-forward, refit annually); years "
        + f"before {first_test_year} are burn-in and the metrics use out-of-sample rows only.",
        _table(["Metric", "Risk-neutral", "Calibrated", "Change"], _overall_rows(index)),
    ]
    if overall is not None and base is not None:
        parts.append(
            f"Brier change {_signed(overall['value'])} (95% cluster-bootstrap interval "
            f"{_signed(overall['ci_low'])} to {_signed(overall['ci_high'])}, resampling "
            "expiration dates; negative means calibration helped) over "
            f"{_count(base['n_predictions'])} predictions, {_count(base['n_snapshots'])} snapshots "
            f"and {_count(base['n_clusters'])} expiration clusters. "
            "Predictions that resolve on the same date share one market move, so the effective "
            "sample is closer to the number of clusters than to the number of predictions."
        )
    parts.append(
        "### By days to expiration\n\n" + _segment_table(index, "dte_bucket", "DTE bucket")
    )
    parts.append("### By underlying\n\n" + _segment_table(index, "underlying", "Underlying"))
    parts.append("### By fold year\n\n" + _segment_table(index, "fold", "Fold"))
    return "\n\n".join(parts)


def _bin_label(lower: object, upper: object) -> str:
    """Format a probability bin as ``0.0-0.1``."""
    return f"{_fixed(lower, 1)}-{_fixed(upper, 1)}"


def _reliability_section(data: ReportData) -> str:
    """Render the reliability figure link and the bins table."""
    head = f"## Reliability\n\n![Reliability diagram]({CALIBRATION_IMAGE})\n\n"
    bins = data.bins
    if bins.empty:
        return head + "The reliability table is empty until there are out-of-sample predictions."
    raw = bins[bins["variant"] == "raw"].set_index("bin_index")
    cal = bins[bins["variant"] == "calibrated"].set_index("bin_index")
    rows = []
    for i in sorted(raw.index):
        r = raw.loc[i]
        c = cal.loc[i] if i in cal.index else None
        rows.append(
            [
                _bin_label(r["lower"], r["upper"]),
                _count(r["n"]),
                _fixed(r["mean_predicted"]),
                _fixed(r["frequency_realised"]),
                _count(None if c is None else c["n"]),
                _fixed(None if c is None else c["mean_predicted"]),
                _fixed(None if c is None else c["frequency_realised"]),
            ]
        )
    table = _table(
        [
            "Bin",
            "n raw",
            "Predicted raw",
            "Realised raw",
            "n calibrated",
            "Predicted calibrated",
            "Realised calibrated",
        ],
        rows,
    )
    return head + table


def _spread_rows(scores: pd.DataFrame) -> list[list[str]]:
    """Return table rows for the spreads in ``scores``, in the order given."""
    return [
        [
            _count(r["rank"]),
            str(r["underlying"]),
            _day(r["trade_date"]),
            _day(r["expiration"]),
            _count(r["dte_days"]),
            f"{_num(r['short_strike']):g}/{_num(r['long_strike']):g}",
            _fixed(r["credit"], 2),
            _fixed(r["credit_natural"], 2),
            _percent(r["prob_profit"]),
            _percent(r["prob_profit_raw"]),
            _percent(r["expected_roc"], 2),
            _percent(r["annualised_roc"]),
        ]
        for _, r in scores.iterrows()
    ]


SPREAD_HEADERS: Final[tuple[str, ...]] = (
    "Rank",
    "Underlying",
    "Session",
    "Expiration",
    "DTE",
    "Short/long",
    "Mid credit",
    "Natural credit",
    "POP calibrated",
    "POP risk-neutral",
    "Expected ROC",
    "Annualised ROC",
)


def _spreads_section(data: ReportData, top: int) -> str:
    """Render the top spreads table and the figure link."""
    as_of = "no session" if data.as_of is None else data.as_of.isoformat()
    head = f"## Top put credit spreads ({as_of})\n\n"
    if data.scores.empty:
        body = "No spread is eligible on the latest session.\n\n"
    else:
        body = _table(SPREAD_HEADERS, _spread_rows(data.scores.head(top))) + "\n\n"
        body += (
            "Credits are dollars per share. POP is the probability the underlying settles above "
            "the breakeven; ROC is the return on the collateral (maximum loss) over the trade, "
            "annualised in the last column.\n\n"
        )
    return head + body + f"![Eligible spreads]({SPREADS_IMAGE})"


def _reading_section(data: ReportData) -> str:
    """Render the interpretation paragraph with the numbers pulled from the database."""
    text = (
        "## How to read this\n\n"
        "Under the risk-neutral CDF built from the same mid quotes, a spread's expected return on "
        "collateral is roughly the cash rate by construction, so any edge comes from the "
        "calibration map, which is an estimate of the variance risk premium: the gap between the "
        "probabilities the option market implies and the frequencies that followed."
    )
    scores = data.scores
    if not scores.empty:
        text += (
            f" Across the {_count(len(scores))} eligible spreads of the latest session the median "
            f"annualised return is {_percent(scores['annualised_roc_raw'].median())} under the "
            f"risk-neutral CDF and {_percent(scores['annualised_roc'].median())} after "
            f"calibration, against a cash rate of {_percent(scores['cash_apy'].iloc[0])}."
        )
    return text


def _caveats_section(data: ReportData) -> str:
    """Render the caveats, with counts from the database."""
    counts = {str(r["status"]): int(r["n"]) for _, r in data.status_counts.iterrows()}
    flags = {str(r["flag"]): _num(r["share"]) for _, r in data.flags.iterrows()}
    tail = ", ".join(
        f"{name.lower().replace('_', ' ')} {_percent(flags[name])}"
        for name in sorted(flags)
        if "TAIL" in name.upper()
    )
    per_expiration = data.snapshots_per_expiration
    sharing = (
        ""
        if per_expiration is None
        else f"on average {per_expiration:.1f} snapshots share an expiration, "
    )
    bullets = [
        "**Correlated samples.** Each snapshot contributes up to 13 nested targets, "
        f"{sharing}and the market moves together on an expiration date. The "
        "interval above resamples expiration dates for that reason.",
        "**Sparse chains and zero bids.** Only quotes with a positive bid and an ask at or above "
        f"the bid are used; {_count(counts.get('too_few_puts', 0))} snapshots with fewer than 4 "
        "usable puts are excluded and counted above.",
        "**Tail extrapolation.** Targets outside the strikes of a CDF are never predicted, and a "
        "spread whose long strike lies below the lowest knot is ineligible. Share of snapshots "
        f"with a flagged tail: {tail or 'none'}.",
        "**Splits and unadjusted closes.** Closes are as traded. "
        f"{_count(counts.get('split_in_window', 0))} snapshots whose window contains a daily move "
        f"beyond {DEFAULT_CONFIG.split_abs_log_return:g} in log terms are excluded.",
        f"**Ticker reuse.** {_count(counts.get('ticker_reused', 0))} snapshots predate the current "
        "company behind a reused symbol.",
        "**Hindsight in the universe.** The watchlist is today's large caps, which biases the "
        "realised downside frequency low and makes the calibrated map optimistic. This is the most "
        "important caveat here.",
        "**Prices.** Mids are indicative end-of-day values, so credits are mid credits; the "
        "natural credit is shown and must be positive. Quote and close times can differ. "
        "American-style puts carry an early-exercise premium that slightly overstates P(S < K) "
        "deep in the money, and the risk-free rate is the constant "
        f"{_percent(DEFAULT_CONFIG.risk_free_apy)}.",
        "**Coverage gaps.** The vendor history misses some sessions, which affects sampling, not "
        "labels. One pooled map serves every underlying and expiry; the segment tables show the "
        "differences.",
        "**Derived data only.** This report holds derived statistics and a few derived spread "
        "rows, never raw vendor quotes.",
    ]
    return "## Caveats\n\n" + "\n".join(f"- {b}" for b in bullets)


def render_markdown(data: ReportData, *, top: int) -> str:
    """Render the report. The text is a pure function of ``data`` and ``top``.

    Args:
        data: The frames read from the database.
        top: How many spreads to list in the top-spreads table.

    Returns:
        The markdown, ending in a newline.
    """
    as_of = (
        "no spread scores yet" if data.as_of is None else f"the {data.as_of.isoformat()} session"
    )
    head = (
        "# Results\n\n"
        "Source: the `gold` schema of the DuckDB file built by dbt; spreads are scored as of "
        f"{as_of}."
    )
    sections = [
        head,
        _coverage_section(data),
        _status_section(data),
        _calibration_section(data),
        _reliability_section(data),
        _spreads_section(data, top),
        _reading_section(data),
        _caveats_section(data),
    ]
    return "\n\n".join(sections) + "\n"


def readme_excerpt(data: ReportData) -> str:
    """Render the short excerpt for the README: three overall metrics and the top three spreads.

    Args:
        data: The frames read from the database.

    Returns:
        Two markdown tables, six body rows in all.
    """
    metric_rows = _overall_rows(_index_metrics(data.metrics))
    metrics = _table(["Out-of-sample metric", "Risk-neutral", "Calibrated", "Change"], metric_rows)
    spreads = _table(SPREAD_HEADERS, _spread_rows(data.scores.head(3)))
    return metrics + "\n\n" + spreads


def replace_readme_excerpt(readme: str, excerpt: str) -> str:
    """Replace the text between the results markers of a README.

    Args:
        readme: The README text.
        excerpt: The markdown to put between the start and end markers.

    Returns:
        The README with the excerpt in place; the markers stay, so the call is repeatable.

    Raises:
        ValueError: If either marker is missing or the end marker precedes the start marker.
    """
    start = readme.find(README_START)
    end = readme.find(README_END)
    if start < 0 or end < 0 or end < start:
        raise ValueError(f"README needs {README_START} followed by {README_END}")
    return readme[: start + len(README_START)] + "\n" + excerpt.strip("\n") + "\n" + readme[end:]


# --- figures ---------------------------------------------------------------------------------


def _save(fig: Figure, path: Path) -> None:
    """Write a figure as a PNG with no software metadata, creating the directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    FigureCanvasAgg(fig)
    fig.savefig(path, dpi=IMAGE_DPI, metadata={"Software": None}, facecolor="white")


def _placeholder(message: str, path: Path, *, size: tuple[float, float]) -> None:
    """Write a figure that only says why it is empty."""
    fig = Figure(figsize=size, facecolor="white")
    ax = fig.subplots()
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=INK_MUTED, fontsize=11)
    _save(fig, path)


def _style(ax: Axes) -> None:
    """Apply the shared recessive grid and spines."""
    ax.grid(True, color="#e6e5e0", linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9c8c2")
    ax.tick_params(colors=INK_MUTED, labelsize=9)


def plot_calibration(bins: pd.DataFrame, path: Path) -> None:
    """Write the reliability diagram: realised frequency by predicted probability, and counts.

    The top panel plots the realised frequency of each probability bin against its mean
    predicted probability for the raw (grey) and calibrated (blue) forecasts, marker area
    proportional to the bin count, with the diagonal of perfect calibration. The bottom panel
    shows how many predictions fall in each bin.

    Args:
        bins: ``calibration_bins`` (variant, bin_index, lower, upper, n, mean_predicted,
            frequency_realised). An empty frame gives a placeholder figure.
        path: Where to write the PNG.
    """
    if bins.empty:
        _placeholder("No out-of-sample predictions yet", path, size=(6.4, 6.4))
        return
    fig = Figure(figsize=(6.4, 7.2), facecolor="white", layout="constrained")
    top, bottom = fig.subplots(2, 1, height_ratios=(3, 1.4))
    top.plot([0, 1], [0, 1], color=LIGHT_GREY, linewidth=1.2, linestyle="--", label="Perfect")
    series = (("raw", "Risk-neutral", GREY, "o"), ("calibrated", "Calibrated", BLUE, "s"))
    half = 0.022  # half the gap between the two bars of a bin, in probability
    for k, (variant, label, colour, marker) in enumerate(series):
        part = bins[(bins["variant"] == variant) & (bins["n"] > 0)].sort_values("bin_index")
        sizes = 18 + 160 * part["n"] / max(float(bins["n"].max()), 1.0)
        top.plot(
            part["mean_predicted"],
            part["frequency_realised"],
            color=colour,
            linewidth=1.5,
            alpha=0.9,
        )
        top.scatter(
            part["mean_predicted"],
            part["frequency_realised"],
            s=sizes,
            color=colour,
            marker=marker,
            edgecolor="white",
            linewidth=1.0,
            label=label,
            zorder=3,
        )
        every = bins[bins["variant"] == variant].sort_values("bin_index")
        centre = (every["lower"] + every["upper"]) / 2 + (k - 0.5) * 2 * half
        bottom.bar(centre, every["n"], width=1.8 * half, color=colour, label=label)
    top.set_xlim(0, 1)
    top.set_ylim(0, 1)
    top.set_xlabel("Mean predicted probability P(S < K)", color=INK_MUTED, fontsize=9)
    top.set_ylabel("Realised frequency", color=INK_MUTED, fontsize=9)
    top.set_title(
        "Reliability of out-of-sample probabilities (marker area is bin count)",
        loc="left",
        fontsize=10,
        color=INK,
    )
    top.legend(frameon=False, fontsize=9, loc="upper left")
    bottom.set_xlim(0, 1)
    bottom.set_xlabel("Probability bin", color=INK_MUTED, fontsize=9)
    bottom.set_ylabel("Predictions", color=INK_MUTED, fontsize=9)
    bottom.legend(frameon=False, fontsize=9, loc="upper left")
    _style(top)
    _style(bottom)
    _save(fig, path)


def plot_spread_scores(scores: pd.DataFrame, path: Path, *, top: int = 10) -> None:
    """Write the eligible spreads of the latest session: calibrated POP against annualised ROC.

    The y axis is symmetric-log so that the few large returns do not flatten the rest. Colour
    and marker shape identify the underlying (the seven with the most eligible spreads; the rest
    are one grey group); the best ``top`` spreads are ringed in black.

    Args:
        scores: Eligible spreads, best rank first, with ``prob_profit``, ``annualised_roc``,
            ``underlying`` and ``rank``. An empty frame gives a placeholder figure.
        path: Where to write the PNG.
        top: How many of the best-ranked spreads to ring.
    """
    if scores.empty:
        _placeholder("No eligible spread on the latest session", path, size=(7.5, 5.0))
        return
    fig = Figure(figsize=(7.5, 5.0), facecolor="white", layout="constrained")
    ax = fig.subplots()
    sizes = scores["underlying"].value_counts()
    ranked = sorted(sizes.index, key=lambda u: (-int(sizes[u]), str(u)))
    named = ranked[: len(SERIES_COLOURS)]
    groups = [
        (u, SERIES_COLOURS[i], SERIES_MARKERS[i], scores["underlying"] == u)
        for i, u in enumerate(named)
    ]
    if len(ranked) > len(named):
        groups.append(("Other", LIGHT_GREY, "o", ~scores["underlying"].isin(named)))
    for label, colour, marker, mask in groups:
        part = scores[mask]
        ax.scatter(
            part["prob_profit"],
            part["annualised_roc"],
            s=34,
            color=colour,
            marker=marker,
            edgecolor="white",
            linewidth=0.6,
            label=f"{label} ({len(part)})",
            zorder=3,
        )
    best = scores.nsmallest(top, "rank")
    ax.scatter(
        best["prob_profit"],
        best["annualised_roc"],
        s=110,
        facecolor="none",
        edgecolor=INK,
        linewidth=1.3,
        label=f"Top {len(best)} by rank",
        zorder=4,
    )
    ax.axhline(0, color=GREY, linewidth=0.8)
    ax.set_yscale("symlog", linthresh=0.1)
    low, high = ax.get_ylim()
    ticks = [t for t in Y_TICKS if low <= t <= high]
    ax.set_yticks(ticks, labels=[f"{t:.0%}" for t in ticks])
    ax.set_xlabel("Probability of profit (calibrated)", color=INK_MUTED, fontsize=9)
    ax.set_ylabel("Annualised return on collateral (symlog axis)", color=INK_MUTED, fontsize=9)
    ax.set_title("Eligible put credit spreads, latest session", loc="left", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8, loc="best", ncols=2)
    _style(ax)
    _save(fig, path)


# --- command line ----------------------------------------------------------------------------


def _missing_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Return the names of the required tables that the ``gold`` schema lacks."""
    found = {
        str(r[0])
        for r in con.execute(
            "select table_name from information_schema.tables where table_schema = 'gold'"
        ).fetchall()
    }
    return [t for t in REQUIRED_TABLES if t not in found]


def main(argv: Sequence[str] | None = None) -> int:
    """Write the report for a DuckDB file.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        0 on success; 2 when the database file, a required table or the README markers are
        missing (the message says what), or the file is locked by a writer.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=Path(".dbt-local/oap.duckdb"))
    parser.add_argument("--out", type=Path, default=Path("docs"))
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--readme", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"{args.db} does not exist: {MISSING_HINT}", file=sys.stderr)
        return 2
    try:
        con = duckdb.connect(str(args.db), read_only=True)
    except duckdb.IOException as exc:
        print(f"cannot open {args.db} (is a build writing it?): {exc}", file=sys.stderr)
        return 2
    try:
        missing = _missing_tables(con)
        if missing:
            print(f"gold tables missing: {', '.join(missing)}: {MISSING_HINT}", file=sys.stderr)
            return 2
        data = load_report_data(con, top=args.top)
    finally:
        con.close()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.md").write_text(render_markdown(data, top=args.top))
    plot_calibration(data.bins, args.out / CALIBRATION_IMAGE)
    plot_spread_scores(data.scores, args.out / SPREADS_IMAGE, top=args.top)
    print(f"wrote {args.out / 'results.md'} and {args.out / 'img'}")
    if args.readme is not None:
        try:
            updated = replace_readme_excerpt(args.readme.read_text(), readme_excerpt(data))
        except (OSError, ValueError) as exc:
            print(f"README excerpt not written: {exc}", file=sys.stderr)
            return 2
        args.readme.write_text(updated)
        print(f"updated the results excerpt in {args.readme}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
