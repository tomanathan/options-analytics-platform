"""Rule lab: candidate selection rules for put credit spreads, evaluated walk-forward.

The strategy backtest (``oap.analytics.strategy``) measures one rule, the live "Top 10 to
enter". The rule lab measures many. Its input is every eligible spread of every historical
session, scored by ``score_session`` with the walk-forward map of its year and settled at
expiry by ``settle_trades`` (the scored-spread cache), plus per ``(underlying, trade_date)``
regime features. A ``Rule`` is a selection over those rows: gates, a ranking, an optional
one-spread-per-underlying-and-expiry diversification, then the top ``N`` per session.

Guards. A rule only ever chooses among spreads that pass every guard of the live entry
ranking (eligible, calibrated POP at least ``entry_min_pop``, credit at least
``min_edge_credit``, natural credit at least ``min_natural_fraction`` of the mid with a
positive natural edge, inside the quoted strikes, no tail, sparse or unknown-forward flag).
``score_session`` sets ``rank_entry`` on exactly those spreads, so the guard is
``rank_entry`` being non-null, and ``rank_entry`` breaks every tie of a ranking. The baseline
rule (``Rule()``) therefore selects exactly the live ``entry_top10`` trades.

Rankings (higher is better; nan ranks last), with natural credit ``c_n``, width ``W``,
natural max loss ``L_n = W - c_n``, natural odds ``b = c_n / L_n``, calibrated POP ``p`` and
holding period ``years``; annualising is ``(1 + r) ** (1 / years) - 1`` as in the engine:

* ``return_mid``: ``annualised_roc`` (mid credit, interest included), the live ranking;
* ``return_natural``: ``r = edge_natural / L_n`` annualised, the calibrated expected return
  at the price one can fill, without interest;
* ``reward_to_risk``: expected payoff over its standard deviation, per trade;
* ``kelly_growth``: ``p * log(1 + b * f) + (1 - p) * log(1 - f)`` with ``f`` the score's
  ``kelly_fraction`` clipped to ``[0, KELLY_CAP]``: the expected log growth per trade of a
  two-outcome bet at natural odds. It is at most 0 whenever ``p * b < 1 - p``;
* ``pop_shrunk_return``: ``r = q * b - (1 - q)`` annualised, the two-outcome natural return
  with the POP shrunk halfway toward the market's ``pop_implied``:
  ``q = (1 - POP_SHRINK) * p + POP_SHRINK * pop_implied``. It discounts the calibration
  where it disagrees most with the price, which is where the winner's curse bites.

Regime features use end-of-day data of the trade date, the same time as the fill:
``ret_20`` and ``ret_5`` are log returns of the underlying over the last 20 and 5 sessions
(a day whose absolute log return exceeds ``split_abs_log_return`` counts as 0, since the
closes are not split-adjusted); ``atm_iv`` is the vendor IV of the out-of-the-money option
nearest the money in the shortest expiry with at least ``ATM_MIN_DTE`` days;
``atm_iv_change_5`` is ``atm_iv`` over its value five sessions earlier, minus 1;
``iv_rank_120`` is the share of the previous 119 sessions whose ``atm_iv`` is below today's.
A rule's regime gate fails when a feature it needs is missing.

Evaluation splits trades into periods by the calendar year of the trade date (never by
expiration), keeps out-of-sample trades only, and reports per period the metrics of
``LAB_METRICS``; the hold-out also gets a cluster-bootstrap interval (by expiration) for
the mean realised return.

Units: prices, strikes, credits and payoffs in dollars per share; returns are decimals on
max loss (0.02 is 2%) over the holding period unless annualised; volatility is a decimal
(0.20 is 20%); probabilities are decimals in [0, 1]; ``dte_days`` is calendar days and
``years`` is calendar days / 365; drawdowns are in dollars per dollar of maximum loss with
one dollar per session split across its trades.
"""

import itertools
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

from oap.analytics.backtest import cluster_bootstrap_ci
from oap.analytics.config import DEFAULT_CONFIG, AnalyticsConfig
from oap.analytics.sample import require_columns
from oap.analytics.strategy import SETTLED_COLUMNS
from oap.engine._types import FloatArray

RankBy = Literal[
    "return_mid", "return_natural", "reward_to_risk", "kelly_growth", "pop_shrunk_return"
]
Regime = Literal["none", "trend_up", "calm", "trend_up_calm", "high_iv_rank"]
DteBand = tuple[int, int]
MoneynessBand = tuple[float, float]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]

