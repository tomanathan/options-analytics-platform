"""Strategy backtest of the entry ranking: the live "Top to enter" rule applied historically.

Every historical session is ranked by ``oap.analytics.scoring.score_session``, the function
that ranks the latest session, with only the calibration map that existed at the time: a
session in year Y uses ``fold_<Y>``, fitted on expirations before 1 January of Y (ADR 0010),
never the production map. Each selected spread is held to expiry and settled at the actual
settlement close, and the realised results are compared with what the scores predicted.

Three strategies are selected from the same scores:

* ``entry_top<N>``: the ``N`` best by ``rank_entry``, the live entry ranking (``ENTRY_RULE``);
* ``return_top<N>``: the ``N`` best by ``rank``, raw annualised return without the entry
  guards, which shows what the guards add;
* ``eligible_all``: every eligible spread, equal weight; the no-selection baseline. It is not
  a tradeable portfolio.

Settlement. The trade fills at the natural credit ``c_n`` (short bid minus long ask), so the
seller's payoff at expiry is ``c_n - clip(K - S_T, 0, W)`` per share and the trade's maximum
loss is ``W - c_n``. The realised return is the payoff over that maximum loss (return on max
loss over the holding period), which lies in ``[-1, c_n / (W - c_n)]``. There are no
commissions, no slippage beyond the natural price, no early management or assignment, and no
interest on the collateral. The predicted figures are the scores' own: ``prob_profit`` (at the
mid-credit breakeven) and ``expected_roc`` (mid credit, interest included), so part of any gap
is the half-spread and the interest, not the calibration.

Out of sample. A session's trades are out of sample when its year is at least
``first_test_year`` and its fold map is not the identity, the rule of
``oap.analytics.backtest.apply_fold_maps``. Earlier sessions (2020 burn-in) stay in the trades
and are excluded from every metric.

Units: prices, strikes, credits and payoffs are dollars per share; returns are decimals over
the holding period (0.02 is 2%); probabilities are decimals in [0, 1]; ``dte_days`` is calendar
days. Equity curves and drawdowns are in units of one dollar of maximum loss.
"""

import math
from collections.abc import Iterator, Mapping
from typing import Final, Literal

import numpy as np
import pandas as pd

from oap.analytics.backtest import cluster_bootstrap_ci
from oap.analytics.config import (
    DEFAULT_CONFIG,
    DTE_BUCKETS,
    AnalyticsConfig,
    dte_bucket,
    fold_map_id,
)
from oap.analytics.sample import (
    OUTCOME_COLUMNS,
    QUOTE_COLUMNS,
    SNAPSHOT_KEY,
    SnapshotStatus,
    empty_frame,
    require_columns,
)
from oap.analytics.scoring import SPREAD_COLUMNS, score_session
from oap.engine._types import FloatArray
from oap.engine.calibration import CalibrationMap

ELIGIBLE_ALL: Final = "eligible_all"
"""Name of the no-selection baseline strategy."""

TRADE_COLUMNS: Final[tuple[str, ...]] = (
    *SPREAD_COLUMNS,
    "strategy",
    "is_out_of_sample",
)
"""Columns of a selected (not yet settled) trade: the scored spread and its strategy."""

SETTLED_COLUMNS: Final[tuple[str, ...]] = (
    *TRADE_COLUMNS,
    "settlement_date",
    "settlement_close",
    "max_loss_natural",
    "realised_payoff",
    "realised_return",
    "win",
    "max_loss_hit",
)
"""Columns of a settled trade."""

METRIC_COLUMNS: Final[tuple[str, ...]] = (
    "strategy",
    "segment_type",
    "segment",
    "metric",
    "value",
    "n_trades",
    "n_sessions",
)

EQUITY_COLUMNS: Final[tuple[str, ...]] = ("strategy", "trade_date", "cumulative_return", "drawdown")

