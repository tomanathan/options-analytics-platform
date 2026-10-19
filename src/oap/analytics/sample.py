"""Build the labelled prediction sample for the calibration backtest.

A snapshot is one underlying's option chain for one expiration on one trade date. For
each usable snapshot the risk-neutral CDF is built from the chain, evaluated at a grid of
strikes expressed as fractions of the underlying close, and paired with what happened:
whether the settlement close ended below each strike.

Units: strikes, prices and closes are in dollars per share; ``dte_years`` is in years
(calendar days / 365); probabilities are decimals in [0, 1]; moneyness is a strike divided
by the underlying close, a dimensionless ratio.

Frames carry date columns as ``datetime64``, which is what DuckDB's ``.df()`` returns.
The functions are pure: they read no files and keep no state. Engine errors are not
caught, so a failure here fails the dbt model that called it.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np
import pandas as pd

from oap.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, dte_bucket
from oap.engine._types import FloatArray
from oap.engine.conventions import dte_years
from oap.engine.implied_distribution import (
    MIN_PUT_STRIKES,
    RiskNeutralCdf,
    implied_cdf,
    usable_quotes,
)

SNAPSHOT_KEY: Final[tuple[str, ...]] = ("underlying", "trade_date", "expiration")

SNAPSHOT_COLUMNS: Final[tuple[str, ...]] = (
    *SNAPSHOT_KEY,
    "dte_days",
    "underlying_close",
    "n_usable_puts",
    "n_usable_calls",
    "settlement_date",
    "settlement_close",
    "status",
)

PREDICTION_COLUMNS: Final[tuple[str, ...]] = (
    *SNAPSHOT_KEY,
    "settlement_date",
    "dte_days",
    "dte_years",
    "dte_bucket",
    "fold",
    "moneyness",
    "target_strike",
    "underlying_close",
    "settlement_close",
    "predicted_raw",
    "realised",
    "n_knots",
    "forward",
    "cdf_flags",
)

MIN_CALL_STRIKES: Final = 2
STRIKE_DECIMALS: Final = 6
QUOTE_COLUMNS: Final[tuple[str, ...]] = (
    *SNAPSHOT_KEY,
    "strike",
    "option_right",
    "bid",
    "ask",
    "underlying_close",
    "dte_days",
)
OUTCOME_COLUMNS: Final[tuple[str, ...]] = (
    "underlying",
    "expiration",
    "settlement_date",
    "settlement_close",
)


class SnapshotStatus(StrEnum):
    """Why a chain snapshot is, or is not, usable for the backtest."""

    OK = "ok"
    TICKER_REUSED = "ticker_reused"
    TOO_SHORT = "too_short"
    NO_CLOSE = "no_close"
    TOO_FEW_PUTS = "too_few_puts"
    UNSETTLED = "unsettled"
    SPLIT_IN_WINDOW = "split_in_window"


def empty_frame(columns: tuple[str, ...]) -> pd.DataFrame:
    """Return a frame with the given columns and no rows.

    Args:
        columns: Column names, in order.

    Returns:
        An empty frame with object columns; ``oap.analytics.io.to_output`` casts them.
    """
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def require_columns(frame: pd.DataFrame, columns: tuple[str, ...], name: str) -> None:
    """Require that a frame has the given columns.

    Args:
        frame: Frame to check.
        columns: Column names that must be present.
        name: Frame name used in the error message.

    Raises:
        ValueError: If a column is missing.
    """
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{name} is missing columns: {missing}")


def usable_mask(bid: pd.Series, ask: pd.Series) -> pd.Series:
    """Flag quotes the engine would keep.

    This is the rule of ``oap.engine.implied_distribution.usable_quotes`` without the
    strike: bid and ask finite, ``bid > 0`` (a zero bid makes the mid overstate value)
    and ``ask >= bid`` (not crossed).

    Args:
        bid: Bid prices in dollars per share.
        ask: Ask prices in dollars per share, aligned with ``bid``.

    Returns:
        Boolean series aligned with ``bid``; True for usable quotes.
    """
    b = pd.to_numeric(bid, errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
    a = pd.to_numeric(ask, errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
    mask = np.isfinite(b) & np.isfinite(a) & (b > 0) & (a >= b)
    return pd.Series(mask, index=bid.index)


def split_events(daily: pd.DataFrame, *, threshold: float) -> pd.DataFrame:
    """Find sessions whose close-to-close move looks like an unadjusted stock split.

    Closes in the source are not split adjusted, so a 4-for-1 split shows as a log return
    near -1.39. The same rule catches every listed split from 3-for-1 to 20-for-1.

    Args:
        daily: Frame with ``underlying``, ``trade_date`` and ``log_return`` (a
            dimensionless decimal; null rows are ignored).
        threshold: Absolute log return above which a session is flagged.

    Returns:
        Frame with columns ``underlying`` and ``trade_date`` of the flagged sessions.

    Raises:
        ValueError: If ``daily`` lacks a required column.
    """
    require_columns(daily, ("underlying", "trade_date", "log_return"), "daily")
    moves = pd.to_numeric(daily["log_return"], errors="coerce")
    flagged = daily.loc[moves.abs() > threshold, ["underlying", "trade_date"]]
    return flagged.drop_duplicates().reset_index(drop=True)


def _summarise_snapshots(quotes: pd.DataFrame) -> pd.DataFrame:
    """Reduce quote rows to one row per snapshot.

    Args:
        quotes: Quote rows with the columns in ``QUOTE_COLUMNS``.

    Returns:
        One row per snapshot key with ``dte_days``, ``underlying_close`` (dollars, the
        first non-null value) and the counts of usable puts and calls.
    """
    work = quotes[list(QUOTE_COLUMNS)].copy()
    usable = usable_mask(work["bid"], work["ask"])
    work["usable_put"] = usable & (work["option_right"] == "P")
    work["usable_call"] = usable & (work["option_right"] == "C")
    summary = (
        work.groupby(list(SNAPSHOT_KEY), sort=True)
        .agg(
            dte_days=("dte_days", "first"),
            underlying_close=("underlying_close", "first"),
            n_usable_puts=("usable_put", "sum"),
            n_usable_calls=("usable_call", "sum"),
        )
        .reset_index()
    )
    return summary.astype(
        {
            "dte_days": "int64",
            "underlying_close": "float64",
            "n_usable_puts": "int64",
            "n_usable_calls": "int64",
        }
    )


def _split_in_window(snapshots: pd.DataFrame, events: pd.DataFrame) -> pd.Series:
    """Flag snapshots with a split event in ``(trade_date, settlement_date]``.

    The ex-date of a split on the trade date itself is not in the window: OCC adjusts
    strikes at the open, so a chain snapshotted on the ex-date is consistent.

    Args:
        snapshots: Snapshot rows with ``underlying``, ``trade_date`` and
            ``settlement_date`` (null when unsettled), on a default RangeIndex.
        events: Output of ``split_events``.

    Returns:
        Boolean series aligned with ``snapshots``.
    """
    flags = np.zeros(len(snapshots), dtype=np.bool_)
    if not events.empty and not snapshots.empty:
        pairs = snapshots[["underlying", "trade_date", "settlement_date"]].reset_index(names="row")
        joined = pairs.merge(
            events.rename(columns={"trade_date": "event_date"}), on="underlying", how="inner"
        )
        inside = (joined["event_date"] > joined["trade_date"]) & (
            joined["event_date"] <= joined["settlement_date"]
        )
        flags[joined.loc[inside, "row"].to_numpy(dtype=np.int64)] = True
    return pd.Series(flags, index=snapshots.index)


def classify_snapshots(
    quotes: pd.DataFrame,
    outcomes: pd.DataFrame,
    daily: pd.DataFrame,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """Classify every chain snapshot as usable or excluded, and say why.

    The first failing rule wins, in this order: ``ticker_reused`` (trade date before the
    symbol's ``ticker_valid_from``), ``too_short`` (fewer than ``min_dte_days`` calendar
    days), ``no_close`` (null underlying close), ``too_few_puts`` (fewer than four usable
    puts), ``unsettled`` (no expiration outcome), ``split_in_window`` (a split event in
    ``(trade_date, settlement_date]``).

    Args:
        quotes: Quote rows with ``underlying``, ``trade_date``, ``expiration``,
            ``strike`` (dollars), ``option_right`` ("P" or "C"), ``bid`` and ``ask``
            (dollars per share), ``underlying_close`` (dollars) and ``dte_days``.
        outcomes: One row per ``(underlying, expiration)`` with ``settlement_date`` and
            ``settlement_close`` (dollars).
        daily: Daily rows with ``underlying``, ``trade_date`` and ``log_return``.
        config: Analytics parameters.

    Returns:
        One row per snapshot with ``SNAPSHOT_COLUMNS``, sorted by the snapshot key.
        ``settlement_date`` and ``settlement_close`` are null when unsettled.

    Raises:
        ValueError: If an input frame lacks a required column.
    """
    require_columns(quotes, QUOTE_COLUMNS, "quotes")
    require_columns(outcomes, OUTCOME_COLUMNS, "outcomes")
    if quotes.empty:
        return empty_frame(SNAPSHOT_COLUMNS)
    settled = outcomes[list(OUTCOME_COLUMNS)].drop_duplicates(["underlying", "expiration"])
    snaps = _summarise_snapshots(quotes).merge(settled, on=["underlying", "expiration"], how="left")
    snaps["settlement_close"] = snaps["settlement_close"].astype("float64")

    reused = np.zeros(len(snaps), dtype=np.bool_)
    for symbol, valid_from in config.ticker_valid_from:
        before = snaps["trade_date"] < pd.Timestamp(valid_from)
        reused |= ((snaps["underlying"] == symbol) & before).to_numpy(dtype=np.bool_)
    events = split_events(daily, threshold=config.split_abs_log_return)
    split = _split_in_window(snaps, events).to_numpy(dtype=np.bool_)

    snaps["status"] = np.select(
        [
            reused,
            (snaps["dte_days"] < config.min_dte_days).to_numpy(dtype=np.bool_),
            snaps["underlying_close"].isna().to_numpy(dtype=np.bool_),
            (snaps["n_usable_puts"] < MIN_PUT_STRIKES).to_numpy(dtype=np.bool_),
            snaps["settlement_date"].isna().to_numpy(dtype=np.bool_),
            split,
        ],
        [
            SnapshotStatus.TICKER_REUSED.value,
            SnapshotStatus.TOO_SHORT.value,
            SnapshotStatus.NO_CLOSE.value,
            SnapshotStatus.TOO_FEW_PUTS.value,
            SnapshotStatus.UNSETTLED.value,
            SnapshotStatus.SPLIT_IN_WINDOW.value,
        ],
        default=SnapshotStatus.OK.value,
    )
    return snaps[list(SNAPSHOT_COLUMNS)].reset_index(drop=True)


def chain_cdf(chain: pd.DataFrame, *, years: float, rate: float) -> RiskNeutralCdf | None:
    """Build the risk-neutral CDF of one snapshot's chain.

    Both the backtest and live scoring call this function, so the distribution a map is
    trained on is the distribution it is applied to. Unusable quotes are dropped per side
    with the engine's ``usable_quotes``; calls are passed only when at least two are
    usable, which lets the engine infer the forward from put-call parity.

    Args:
        chain: Rows of one snapshot, both rights, with ``strike`` (dollars),
            ``option_right`` ("P" or "C"), ``bid`` and ``ask`` (dollars per share).
        years: Time to expiration in years (calendar days / 365); must be positive.
        rate: Risk-free rate as a decimal APY.

    Returns:
        The CDF, or None when fewer than four usable puts remain.

    Raises:
        EngineInputError: If the engine rejects the quotes (for example duplicate
            strikes) or ``years`` or ``rate`` are out of range.
    """
    puts = chain.loc[chain["option_right"] == "P"]
    calls = chain.loc[chain["option_right"] == "C"]
    put_strikes, put_mids = usable_quotes(puts["strike"], puts["bid"], puts["ask"])
    if put_strikes.shape[0] < MIN_PUT_STRIKES:
        return None
    call_strikes, call_mids = usable_quotes(calls["strike"], calls["bid"], calls["ask"])
    if call_strikes.shape[0] >= MIN_CALL_STRIKES:
        return implied_cdf(
            put_strikes,
            put_mids,
            years=years,
            rate=rate,
            call_strikes=call_strikes,
            call_mids=call_mids,
        )
    return implied_cdf(put_strikes, put_mids, years=years, rate=rate)


def build_predictions(
    quotes: pd.DataFrame,
    snapshots: pd.DataFrame,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """Predict the probability of finishing below each grid strike, with the outcome.

    Only snapshots whose status is ``ok`` are used. For each, the CDF comes from
    ``chain_cdf`` at ``config.risk_free_apy``; targets are ``moneyness * underlying_close``
    rounded to 1e-6 dollars (so a decimal product such as 0.975 * 100 is exactly 97.5),
    kept only inside the CDF's outer knots, so nothing is extrapolated. ``realised`` is
    ``settlement_close < target`` (strict).

    Args:
        quotes: Quote rows as in ``classify_snapshots``.
        snapshots: Output of ``classify_snapshots`` for the same quotes.
        config: Analytics parameters.

    Returns:
        One row per snapshot and in-range target with ``PREDICTION_COLUMNS``, in snapshot
        order then ascending moneyness. ``fold`` is the calendar year of the trade date,
        ``predicted_raw`` the risk-neutral probability as a decimal, ``dte_years`` the
        time in years, ``forward`` in dollars (nan when unknown) and ``cdf_flags`` the
        sorted, comma-joined engine quality flags.

    Raises:
        ValueError: If an input frame lacks a required column.
        EngineInputError: If the engine rejects a chain. Not caught: a bad chain must
            fail the model rather than silently drop a snapshot.
    """
    require_columns(quotes, QUOTE_COLUMNS, "quotes")
    require_columns(snapshots, SNAPSHOT_COLUMNS, "snapshots")
    ok = snapshots.loc[snapshots["status"] == SnapshotStatus.OK.value].reset_index(drop=True)
    if ok.empty or quotes.empty:
        return empty_frame(PREDICTION_COLUMNS)
    key = list(SNAPSHOT_KEY)
    selected = quotes.merge(ok[key], on=key, how="inner")
    chains = {name: group for name, group in selected.groupby(key, sort=False)}
    grid = np.asarray(config.moneyness_grid, dtype=np.float64)
    evaluated: list[_Evaluated] = []
    underlyings = ok["underlying"].tolist()
    trade_dates = pd.DatetimeIndex(ok["trade_date"])
    expirations = pd.DatetimeIndex(ok["expiration"])
    closes = ok["underlying_close"].to_numpy(dtype=np.float64)
    for i in range(len(ok)):
        chain = chains.get((underlyings[i], trade_dates[i], expirations[i]))
        if chain is None:
            continue
        years = dte_years(trade_dates[i].date(), expirations[i].date())
        cdf = chain_cdf(chain, years=years, rate=config.risk_free_apy)
        if cdf is None:
            continue
        targets = np.round(grid * closes[i], STRIKE_DECIMALS)
        inside = (targets >= cdf.strikes[0]) & (targets <= cdf.strikes[-1])
        if not inside.any():
            continue
        evaluated.append(
            _Evaluated(
                row=i,
                years=years,
                forward=cdf.forward,
                n_knots=int(cdf.strikes.shape[0]),
                flags=",".join(sorted(f.value for f in cdf.flags)),
                moneyness=grid[inside],
                targets=targets[inside],
                predicted=cdf.prob_below_array(targets[inside]),
            )
        )
    return _assemble(ok, evaluated)


@dataclass(frozen=True)
class _Evaluated:
    """The CDF evaluated at the in-range targets of one snapshot.

    Attributes:
        row: Position of the snapshot among the ``ok`` snapshots.
        years: Time to expiration in years.
        forward: Forward price in dollars; nan when unknown.
        n_knots: Number of CDF knots.
        flags: Sorted, comma-joined quality flags.
        moneyness: Target strikes as fractions of the close.
        targets: Target strikes in dollars.
        predicted: Risk-neutral probability of finishing below each target, as decimals.
    """

    row: int
    years: float
    forward: float
    n_knots: int
    flags: str
    moneyness: FloatArray
    targets: FloatArray
    predicted: FloatArray


def _assemble(ok: pd.DataFrame, evaluated: list[_Evaluated]) -> pd.DataFrame:
    """Expand per-snapshot results into the prediction frame.

    Args:
        ok: Snapshots with status ``ok``, on a default RangeIndex.
        evaluated: One entry per snapshot that has at least one in-range target.

    Returns:
        The frame with ``PREDICTION_COLUMNS``; empty if ``evaluated`` is empty.
    """
    if not evaluated:
        return empty_frame(PREDICTION_COLUMNS)
    counts = np.array([e.targets.shape[0] for e in evaluated], dtype=np.int64)
    base = ok.iloc[np.repeat([e.row for e in evaluated], counts)].reset_index(drop=True)
    targets = np.concatenate([e.targets for e in evaluated])
    settlement = base["settlement_close"].to_numpy(dtype=np.float64)
    return pd.DataFrame(
        {
            "underlying": base["underlying"],
            "trade_date": base["trade_date"],
            "expiration": base["expiration"],
            "settlement_date": base["settlement_date"],
            "dte_days": base["dte_days"],
            "dte_years": np.repeat([e.years for e in evaluated], counts),
            "dte_bucket": base["dte_days"].map(dte_bucket).astype(object),
            "fold": base["trade_date"].dt.year.astype("int64"),
            "moneyness": np.concatenate([e.moneyness for e in evaluated]),
            "target_strike": targets,
            "underlying_close": base["underlying_close"],
            "settlement_close": base["settlement_close"],
            "predicted_raw": np.concatenate([e.predicted for e in evaluated]),
            "realised": settlement < targets,
            "n_knots": np.repeat([e.n_knots for e in evaluated], counts),
            "forward": np.repeat([e.forward for e in evaluated], counts),
            "cdf_flags": np.repeat([e.flags for e in evaluated], counts).astype(object),
        }
    )[list(PREDICTION_COLUMNS)]