RANK_BYS: Final[tuple[RankBy, ...]] = (
    "return_mid",
    "return_natural",
    "reward_to_risk",
    "kelly_growth",
    "pop_shrunk_return",
)
DTE_BANDS: Final[tuple[DteBand | None, ...]] = (None, (7, 21), (21, 45), (45, 70))
"""Days-to-expiry bands of the grid, ``lo <= dte_days < hi`` in calendar days."""
MONEYNESS_BANDS: Final[tuple[MoneynessBand | None, ...]] = (
    None,
    (0.80, 0.90),
    (0.90, 0.95),
    (0.95, 1.00),
)
"""Short strike over close bands of the grid, ``lo <= short_moneyness < hi``."""
REGIMES: Final[tuple[Regime, ...]] = ("none", "trend_up", "calm", "trend_up_calm", "high_iv_rank")
EDGE_MARGINS: Final[tuple[float, ...]] = (0.0, 0.10)
"""Required natural credit over fair credit, minus 1, as decimals."""

KELLY_CAP: Final = 0.5
"""Largest Kelly fraction used by ``kelly_growth``, a decimal share of capital."""
POP_SHRINK: Final = 0.5
"""Weight of ``pop_implied`` in the shrunk POP of ``pop_shrunk_return``."""

RET_LONG: Final = 20
RET_SHORT: Final = 5
IV_CHANGE_LAG: Final = 5
IV_RANK_WINDOW: Final = 120
ATM_MIN_DTE: Final = 7
"""Shortest expiry, in calendar days, whose IV can be the ``atm_iv``."""
CALM_MAX_IV_CHANGE: Final = 0.20
"""``calm`` holds when ``atm_iv_change_5`` is below this decimal."""
HIGH_IV_RANK: Final = 0.5
"""``high_iv_rank`` holds when ``iv_rank_120`` is at least this decimal."""

REGIME_COLUMNS: Final[tuple[str, ...]] = (
    "underlying",
    "trade_date",
    "ret_5",
    "ret_20",
    "atm_iv",
    "atm_iv_change_5",
    "iv_rank_120",
)
DAILY_COLUMNS: Final[tuple[str, ...]] = ("underlying", "trade_date", "log_return")
IV_QUOTE_COLUMNS: Final[tuple[str, ...]] = (
    "underlying",
    "trade_date",
    "expiration",
    "strike",
    "option_right",
    "source_iv",
    "underlying_close",
    "dte_days",
)

PERIODS: Final[tuple[str, ...]] = ("dev", "holdout")
LAB_METRICS: Final[tuple[str, ...]] = (
    "n_trades",
    "n_sessions",
    "win_rate",
    "mean_predicted_pop",
    "mean_realised_return",
    "total_return",
    "sharpe_per_trade",
    "max_drawdown",
    "max_loss_rate",
)
"""Metrics of every period; the hold-out also has ``mean_realised_return_ci_low/high``."""

_RANK_CODES: Final[dict[str, str]] = {
    "return_mid": "rm",
    "return_natural": "rn",
    "reward_to_risk": "rr",
    "kelly_growth": "kg",
    "pop_shrunk_return": "ps",
}
_REGIME_CODES: Final[dict[str, str]] = {
    "none": "any",
    "trend_up": "up",
    "calm": "calm",
    "trend_up_calm": "upcalm",
    "high_iv_rank": "ivr",
}
_RANK_WORDS: Final[dict[str, str]] = {
    "return_mid": "annualised return on max loss at the mid credit (the live ranking)",
    "return_natural": "annualised calibrated return on max loss at the natural credit",
    "reward_to_risk": "reward to risk (expected payoff over its standard deviation)",
    "kelly_growth": "expected log growth of a capped Kelly bet at natural odds",
    "pop_shrunk_return": (
        "annualised natural return with the POP shrunk halfway toward the market-implied POP"
    ),
}
_REGIME_WORDS: Final[dict[str, str]] = {
    "none": "",
    "trend_up": "only when the underlying's 20-session return is positive",
    "calm": "only when the near-the-money IV rose less than 20% over 5 sessions",
    "trend_up_calm": (
        "only when the underlying's 20-session return is positive and the near-the-money IV "
        "rose less than 20% over 5 sessions"
    ),
    "high_iv_rank": "only when the near-the-money IV is at or above its 120-session median rank",
}


def _percent_code(value: float) -> str:
    """Format a decimal as a compact whole-percent code, such as ``0.95`` to ``95``."""
    return f"{round(value * 100, 4):g}"