METRICS: Final[tuple[str, ...]] = (
    "win_rate",
    "mean_predicted_pop",
    "pop_gap_realised",
    "mean_realised_return",
    "mean_predicted_return",
    "total_return",
    "median_realised_return",
    "worst_trade_return",
    "max_loss_rate",
    "sharpe_per_trade",
    "max_drawdown",
    "max_drawdown_session",
    "avg_dte_days",
)
"""Metrics computed for every strategy and segment, in output order."""

CI_METRICS: Final[tuple[str, ...]] = ("win_rate", "mean_realised_return")
"""Overall metrics that also get ``<metric>_ci_low`` and ``<metric>_ci_high`` rows."""

SEGMENT_TYPES: Final[tuple[str, ...]] = ("overall", "year", "underlying", "dte_bucket")

Basis = Literal["trade", "session"]


def strategy_names(top_n: int) -> tuple[str, str, str]:
    """Return the strategy names for a top-``N`` selection, the live entry ranking first.

    Args:
        top_n: Number of spreads selected per session; at least 1.

    Returns:
        ``(f"entry_top{top_n}", f"return_top{top_n}", "eligible_all")``.

    Raises:
        ValueError: If ``top_n`` is below 1.
    """
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    return f"entry_top{top_n}", f"return_top{top_n}", ELIGIBLE_ALL


def _single_session(quotes: pd.DataFrame) -> None:
    """Require that quotes hold at most one ``trade_date``.

    Args:
        quotes: Quote rows.

    Raises:
        ValueError: If more than one trade date is present.
    """
    if quotes["trade_date"].nunique() > 1:
        raise ValueError("quotes must hold a single trade_date")


def select_session_entries(
    quotes_session: pd.DataFrame,
    cmap: CalibrationMap,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    *,
    top_n: int | None,
    map_id: str,
    rank_column: str = "rank_entry",
) -> pd.DataFrame:
    """Rank one session with the live scoring path and return the selected spreads.

    The session is scored by ``score_session`` (the function behind
    ``score_latest_session``) with ``eligible_only``, which yields exactly the eligible rows
    and ranks of a full run.

    Args:
        quotes_session: Quote rows of one ``trade_date``, all underlyings and expirations.
        cmap: Calibration map available on that date.
        config: Analytics parameters.
        top_n: Rows with ``rank_column <= top_n``, best first; None returns every eligible
            spread in scoring order.
        map_id: Identifier of ``cmap``, recorded on every row.
        rank_column: ``rank_entry`` (the live entry ranking) or ``rank`` (raw return order).

    Returns:
        Rows with ``SPREAD_COLUMNS``.

    Raises:
        ValueError: If a column is missing or the quotes span several trade dates.
    """
    require_columns(quotes_session, QUOTE_COLUMNS, "quotes")
    _single_session(quotes_session)
    scores = score_session(quotes_session, cmap, config, map_id=map_id, eligible_only=True)
    return _pick(scores, rank_column, top_n)


def _pick(scores: pd.DataFrame, rank_column: str, top_n: int | None) -> pd.DataFrame:
    """Select rows of a scored session.

    Args:
        scores: Output of ``score_session``.
        rank_column: Rank column to select on.
        top_n: Largest rank kept; None keeps every eligible row.

    Returns:
        The selected rows on a default index, best rank first when ``top_n`` is given.
    """
    if top_n is None:
        return scores.loc[scores["eligible"].astype(bool)].reset_index(drop=True)
    ranks = scores[rank_column]
    chosen = scores.loc[ranks.notna() & (ranks <= top_n)]
    return chosen.sort_values(rank_column, kind="stable").reset_index(drop=True)