@dataclass(frozen=True)
class Rule:
    """A selection rule for put credit spreads, applied to one session at a time.

    Attributes:
        rank_by: The ranking; see the module docstring.
        dte_band: ``(lo, hi)`` calendar days, keeping ``lo <= dte_days < hi``; None keeps all.
        moneyness_band: ``(lo, hi)`` short strike over close, keeping
            ``lo <= short_moneyness < hi``; None keeps all.
        one_per_underlying_expiry: Keep only the best-ranked spread of each underlying and
            expiration before taking the top ``N``.
        regime: Regime gate on the underlying's features of the trade date.
        natural_edge_margin: Require ``credit_natural >= (1 + margin) * fair_credit``, a
            non-negative decimal.
        top_n: Spreads per session, at least 1.
    """

    rank_by: RankBy = "return_mid"
    dte_band: DteBand | None = None
    moneyness_band: MoneynessBand | None = None
    one_per_underlying_expiry: bool = False
    regime: Regime = "none"
    natural_edge_margin: float = 0.0
    top_n: int = 10

    def __post_init__(self) -> None:
        """Validate the fields.

        Raises:
            ValueError: If a field is outside its domain.
        """
        if self.rank_by not in RANK_BYS:
            raise ValueError(f"unknown rank_by {self.rank_by!r}")
        if self.regime not in REGIMES:
            raise ValueError(f"unknown regime {self.regime!r}")
        for band in (self.dte_band, self.moneyness_band):
            if band is not None and not band[0] < band[1]:
                raise ValueError("a band must have lo < hi")
        if not self.natural_edge_margin >= 0:
            raise ValueError("natural_edge_margin must be non-negative")
        if self.top_n < 1:
            raise ValueError("top_n must be at least 1")

    @property
    def rule_id(self) -> str:
        """Return a short identifier that depends only on the fields.

        Returns:
            Such as ``rn-d21_45-m90_95-one-calm-e10-n10``.
        """
        dte = "dany" if self.dte_band is None else f"d{self.dte_band[0]}_{self.dte_band[1]}"
        band = self.moneyness_band
        money = "many" if band is None else f"m{_percent_code(band[0])}_{_percent_code(band[1])}"
        return "-".join(
            (
                _RANK_CODES[self.rank_by],
                dte,
                money,
                "one" if self.one_per_underlying_expiry else "all",
                _REGIME_CODES[self.regime],
                f"e{_percent_code(self.natural_edge_margin)}",
                f"n{self.top_n}",
            )
        )


BASELINE_RULE: Final = Rule()
"""The live "Top 10 to enter" rule."""


def describe_rule(rule: Rule) -> str:
    """State a rule in words.

    Args:
        rule: The rule.

    Returns:
        One sentence.
    """
    parts = [f"Rank by {_RANK_WORDS[rule.rank_by]}"]
    if rule.dte_band is not None:
        parts.append(f"{rule.dte_band[0]} to {rule.dte_band[1] - 1} days to expiry")
    if rule.moneyness_band is not None:
        lo, hi = rule.moneyness_band
        parts.append(f"short strike from {lo:.0%} to below {hi:.0%} of the close")
    if rule.one_per_underlying_expiry:
        parts.append("at most one spread per underlying and expiry")
    if rule.regime != "none":
        parts.append(_REGIME_WORDS[rule.regime])
    if rule.natural_edge_margin > 0:
        parts.append(
            f"natural credit at least {rule.natural_edge_margin:.0%} above the fair credit"
        )
    parts.append(f"top {rule.top_n} per session, after every entry guard")
    return "; ".join(parts) + "."


def rule_grid(top_n: int = 10) -> tuple[Rule, ...]:
    """Return the full factorial grid of rules, the baseline first.

    Args:
        top_n: Spreads per session of every rule.

    Returns:
        ``len(RANK_BYS) * len(DTE_BANDS) * len(MONEYNESS_BANDS) * 2 * len(REGIMES) *
        len(EDGE_MARGINS)`` rules (1,600), the last field varying fastest.
    """
    return tuple(
        Rule(
            rank_by=rank_by,
            dte_band=dte,
            moneyness_band=money,
            one_per_underlying_expiry=one,
            regime=regime,
            natural_edge_margin=margin,
            top_n=top_n,
        )
        for rank_by, dte, money, one, regime, margin in itertools.product(
            RANK_BYS, DTE_BANDS, MONEYNESS_BANDS, (False, True), REGIMES, EDGE_MARGINS
        )
    )


# --- rankings --------------------------------------------------------------------------------


def _floats(frame: pd.DataFrame, column: str) -> FloatArray:
    """Return a column as a float64 array."""
    return np.asarray(frame[column].to_numpy(dtype=np.float64), dtype=np.float64)


def annualise(returns: FloatArray, years: FloatArray) -> FloatArray:
    """Compound holding-period returns to one year, as the engine does.

    Args:
        returns: Returns over the holding period, decimals.
        years: Holding periods in years, positive.

    Returns:
        ``(1 + r) ** (1 / years) - 1``; -1 where ``r <= -1``; infinity on overflow.
    """
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        grown = np.expm1(np.log1p(np.maximum(returns, -1.0)) / years)
    return np.asarray(np.where(returns <= -1.0, -1.0, grown), dtype=np.float64)


def natural_odds(frame: pd.DataFrame) -> FloatArray:
    """Return ``credit_natural / (width - credit_natural)``, the odds at the natural fill."""
    natural = _floats(frame, "credit_natural")
    return np.asarray(natural / (_floats(frame, "width") - natural), dtype=np.float64)


def kelly_growth(prob: FloatArray, odds: FloatArray, kelly: FloatArray) -> FloatArray:
    """Return the expected log growth of a two-outcome bet at a capped Kelly fraction.

    Args:
        prob: Probability of profit, decimals in [0, 1].
        odds: Win over loss per dollar risked (natural credit over natural max loss).
        kelly: Kelly fraction of the score, clipped to ``[0, KELLY_CAP]``.

    Returns:
        ``p * log(1 + b * f) + (1 - p) * log(1 - f)`` per trade, in log dollars per dollar.
    """
    f = np.clip(kelly, 0.0, KELLY_CAP)
    return np.asarray(prob * np.log1p(odds * f) + (1.0 - prob) * np.log1p(-f), dtype=np.float64)


def shrunk_pop(prob: FloatArray, pop_implied: FloatArray) -> FloatArray:
    """Return the calibrated POP shrunk toward the market-implied POP by ``POP_SHRINK``."""
    return np.asarray((1.0 - POP_SHRINK) * prob + POP_SHRINK * pop_implied, dtype=np.float64)


def rank_score(frame: pd.DataFrame, rank_by: RankBy) -> FloatArray:
    """Return the ranking score of every row; higher ranks first.

    Args:
        frame: Scored spreads with ``SPREAD_COLUMNS``.
        rank_by: The ranking; see the module docstring.

    Returns:
        One float per row; nan where the score is undefined.
    """
    if rank_by == "return_mid":
        return _floats(frame, "annualised_roc")
    if rank_by == "reward_to_risk":
        return _floats(frame, "reward_to_risk")
    odds = natural_odds(frame)
    prob = _floats(frame, "prob_profit")
    years = _floats(frame, "years")
    if rank_by == "kelly_growth":
        return kelly_growth(prob, odds, _floats(frame, "kelly_fraction"))
    if rank_by == "return_natural":
        loss = _floats(frame, "width") - _floats(frame, "credit_natural")
        return annualise(_floats(frame, "edge_natural") / loss, years)
    q = shrunk_pop(prob, _floats(frame, "pop_implied"))
    return annualise(q * odds - (1.0 - q), years)


# --- regime features -------------------------------------------------------------------------


def _by_underlying(frame: pd.DataFrame) -> pd.DataFrame:
    """Sort by underlying and trade date on a default index."""
    return frame.sort_values(["underlying", "trade_date"], kind="stable").reset_index(drop=True)