def session_map(
    maps: Mapping[str, CalibrationMap],
    trade_date: pd.Timestamp,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> tuple[str, CalibrationMap, bool] | None:
    """Choose the calibration map available on a trade date.

    The map is ``fold_<year of trade_date>``, fitted only on expirations before 1 January of
    that year; the production map is never used. The out-of-sample rule is the one of
    ``apply_fold_maps``.

    Args:
        maps: Calibration maps keyed by map id.
        trade_date: Session date.
        config: Analytics parameters; ``first_test_year`` starts the out-of-sample years.

    Returns:
        ``(map_id, map, is_out_of_sample)``, or None when the year has no fold map.
    """
    year = pd.Timestamp(trade_date).year
    map_id = fold_map_id(year)
    cmap = maps.get(map_id)
    if cmap is None:
        return None
    return map_id, cmap, year >= config.first_test_year and not cmap.is_identity


def ok_quotes(quotes: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    """Keep the quotes of snapshots whose status is ``ok``, as the calibration sample does.

    Args:
        quotes: Quote rows.
        snapshots: ``calibration_snapshot`` rows with the snapshot key and ``status``.

    Returns:
        The quotes of ok snapshots, in their original order.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(quotes, QUOTE_COLUMNS, "quotes")
    require_columns(snapshots, (*SNAPSHOT_KEY, "status"), "snapshots")
    key = list(SNAPSHOT_KEY)
    ok = snapshots.loc[snapshots["status"] == SnapshotStatus.OK.value, key].drop_duplicates()
    return quotes.merge(ok, on=key, how="inner")


def backtest_session(
    quotes_session: pd.DataFrame,
    snapshots: pd.DataFrame,
    maps: Mapping[str, CalibrationMap],
    config: AnalyticsConfig = DEFAULT_CONFIG,
    *,
    top_n: int,
) -> pd.DataFrame:
    """Select the trades of every strategy on one session.

    The quotes are restricted to ok snapshots, the session's fold map is chosen by
    ``session_map``, the session is scored once by ``score_session`` and the three strategies
    are read off the ranks.

    Args:
        quotes_session: Quote rows of one ``trade_date``.
        snapshots: ``calibration_snapshot`` rows (any dates).
        maps: Calibration maps keyed by map id.
        config: Analytics parameters.
        top_n: Spreads per session of the two top-``N`` strategies.

    Returns:
        Rows with ``TRADE_COLUMNS``; empty when the session has no ok snapshot, no fold map or
        no eligible spread.

    Raises:
        ValueError: If a column is missing, ``top_n`` is below 1 or the quotes span several
            trade dates.
    """
    entry, by_return, everything = strategy_names(top_n)
    require_columns(quotes_session, QUOTE_COLUMNS, "quotes")
    _single_session(quotes_session)
    quotes = ok_quotes(quotes_session, snapshots)
    if quotes.empty:
        return empty_frame(TRADE_COLUMNS)
    chosen = session_map(maps, pd.Timestamp(quotes["trade_date"].iloc[0]), config)
    if chosen is None:
        return empty_frame(TRADE_COLUMNS)
    map_id, cmap, out_of_sample = chosen
    scores = score_session(quotes, cmap, config, map_id=map_id, eligible_only=True)
    if scores.empty:
        return empty_frame(TRADE_COLUMNS)
    parts = []
    for name, column, n in (
        (entry, "rank_entry", top_n),
        (by_return, "rank", top_n),
        (everything, "rank", None),
    ):
        part = _pick(scores, column, n)
        part["strategy"] = name
        part["is_out_of_sample"] = out_of_sample
        parts.append(part)
    return pd.concat(parts, ignore_index=True)[list(TRADE_COLUMNS)]


def settle_trades(trades: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Settle trades at the settlement close of their expiration, held to expiry.

    Per share, with natural credit ``c_n``, short strike ``K``, width ``W`` and settlement
    close ``S_T``: ``realised_payoff = c_n - clip(K - S_T, 0, W)``,
    ``max_loss_natural = W - c_n``, ``realised_return = realised_payoff / max_loss_natural``,
    ``win = realised_payoff > 0`` and ``max_loss_hit = S_T <= long_strike``.

    Args:
        trades: Rows with ``TRADE_COLUMNS``.
        outcomes: ``fct_expiration_outcome`` rows with ``OUTCOME_COLUMNS``.

    Returns:
        The settled rows with ``SETTLED_COLUMNS`` in the order of ``trades``, and the number of
        rows dropped because their expiration has no settlement close yet.

    Raises:
        ValueError: If a column is missing or a natural credit is not below the width.
    """
    require_columns(trades, TRADE_COLUMNS, "trades")
    require_columns(outcomes, OUTCOME_COLUMNS, "outcomes")
    if trades.empty:
        return empty_frame(SETTLED_COLUMNS), 0
    settled = outcomes[list(OUTCOME_COLUMNS)].drop_duplicates(["underlying", "expiration"])
    joined = trades[list(TRADE_COLUMNS)].merge(
        settled, on=["underlying", "expiration"], how="left", validate="many_to_one"
    )
    known = joined["settlement_close"].notna()
    dropped = int((~known).sum())
    out = joined.loc[known].reset_index(drop=True)
    close = out["settlement_close"].to_numpy(dtype=np.float64)
    short = out["short_strike"].to_numpy(dtype=np.float64)
    long = out["long_strike"].to_numpy(dtype=np.float64)
    width = out["width"].to_numpy(dtype=np.float64)
    natural = out["credit_natural"].to_numpy(dtype=np.float64)
    max_loss = width - natural
    if bool((max_loss <= 0).any()):
        raise ValueError("credit_natural must be below the width")
    payoff = natural - np.clip(short - close, 0.0, width)
    out["max_loss_natural"] = max_loss
    out["realised_payoff"] = payoff
    out["realised_return"] = payoff / max_loss
    out["win"] = payoff > 0
    out["max_loss_hit"] = close <= long
    return out[list(SETTLED_COLUMNS)], dropped


def _session_returns(trades: pd.DataFrame, basis: Basis) -> pd.Series:
    """Return the realised return booked on each session, in date order.

    Args:
        trades: Settled trades of one strategy.
        basis: ``trade`` puts one dollar of maximum loss on every trade, so a session books
            the sum of its trades' returns; ``session`` puts one dollar on every session,
            split equally across its trades, so it books their mean.

    Returns:
        Returns indexed by ``trade_date``, ascending.
    """
    grouped = trades.groupby("trade_date", sort=True)["realised_return"]
    return grouped.sum() if basis == "trade" else grouped.mean()


def _drawdowns(cumulative: FloatArray) -> FloatArray:
    """Return the drawdown below the running peak (starting from 0) at every point.

    Args:
        cumulative: Cumulative return per step, in dollars per dollar of maximum loss.

    Returns:
        Non-negative drawdowns in the same unit.
    """
    peak = np.maximum.accumulate(np.concatenate([[0.0], cumulative]))[1:]
    return np.asarray(peak - cumulative, dtype=np.float64)


def equity_curve(trades: pd.DataFrame, *, basis: Basis = "trade") -> pd.DataFrame:
    """Cumulative realised return per strategy, booked on the trade date of each session.

    Args:
        trades: Settled trades (``strategy``, ``trade_date``, ``realised_return``).
        basis: ``trade`` (one dollar of maximum loss per trade) or ``session`` (one dollar per
            session, split equally across its trades, which puts strategies with different
            trade counts on one scale).

    Returns:
        Rows with ``EQUITY_COLUMNS``, by strategy then date. ``cumulative_return`` and
        ``drawdown`` (non-negative, below the running peak) are in dollars per dollar of
        maximum loss.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(trades, ("strategy", "trade_date", "realised_return"), "trades")
    parts = []
    for strategy, group in trades.groupby("strategy", sort=False):
        per_session = _session_returns(group, basis)
        cumulative = per_session.cumsum().to_numpy(dtype=np.float64)
        parts.append(
            pd.DataFrame(
                {
                    "strategy": strategy,
                    "trade_date": per_session.index,
                    "cumulative_return": cumulative,
                    "drawdown": _drawdowns(cumulative),
                }
            )
        )
    if not parts:
        return empty_frame(EQUITY_COLUMNS)
    return pd.concat(parts, ignore_index=True)[list(EQUITY_COLUMNS)]


def _max_drawdown(trades: pd.DataFrame, basis: Basis) -> float:
    """Return the largest drawdown of one strategy's equity curve.

    Args:
        trades: Settled trades of one strategy, non-empty.
        basis: See ``equity_curve``.

    Returns:
        The maximum drawdown in dollars per dollar of maximum loss, non-negative.
    """
    cumulative = _session_returns(trades, basis).cumsum().to_numpy(dtype=np.float64)
    return float(_drawdowns(cumulative).max())


def _sharpe(returns: FloatArray) -> float:
    """Return mean over sample standard deviation, or nan with fewer than two or no spread."""
    if returns.shape[0] < 2:
        return math.nan
    std = float(np.std(returns, ddof=1))
    return math.nan if std == 0.0 else float(np.mean(returns)) / std


def _segment_values(trades: pd.DataFrame) -> dict[str, float]:
    """Compute every metric of ``METRICS`` for one non-empty set of trades.

    Args:
        trades: Settled trades of one strategy and segment.

    Returns:
        Metric name to value; see ``strategy_metrics`` for the definitions.
    """
    realised = trades["realised_return"].to_numpy(dtype=np.float64)
    win = trades["win"].to_numpy(dtype=np.bool_)
    pop = trades["prob_profit"].to_numpy(dtype=np.float64)
    win_rate = float(win.mean())
    return {
        "win_rate": win_rate,
        "mean_predicted_pop": float(pop.mean()),
        "pop_gap_realised": win_rate - float(pop.mean()),
        "mean_realised_return": float(realised.mean()),
        "mean_predicted_return": float(trades["expected_roc"].astype("float64").mean()),
        "total_return": float(
            trades["realised_payoff"].astype("float64").sum()
            / trades["max_loss_natural"].astype("float64").sum()
        ),
        "median_realised_return": float(np.median(realised)),
        "worst_trade_return": float(realised.min()),
        "max_loss_rate": float(trades["max_loss_hit"].astype(bool).mean()),
        "sharpe_per_trade": _sharpe(realised),
        "max_drawdown": _max_drawdown(trades, "trade"),
        "max_drawdown_session": _max_drawdown(trades, "session"),
        "avg_dte_days": float(trades["dte_days"].astype("float64").mean()),
    }


def _segments(trades: pd.DataFrame) -> Iterator[tuple[str, str, pd.DataFrame]]:
    """Yield the overall set and every year, underlying and DTE bucket segment.

    Args:
        trades: Settled out-of-sample trades of one strategy.

    Yields:
        ``(segment_type, segment, rows)``: overall first, then years, underlyings and DTE
        buckets (shortest first), each in ascending order.
    """
    yield "overall", "all", trades
    keys = {
        "year": pd.to_datetime(trades["trade_date"]).dt.year.astype(str),
        "underlying": trades["underlying"].astype(str),
        "dte_bucket": trades["dte_days"].astype(int).map(dte_bucket),
    }
    for segment_type, key in keys.items():
        values = set(key.tolist())
        order = (
            [b for b in DTE_BUCKETS if b in values]
            if segment_type == "dte_bucket"
            else sorted(values)
        )
        for name in order:
            yield segment_type, name, trades.loc[(key == name).to_numpy()]


def _strategy_order(strategies: list[str]) -> list[str]:
    """Order strategies as entry, return, then the baseline, then any other by name."""

    def key(name: str) -> tuple[int, str]:
        if name.startswith("entry_top"):
            return 0, name
        if name.startswith("return_top"):
            return 1, name
        return (2, name) if name == ELIGIBLE_ALL else (3, name)

    return sorted(strategies, key=key)


def strategy_metrics(
    trades: pd.DataFrame, *, config: AnalyticsConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """Summarise realised against predicted performance on the out-of-sample trades.

    Per strategy and segment (overall, year of the trade date, underlying, DTE bucket):

    * ``win_rate``: share of trades with a positive payoff; ``mean_predicted_pop``: mean
      calibrated probability of profit; ``pop_gap_realised``: their difference;
    * ``mean_realised_return`` and ``median_realised_return``: realised return on max loss;
      ``mean_predicted_return``: mean ``expected_roc``; ``worst_trade_return``: the minimum;
    * ``total_return``: total payoff over total maximum loss, the return on all capital put
      at risk;
    * ``max_loss_rate``: share of trades settling at or below the long strike;
    * ``sharpe_per_trade``: mean over sample standard deviation of the realised returns
      (nan below two trades or with no dispersion);
    * ``max_drawdown``: largest fall of the cumulative realised return with one dollar of
      maximum loss per trade, booked by session in date order; ``max_drawdown_session``: the
      same with one dollar per session (``equity_curve`` bases), comparable across
      strategies with different trade counts;
    * ``avg_dte_days``: mean calendar days to expiry.

    The overall segment also has ``win_rate_ci_low``/``_ci_high`` and
    ``mean_realised_return_ci_low``/``_ci_high``: a 95% cluster-bootstrap interval that
    resamples expiration dates (``cluster_bootstrap_ci``), because trades expiring on one date
    share one market move.

    Args:
        trades: Output of ``settle_trades`` (any strategies; rows not out of sample are
            ignored).
        config: Analytics parameters (bootstrap size and seed).

    Returns:
        Rows with ``METRIC_COLUMNS``; empty when no trade is out of sample.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(trades, SETTLED_COLUMNS, "trades")
    oos = trades.loc[trades["is_out_of_sample"].astype(bool)]
    rows: list[dict[str, object]] = []
    for strategy in _strategy_order([str(s) for s in oos["strategy"].unique()]):
        mine = oos.loc[oos["strategy"] == strategy]
        for segment_type, segment, part in _segments(mine):
            counts = {"n_trades": len(part), "n_sessions": int(part["trade_date"].nunique())}
            values = _segment_values(part)
            if segment_type == "overall":
                clusters = part["expiration"].to_numpy()
                for metric, column in zip(CI_METRICS, ("win", "realised_return"), strict=True):
                    low, high = cluster_bootstrap_ci(
                        part[column].to_numpy(dtype=np.float64),
                        clusters,
                        resamples=config.bootstrap_resamples,
                        seed=config.bootstrap_seed,
                    )
                    values[f"{metric}_ci_low"] = low
                    values[f"{metric}_ci_high"] = high
            for metric, value in values.items():
                rows.append(
                    {
                        "strategy": strategy,
                        "segment_type": segment_type,
                        "segment": segment,
                        "metric": metric,
                        "value": value,
                        **counts,
                    }
                )
    if not rows:
        return empty_frame(METRIC_COLUMNS)
    return pd.DataFrame(rows, columns=list(METRIC_COLUMNS)).astype(
        {"n_trades": "int64", "n_sessions": "int64"}
    )


def leaking_trades(trades: pd.DataFrame, map_table: pd.DataFrame) -> pd.DataFrame:
    """Find trades whose calibration map could have seen their own or later outcomes.

    A trade leaks when it used the production map, a map missing from the table, or a map
    whose latest training expiration is on or after the trade date. An identity map with no
    training rows (null ``train_max_expiration``) does not leak.

    Args:
        trades: Rows with ``map_id`` and ``trade_date``.
        map_table: ``calibration_map`` rows with ``map_id`` and ``train_max_expiration``.

    Returns:
        The leaking rows of ``trades``; empty when the backtest is out of sample.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(trades, ("map_id", "trade_date"), "trades")
    require_columns(map_table, ("map_id", "train_max_expiration"), "map table")
    latest = (
        map_table.groupby("map_id", sort=True)["train_max_expiration"]
        .max()
        .rename("map_latest")
        .reset_index()
    )
    joined = trades.merge(latest, on="map_id", how="left", indicator=True)
    unknown = (joined["_merge"] == "left_only").to_numpy(dtype=np.bool_)
    late = (pd.to_datetime(joined["map_latest"]) >= pd.to_datetime(joined["trade_date"])).to_numpy(
        dtype=np.bool_
    )
    production = ~joined["map_id"].astype(str).str.startswith("fold_").to_numpy(dtype=np.bool_)
    mask = unknown | late | production
    return trades.reset_index(drop=True).loc[mask].reset_index(drop=True)