def return_features(daily: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """Compute ``ret_5`` and ``ret_20`` per underlying and session.

    Args:
        daily: ``fct_underlying_daily`` rows with ``DAILY_COLUMNS``; ``log_return`` is the
            log of close over the previous close (null on an underlying's first row).
        config: ``split_abs_log_return`` marks an unadjusted split, counted as 0.

    Returns:
        ``underlying``, ``trade_date``, ``ret_5`` and ``ret_20``: sums of the last 5 and 20
        log returns (decimals), nan until that many returns exist.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(daily, DAILY_COLUMNS, "daily")
    work = _by_underlying(daily[list(DAILY_COLUMNS)])
    work["trade_date"] = pd.to_datetime(work["trade_date"]).astype("datetime64[ns]")
    returns = work["log_return"].astype("float64")
    returns = returns.mask(returns.abs() > config.split_abs_log_return, 0.0)
    grouped = returns.groupby(work["underlying"], sort=False)
    for name, window in (("ret_5", RET_SHORT), ("ret_20", RET_LONG)):
        rolled = grouped.rolling(window, min_periods=window).sum()
        work[name] = rolled.reset_index(level=0, drop=True)
    return work[["underlying", "trade_date", "ret_5", "ret_20"]]


def atm_iv(quotes: pd.DataFrame) -> pd.DataFrame:
    """Return the near-the-money implied volatility per underlying and session.

    Out-of-the-money quotes (puts at or below the close, calls at or above it) with a
    positive vendor IV and at least ``ATM_MIN_DTE`` days to expiry are kept; within the
    shortest such expiry the quotes nearest the money (smallest ``|strike / close - 1|``)
    are averaged.

    Args:
        quotes: Rows with ``IV_QUOTE_COLUMNS``; ``source_iv`` is a decimal.

    Returns:
        ``underlying``, ``trade_date`` and ``atm_iv`` (decimal), one row per pair with a
        usable quote, sorted.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(quotes, IV_QUOTE_COLUMNS, "quotes")
    iv = quotes["source_iv"].astype("float64")
    close = quotes["underlying_close"].astype("float64")
    strike = quotes["strike"].astype("float64")
    right = quotes["option_right"].astype(str)
    otm = ((right == "P") & (strike <= close)) | ((right == "C") & (strike >= close))
    keep = (
        otm
        & (quotes["dte_days"].astype("int64") >= ATM_MIN_DTE)
        & np.isfinite(iv)
        & (iv > 0)
        & np.isfinite(close)
        & (close > 0)
    )
    work = quotes.loc[keep, ["underlying", "trade_date", "dte_days"]].copy()
    if work.empty:
        return pd.DataFrame(
            {
                "underlying": pd.Series(dtype="object"),
                "trade_date": pd.Series(dtype="datetime64[ns]"),
                "atm_iv": pd.Series(dtype="float64"),
            }
        )
    work["trade_date"] = pd.to_datetime(work["trade_date"]).astype("datetime64[ns]")
    work["iv"] = iv[keep]
    work["distance"] = (strike[keep] / close[keep] - 1.0).abs()
    key = ["underlying", "trade_date"]
    shortest = work["dte_days"] == work.groupby(key)["dte_days"].transform("min")
    work = work.loc[shortest]
    nearest = work["distance"] <= work.groupby(key)["distance"].transform("min") + 1e-12
    out = work.loc[nearest].groupby(key, sort=True)["iv"].mean().rename("atm_iv").reset_index()
    return out


def iv_features(atm: pd.DataFrame) -> pd.DataFrame:
    """Add the five-session IV change and the 120-session IV rank to ``atm_iv`` rows.

    Sessions are the rows of each underlying in date order.

    Args:
        atm: ``underlying``, ``trade_date`` and ``atm_iv`` (decimal), as ``atm_iv`` returns.

    Returns:
        The rows sorted, with ``atm_iv_change_5`` (``atm_iv`` over its value
        ``IV_CHANGE_LAG`` sessions earlier, minus 1) and ``iv_rank_120`` (share of the
        previous ``IV_RANK_WINDOW - 1`` sessions with a lower ``atm_iv``, in [0, 1]); nan
        until enough sessions exist.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(atm, ("underlying", "trade_date", "atm_iv"), "atm")
    work = _by_underlying(atm[["underlying", "trade_date", "atm_iv"]])
    work["trade_date"] = pd.to_datetime(work["trade_date"]).astype("datetime64[ns]")
    iv = work["atm_iv"].astype("float64")
    work["atm_iv_change_5"] = iv / iv.groupby(work["underlying"]).shift(IV_CHANGE_LAG) - 1.0
    rank = np.full(len(work), np.nan)
    positions = work.groupby("underlying", sort=False).indices
    for index in positions.values():
        values = iv.to_numpy(dtype=np.float64)[index]
        if values.shape[0] < IV_RANK_WINDOW:
            continue
        windows = np.lib.stride_tricks.sliding_window_view(values, IV_RANK_WINDOW)
        below = (windows[:, :-1] < windows[:, -1:]).sum(axis=1)
        rank[index[IV_RANK_WINDOW - 1 :]] = below / (IV_RANK_WINDOW - 1)
    work["iv_rank_120"] = rank
    return work


def regime_features(
    daily: pd.DataFrame, atm: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """Join the return and IV features on ``(underlying, trade_date)``.

    Args:
        daily: Rows for ``return_features``.
        atm: Rows for ``iv_features`` (the output of ``atm_iv`` over every session).
        config: Analytics parameters.

    Returns:
        Rows with ``REGIME_COLUMNS`` (outer join, nan where a side is missing), sorted.
    """
    joined = return_features(daily, config).merge(
        iv_features(atm), on=["underlying", "trade_date"], how="outer"
    )
    return _by_underlying(joined)[list(REGIME_COLUMNS)]


# --- selection -------------------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedTrades:
    """Guarded trades with their regime features and one sort order per ranking.

    Attributes:
        frame: Settled trades that pass every entry guard, with the regime columns, on a
            default index.
        orders: Per ranking, row positions sorted by session, score (best first, nan last)
            and ``rank_entry``.
        session: Session code per row, increasing with ``trade_date``.
        group: Code of ``(trade_date, underlying, expiration)`` per row.
    """

    frame: pd.DataFrame
    orders: Mapping[str, IntArray]
    session: IntArray
    group: IntArray

    def column(self, name: str) -> FloatArray:
        """Return a column as float64."""
        return _floats(self.frame, name)


def prepare(trades: pd.DataFrame, regime: pd.DataFrame) -> PreparedTrades:
    """Keep the guarded trades, attach the regime features and sort once per ranking.

    Args:
        trades: Settled trades with ``SETTLED_COLUMNS`` (the scored-spread cache).
        regime: Rows with ``REGIME_COLUMNS``.

    Returns:
        The prepared trades.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(trades, SETTLED_COLUMNS, "trades")
    require_columns(regime, REGIME_COLUMNS, "regime")
    guarded = trades.loc[trades["rank_entry"].notna()].copy()
    guarded["trade_date"] = pd.to_datetime(guarded["trade_date"]).astype("datetime64[ns]")
    features = regime[list(REGIME_COLUMNS)].copy()
    features["trade_date"] = pd.to_datetime(features["trade_date"]).astype("datetime64[ns]")
    features = features.drop_duplicates(["underlying", "trade_date"])
    frame = guarded.merge(features, on=["underlying", "trade_date"], how="left")
    frame = frame.reset_index(drop=True)
    session = np.unique(frame["trade_date"].to_numpy(), return_inverse=True)[1].astype(np.int64)
    group_key = (
        frame["trade_date"].astype(str)
        + "|"
        + frame["underlying"].astype(str)
        + "|"
        + frame["expiration"].astype(str)
    )
    group = np.unique(group_key.to_numpy(dtype=str), return_inverse=True)[1].astype(np.int64)
    tie = frame["rank_entry"].astype("float64").to_numpy(dtype=np.float64)
    orders: dict[str, IntArray] = {}
    for rank_by in RANK_BYS:
        score = rank_score(frame, rank_by)
        score = np.where(np.isnan(score), -np.inf, score)
        orders[rank_by] = np.lexsort((tie, -score, session)).astype(np.int64)
    return PreparedTrades(frame=frame, orders=orders, session=session, group=group)


def _gate(prepared: PreparedTrades, rule: Rule) -> BoolArray:
    """Return the rows that pass the rule's DTE, moneyness, regime and edge gates."""
    frame = prepared.frame
    mask = np.ones(len(frame), dtype=np.bool_)
    if rule.dte_band is not None:
        dte = prepared.column("dte_days")
        mask &= (dte >= rule.dte_band[0]) & (dte < rule.dte_band[1])
    if rule.moneyness_band is not None:
        money = prepared.column("short_moneyness")
        mask &= (money >= rule.moneyness_band[0]) & (money < rule.moneyness_band[1])
    if rule.regime in ("trend_up", "trend_up_calm"):
        mask &= prepared.column("ret_20") > 0
    if rule.regime in ("calm", "trend_up_calm"):
        mask &= prepared.column("atm_iv_change_5") < CALM_MAX_IV_CHANGE
    if rule.regime == "high_iv_rank":
        mask &= prepared.column("iv_rank_120") >= HIGH_IV_RANK
    natural = prepared.column("credit_natural")
    mask &= natural >= (1.0 + rule.natural_edge_margin) * prepared.column("fair_credit")
    return mask


def _within_session_rank(session: IntArray) -> IntArray:
    """Return 0, 1, 2, ... within each run of equal, sorted session codes."""
    n = session.shape[0]
    index = np.arange(n, dtype=np.int64)
    if n == 0:
        return index
    start = np.concatenate([[True], session[1:] != session[:-1]])
    first = np.maximum.accumulate(np.where(start, index, 0))
    return np.asarray(index - first, dtype=np.int64)


def select_positions(prepared: PreparedTrades, rule: Rule) -> IntArray:
    """Apply a rule: gates, ranking, diversification, then the top ``N`` per session.

    Args:
        prepared: Output of ``prepare``.
        rule: The rule.

    Returns:
        Row positions of ``prepared.frame``, by session and best first within a session.
    """
    mask = _gate(prepared, rule)
    order = prepared.orders[rule.rank_by]
    chosen = order[mask[order]]
    if rule.one_per_underlying_expiry and chosen.shape[0]:
        first = np.unique(prepared.group[chosen], return_index=True)[1]
        chosen = chosen[np.sort(first)]
    keep = _within_session_rank(prepared.session[chosen]) < rule.top_n
    return np.asarray(chosen[keep], dtype=np.int64)


def apply_rule(trades: pd.DataFrame, regime: pd.DataFrame, rule: Rule) -> pd.DataFrame:
    """Select the trades of one rule from scored, settled spreads.

    Args:
        trades: Settled trades with ``SETTLED_COLUMNS`` (any number of sessions).
        regime: Rows with ``REGIME_COLUMNS``.
        rule: The rule.

    Returns:
        The selected rows with the regime columns, by session and best first.
    """
    prepared = prepare(trades, regime)
    return prepared.frame.iloc[select_positions(prepared, rule)].reset_index(drop=True)


# --- evaluation ------------------------------------------------------------------------------


def _session_drawdown(session: IntArray, returns: FloatArray) -> float:
    """Return the largest drawdown with one dollar per session split across its trades.

    Args:
        session: Session codes of the trades, any order.
        returns: Realised returns on max loss of the same trades.

    Returns:
        Maximum fall of the cumulative per-session mean return below its running peak
        (starting from 0), in dollars per dollar of maximum loss; nan with no trade.
    """
    if session.shape[0] == 0:
        return math.nan
    codes, inverse = np.unique(session, return_inverse=True)
    sums = np.bincount(inverse, weights=returns, minlength=codes.shape[0])
    counts = np.bincount(inverse, minlength=codes.shape[0])
    cumulative = np.cumsum(sums / counts)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cumulative]))[1:]
    return float(np.max(peak - cumulative))


def _period_metrics(
    prepared: PreparedTrades, rows: IntArray, *, with_ci: bool, config: AnalyticsConfig
) -> dict[str, float]:
    """Compute ``LAB_METRICS`` (and optionally the interval) for some rows."""
    frame = prepared.frame
    n = rows.shape[0]
    values: dict[str, float] = dict.fromkeys(LAB_METRICS, math.nan)
    values["n_trades"] = float(n)
    values["n_sessions"] = float(np.unique(prepared.session[rows]).shape[0])
    if with_ci:
        values["mean_realised_return_ci_low"] = math.nan
        values["mean_realised_return_ci_high"] = math.nan
    if n == 0:
        return values
    realised = prepared.column("realised_return")[rows]
    std = float(np.std(realised, ddof=1)) if n >= 2 else 0.0
    values.update(
        {
            "win_rate": float(frame["win"].to_numpy(dtype=np.bool_)[rows].mean()),
            "mean_predicted_pop": float(prepared.column("prob_profit")[rows].mean()),
            "mean_realised_return": float(realised.mean()),
            "total_return": float(
                prepared.column("realised_payoff")[rows].sum()
                / prepared.column("max_loss_natural")[rows].sum()
            ),
            "sharpe_per_trade": float(realised.mean()) / std if std > 0 else math.nan,
            "max_drawdown": _session_drawdown(prepared.session[rows], realised),
            "max_loss_rate": float(frame["max_loss_hit"].to_numpy(dtype=np.bool_)[rows].mean()),
        }
    )
    if with_ci:
        low, high = cluster_bootstrap_ci(
            realised,
            frame["expiration"].to_numpy()[rows],
            resamples=config.bootstrap_resamples,
            seed=config.bootstrap_seed,
        )
        values["mean_realised_return_ci_low"] = low
        values["mean_realised_return_ci_high"] = high
    return values


def evaluate_positions(
    prepared: PreparedTrades,
    positions: IntArray,
    *,
    dev_years: Collection[int],
    holdout_years: Collection[int],
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict[str, dict[str, float]]:
    """Evaluate selected rows by period; see ``evaluate``."""
    if set(dev_years) & set(holdout_years):
        raise ValueError("dev_years and holdout_years must not overlap")
    frame = prepared.frame
    year = frame["trade_date"].dt.year.to_numpy(dtype=np.int64)[positions]
    oos = frame["is_out_of_sample"].to_numpy(dtype=np.bool_)[positions]
    out: dict[str, dict[str, float]] = {}
    for period, years in zip(PERIODS, (dev_years, holdout_years), strict=True):
        inside = oos & np.isin(year, np.asarray(sorted(years), dtype=np.int64))
        out[period] = _period_metrics(
            prepared, positions[inside], with_ci=period == "holdout", config=config
        )
    return out


def evaluate(
    prepared: PreparedTrades,
    rule: Rule,
    *,
    dev_years: Collection[int],
    holdout_years: Collection[int],
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict[str, dict[str, float]]:
    """Apply a rule and measure its out-of-sample trades in the dev and hold-out periods.

    A trade belongs to the period of its trade date's calendar year; trades that are not
    out of sample (burn-in or an identity map) are ignored.

    Args:
        prepared: Output of ``prepare``.
        rule: The rule.
        dev_years: Calendar years of the development period.
        holdout_years: Calendar years of the hold-out, disjoint from ``dev_years``.
        config: Bootstrap size and seed.

    Returns:
        ``{"dev": metrics, "holdout": metrics}`` with ``LAB_METRICS`` (counts as floats; nan
        where undefined); the hold-out adds ``mean_realised_return_ci_low`` and ``_ci_high``.

    Raises:
        ValueError: If the periods overlap.
    """
    return evaluate_positions(
        prepared,
        select_positions(prepared, rule),
        dev_years=dev_years,
        holdout_years=holdout_years,
        config=config,
    )


def flatten(metrics: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
    """Flatten ``evaluate`` output to ``<metric>_<period>`` keys."""
    return {f"{name}_{period}": value for period, m in metrics.items() for name, value in m.items()}


def rule_fields(rule: Rule) -> dict[str, object]:
    """Return the rule's identifier and fields as flat, CSV-friendly values."""
    band = rule.moneyness_band
    return {
        "rule_id": rule.rule_id,
        "rank_by": rule.rank_by,
        "dte_band": "" if rule.dte_band is None else f"{rule.dte_band[0]}-{rule.dte_band[1]}",
        "moneyness_band": "" if band is None else f"{band[0]:.2f}-{band[1]:.2f}",
        "one_per_underlying_expiry": rule.one_per_underlying_expiry,
        "regime": rule.regime,
        "natural_edge_margin": rule.natural_edge_margin,
        "top_n": rule.top_n,
    }


# --- choosing rules --------------------------------------------------------------------------


@dataclass(frozen=True)
class Picks:
    """The protocol's choices from a sweep.

    Attributes:
        qualified: Rules with at least the minimum dev trades and a finite dev drawdown,
            sorted by dev Sharpe (best first, ties by ``rule_id``).
        best_overall: ``rule_id`` with the best dev Sharpe, or None if none qualifies.
        best_roi: ``rule_id`` with the best dev mean realised return among qualified rules
            whose dev drawdown is below ``drawdown_median``, or None.
        drawdown_median: Median dev drawdown of every rule with a finite one.
        beat_dev: Qualified rules (baseline excluded) with a higher dev Sharpe than the
            baseline.
        beat_both: Of those, how many also have a higher hold-out Sharpe.
        median_rule: ``rule_id`` at the median dev-Sharpe position, or None.
    """

    qualified: pd.DataFrame
    best_overall: str | None
    best_roi: str | None
    drawdown_median: float
    beat_dev: int
    beat_both: int
    median_rule: str | None


def pick_rules(results: pd.DataFrame, *, baseline_id: str, min_dev_trades: int) -> Picks:
    """Apply the selection protocol to sweep results; only dev metrics choose.

    Args:
        results: One row per rule with ``rule_id`` and the ``flatten`` columns.
        baseline_id: ``rule_id`` of the baseline.
        min_dev_trades: Fewest dev trades a rule needs to be ranked.

    Returns:
        The picks.

    Raises:
        ValueError: If a column is missing or the baseline is absent.
    """
    require_columns(
        results,
        (
            "rule_id",
            "n_trades_dev",
            "max_drawdown_dev",
            "sharpe_per_trade_dev",
            "mean_realised_return_dev",
            "sharpe_per_trade_holdout",
        ),
        "results",
    )
    base = results.loc[results["rule_id"] == baseline_id]
    if base.empty:
        raise ValueError("the baseline is not in the results")
    drawdown = results["max_drawdown_dev"].astype("float64")
    finite = np.isfinite(drawdown.to_numpy(dtype=np.float64))
    median = float(drawdown[finite].median()) if finite.any() else math.nan
    ok = (results["n_trades_dev"].astype("float64") >= min_dev_trades).to_numpy() & finite
    qualified = results.loc[ok].copy()
    qualified["_sharpe"] = qualified["sharpe_per_trade_dev"].astype("float64").fillna(-np.inf)
    qualified = qualified.sort_values(
        ["_sharpe", "rule_id"], ascending=[False, True], kind="stable"
    ).drop(columns="_sharpe")
    qualified = qualified.reset_index(drop=True)
    best_overall = str(qualified["rule_id"].iloc[0]) if not qualified.empty else None
    low_dd = qualified.loc[qualified["max_drawdown_dev"].astype("float64") < median]
    best_roi = None
    if not low_dd.empty:
        roi = low_dd.assign(_roi=low_dd["mean_realised_return_dev"].astype("float64"))
        roi = roi.sort_values(["_roi", "rule_id"], ascending=[False, True], kind="stable")
        best_roi = str(roi["rule_id"].iloc[0])
    base_dev = float(base["sharpe_per_trade_dev"].iloc[0])
    base_hold = float(base["sharpe_per_trade_holdout"].iloc[0])
    others = qualified.loc[qualified["rule_id"] != baseline_id]
    beat = others.loc[others["sharpe_per_trade_dev"].astype("float64") > base_dev]
    beat_both = int((beat["sharpe_per_trade_holdout"].astype("float64") > base_hold).sum())
    median_rule = (
        str(qualified["rule_id"].iloc[(len(qualified) - 1) // 2]) if not qualified.empty else None
    )
    return Picks(
        qualified=qualified,
        best_overall=best_overall,
        best_roi=best_roi,
        drawdown_median=median,
        beat_dev=len(beat),
        beat_both=beat_both,
        median_rule=median_rule,
    )
