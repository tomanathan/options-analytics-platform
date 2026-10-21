"""Growth lab rules: pick single long options by growth rate, size them, measure the growth.

The input is every scored, settled option of ``oap.analytics.growth`` (the scored-option
cache). A ``GrowthRule`` is a selection over those rows, applied one session at a time:
gates (right, days to expiry, strike over close, regime, minimum probability of profit),
a ranking (higher first, nan last, ties broken by the cache order), an optional
one-option-per-underlying-and-expiry diversification, then the top ``N`` per session. Only
out-of-sample rows are ever selected.

Rankings: ``growth_rate`` (the calibrated growth-optimal log growth ``g*``), ``growth_gap``
(calibrated minus market ``g*``, the mispricing in growth terms) and ``expected_return``
(``E[R]`` on premium).

Regime gates on the underlying's features of the trade date (a missing feature fails the
gate): ``calm`` (``atm_iv_change_5`` below the rule lab's ``CALM_MAX_IV_CHANGE``),
``trend_up`` (``ret_20`` above 0), ``high_iv_rank`` and ``low_iv_rank`` (``iv_rank_120`` in
the step-1 ``high`` and ``low`` buckets: at least 2/3, below 1/3).

Sizing. The session's picks get weights ``w_i``, fractions of equity: ``equal`` splits
``F_MAX`` equally across them; ``kelly`` gives each its ``kelly_fraction`` and scales the
session down so the weights sum to at most ``F_MAX``. A pick with ``kelly_fraction`` 0 is
not staked under ``kelly`` and is not a trade. Two equity lines start at one dollar and book
each session at its trade date:

* the bet line grows by ``1 + sum(w_i R_i)`` per session: each session's picks as one bet,
  as if no other were open. Its mean log growth per session is the realised counterpart of
  the growth rate ``g*`` and is the headline, but its compounded total is not an account,
  because the options are held for weeks and the sessions overlap;
* the ladder line grows by ``1 + sum(w_i R_i / h_i)``, with ``h_i`` the sessions from the
  trade date to the option's expiry (at least 1): each pick's stake is spread over the
  sessions it is open, so the equity committed averages about ``F_MAX``. Its total growth
  and drawdown approximate a feasible account (still booked at the trade date).

Per period (dev and hold-out, by the trade date's calendar year): trades, win rate (share
with ``R > 0``), mean ``R``, mean predicted probability of profit, mean tail share, the bet
line's mean log growth per session over every session of the period (a session without a
trade grows by 0) and the Sharpe ratio of its session returns, the ladder line's mean log
growth per session, total growth ``V_end - 1`` and largest drawdown below its running peak
(a share of the peak), and a 95% cluster-bootstrap interval for mean ``R`` by expiration
date.

Units: returns on premium as decimals; weights, growth and drawdowns as decimals of equity;
log growth in nats per session; probabilities as decimals; ``dte_days`` in calendar days;
moneyness is strike over close.
"""

import itertools
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

from oap.analytics.backtest import cluster_bootstrap_ci
from oap.analytics.config import DEFAULT_CONFIG, AnalyticsConfig
from oap.analytics.growth import F_MAX
from oap.analytics.regime_calibration import IV_RANK_EDGES
from oap.analytics.rulelab import CALM_MAX_IV_CHANGE
from oap.analytics.sample import require_columns
from oap.engine._types import BoolArray, FloatArray

RankBy = Literal["growth_rate", "growth_gap", "expected_return"]
RightFilter = Literal["call", "put", "both"]
RegimeGate = Literal["any", "calm", "trend_up", "high_iv_rank", "low_iv_rank"]
Sizing = Literal["equal", "kelly"]
DteBand = tuple[int, int]
MoneynessBand = tuple[float, float]
IntArray = npt.NDArray[np.int64]

RANK_BYS: Final[tuple[RankBy, ...]] = ("growth_rate", "growth_gap", "expected_return")
RIGHTS: Final[tuple[RightFilter, ...]] = ("call", "put", "both")
DTE_BANDS: Final[tuple[DteBand | None, ...]] = (None, (7, 21), (21, 45), (45, 70))
"""Days-to-expiry bands, ``lo <= dte_days < hi`` in calendar days."""
MONEYNESS_BANDS: Final[tuple[MoneynessBand | None, ...]] = (
    None,
    (0.90, 0.97),
    (0.97, 1.03),
    (1.03, 1.10),
)
"""Strike over close bands, ``lo <= moneyness < hi``."""
REGIME_GATES: Final[tuple[RegimeGate, ...]] = (
    "any",
    "calm",
    "trend_up",
    "high_iv_rank",
    "low_iv_rank",
)
MIN_PROBS: Final[tuple[float, ...]] = (0.0, 0.25, 0.40)
"""Smallest calibrated probability of profit, decimals."""
TOP_NS: Final[tuple[int, ...]] = (3, 5, 10)
SIZINGS: Final[tuple[Sizing, ...]] = ("equal", "kelly")
PERIODS: Final[tuple[str, ...]] = ("dev", "holdout")

VARIANT_COLUMNS: Final[tuple[str, ...]] = (
    "prob_profit",
    "expected_return",
    "kelly_fraction",
    "growth_rate",
    "growth_gap",
)
"""Columns read with a suffix when a rule is evaluated on another map's scores."""
OPTION_COLUMNS: Final[tuple[str, ...]] = (
    "underlying",
    "trade_date",
    "expiration",
    "dte_days",
    "right",
    "moneyness",
    "is_out_of_sample",
    "ret_20",
    "iv_rank_120",
    "atm_iv_change_5",
    "realised_return",
    "tail_share",
    *VARIANT_COLUMNS,
)
"""Columns of the scored-option cache that the rules read."""

METRICS: Final[tuple[str, ...]] = (
    "n_trades",
    "n_sessions",
    "n_sessions_traded",
    "win_rate",
    "mean_return",
    "mean_predicted_pop",
    "mean_tail_share",
    "growth_per_session",
    "sharpe_per_session",
    "ladder_growth_per_session",
    "ladder_total_growth",
    "ladder_max_drawdown",
    "mean_return_ci_low",
    "mean_return_ci_high",
)
"""Metrics of every period; counts are floats, and every value is nan where undefined."""

_RANK_CODES: Final[dict[str, str]] = {
    "growth_rate": "gr",
    "growth_gap": "gg",
    "expected_return": "er",
}
_REGIME_CODES: Final[dict[str, str]] = {
    "any": "any",
    "calm": "calm",
    "trend_up": "up",
    "high_iv_rank": "ivh",
    "low_iv_rank": "ivl",
}
_RANK_WORDS: Final[dict[str, str]] = {
    "growth_rate": "the calibrated growth-optimal log growth",
    "growth_gap": "calibrated minus market growth-optimal log growth",
    "expected_return": "the calibrated expected return on premium",
}
_REGIME_WORDS: Final[dict[str, str]] = {
    "calm": "only when the near-the-money IV rose less than 20% over 5 sessions",
    "trend_up": "only when the underlying's 20-session return is positive",
    "high_iv_rank": "only when the 120-session IV rank is at least 2/3",
    "low_iv_rank": "only when the 120-session IV rank is below 1/3",
}


def _percent_code(value: float) -> str:
    """Format a decimal as a compact whole-percent code, such as ``0.97`` to ``97``."""
    return f"{round(value * 100, 4):g}"


@dataclass(frozen=True)
class GrowthRule:
    """A selection and sizing rule for single long options, applied per session.

    Attributes:
        rank_by: The ranking; see the module docstring.
        right: ``call``, ``put`` or ``both``.
        dte_band: ``(lo, hi)`` calendar days, keeping ``lo <= dte_days < hi``; None keeps all.
        moneyness_band: ``(lo, hi)`` strike over close, keeping ``lo <= moneyness < hi``;
            None keeps all.
        regime: Regime gate on the underlying's features of the trade date.
        one_per_underlying_expiry: Keep only the best-ranked option of each underlying and
            expiration before taking the top ``N``.
        min_prob_profit: Smallest calibrated probability of profit, a decimal in [0, 1].
        top_n: Options per session, at least 1.
        sizing: ``equal`` or ``kelly``.
    """

    rank_by: RankBy = "growth_rate"
    right: RightFilter = "both"
    dte_band: DteBand | None = None
    moneyness_band: MoneynessBand | None = None
    regime: RegimeGate = "any"
    one_per_underlying_expiry: bool = False
    min_prob_profit: float = 0.0
    top_n: int = 10
    sizing: Sizing = "equal"

    def __post_init__(self) -> None:
        """Validate the fields.

        Raises:
            ValueError: If a field is outside its domain.
        """
        if self.rank_by not in RANK_BYS:
            raise ValueError(f"unknown rank_by {self.rank_by!r}")
        if self.right not in RIGHTS:
            raise ValueError(f"unknown right {self.right!r}")
        if self.regime not in REGIME_GATES:
            raise ValueError(f"unknown regime {self.regime!r}")
        if self.sizing not in SIZINGS:
            raise ValueError(f"unknown sizing {self.sizing!r}")
        for band in (self.dte_band, self.moneyness_band):
            if band is not None and not band[0] < band[1]:
                raise ValueError("a band must have lo < hi")
        if not 0.0 <= self.min_prob_profit <= 1.0:
            raise ValueError("min_prob_profit must be in [0, 1]")
        if self.top_n < 1:
            raise ValueError("top_n must be at least 1")

    @property
    def rule_id(self) -> str:
        """Return a short identifier that depends only on the fields.

        Returns:
            Such as ``gr-put-d21_45-m97_103-calm-one-p25-n5-kelly``.
        """
        dte = "dany" if self.dte_band is None else f"d{self.dte_band[0]}_{self.dte_band[1]}"
        band = self.moneyness_band
        money = "many" if band is None else f"m{_percent_code(band[0])}_{_percent_code(band[1])}"
        return "-".join(
            (
                _RANK_CODES[self.rank_by],
                self.right,
                dte,
                money,
                _REGIME_CODES[self.regime],
                "one" if self.one_per_underlying_expiry else "all",
                f"p{_percent_code(self.min_prob_profit)}",
                f"n{self.top_n}",
                "eq" if self.sizing == "equal" else "kelly",
            )
        )


def describe_rule(rule: GrowthRule) -> str:
    """State a rule in words.

    Args:
        rule: The rule.

    Returns:
        One sentence.
    """
    rights = {"call": "calls only", "put": "puts only", "both": "calls and puts"}
    parts = [f"Rank by {_RANK_WORDS[rule.rank_by]}", rights[rule.right]]
    if rule.dte_band is not None:
        parts.append(f"{rule.dte_band[0]} to {rule.dte_band[1] - 1} days to expiry")
    if rule.moneyness_band is not None:
        lo, hi = rule.moneyness_band
        parts.append(f"strike from {lo:.0%} to below {hi:.0%} of the close")
    if rule.regime != "any":
        parts.append(_REGIME_WORDS[rule.regime])
    if rule.one_per_underlying_expiry:
        parts.append("at most one option per underlying and expiry")
    if rule.min_prob_profit > 0:
        parts.append(f"calibrated probability of profit at least {rule.min_prob_profit:.0%}")
    sizing = (
        f"{F_MAX:.0%} of equity split equally"
        if rule.sizing == "equal"
        else f"each at its growth-optimal fraction, at most {F_MAX:.0%} of equity in all"
    )
    parts.append(f"top {rule.top_n} per session, {sizing}")
    return "; ".join(parts) + "."


def rule_grid() -> tuple[GrowthRule, ...]:
    """Return the full factorial grid of rules.

    Returns:
        ``3 * 3 * 4 * 4 * 5 * 2 * 3 * 3 * 2`` rules (25,920), the last field varying
        fastest, in the order ``rank_by``, right, DTE band, moneyness band, regime,
        diversification, minimum probability, top ``N``, sizing.
    """
    return tuple(
        GrowthRule(
            rank_by=rank_by,
            right=right,
            dte_band=dte,
            moneyness_band=money,
            regime=regime,
            one_per_underlying_expiry=one,
            min_prob_profit=prob,
            top_n=top_n,
            sizing=sizing,
        )
        for rank_by, right, dte, money, regime, one, prob, top_n, sizing in itertools.product(
            RANK_BYS,
            RIGHTS,
            DTE_BANDS,
            MONEYNESS_BANDS,
            REGIME_GATES,
            (False, True),
            MIN_PROBS,
            TOP_NS,
            SIZINGS,
        )
    )


def rule_fields(rule: GrowthRule) -> dict[str, object]:
    """Return the rule's identifier and fields as flat, CSV-friendly values."""
    band = rule.moneyness_band
    return {
        "rule_id": rule.rule_id,
        "rank_by": rule.rank_by,
        "right": rule.right,
        "dte_band": "" if rule.dte_band is None else f"{rule.dte_band[0]}-{rule.dte_band[1]}",
        "moneyness_band": "" if band is None else f"{band[0]:.2f}-{band[1]:.2f}",
        "regime": rule.regime,
        "one_per_underlying_expiry": rule.one_per_underlying_expiry,
        "min_prob_profit": rule.min_prob_profit,
        "top_n": rule.top_n,
        "sizing": rule.sizing,
    }


# --- preparation and selection ---------------------------------------------------------------


def _floats(frame: pd.DataFrame, column: str) -> FloatArray:
    """Return a column as a float64 array (nan for missing)."""
    return np.asarray(frame[column].to_numpy(dtype=np.float64, na_value=np.nan), dtype=np.float64)


@dataclass(frozen=True, eq=False)
class PreparedOptions:
    """Out-of-sample scored options, sorted once, with per-ranking orders.

    Attributes:
        frame: The rows, sorted by trade date, underlying, expiration, right and strike, on
            a default index (the tie-break order).
        suffix: Column suffix of the map-dependent columns the rankings and gates read.
        orders: Per ranking, row positions sorted by session, score (best first, nan last)
            and row position.
        session: Session code per row, increasing with the trade date.
        group: Code of ``(trade_date, underlying, expiration)`` per row.
        session_dates: Trade date of each session code.
        hold: Sessions from each row's trade date to its expiry, at least 1: the count of
            session dates on or after the trade date and before the expiration.
    """

    frame: pd.DataFrame
    suffix: str
    orders: Mapping[str, IntArray]
    session: IntArray
    group: IntArray
    session_dates: pd.DatetimeIndex
    hold: IntArray
    _cache: dict[str, FloatArray] = field(default_factory=dict, repr=False)

    def column(self, name: str) -> FloatArray:
        """Return a column as float64, reading ``<name><suffix>`` for map-dependent columns."""
        key = f"{name}{self.suffix}" if name in VARIANT_COLUMNS else name
        if key not in self._cache:
            self._cache[key] = _floats(self.frame, key)
        return self._cache[key]


def _holding_sessions(
    dates: npt.NDArray[np.datetime64], session: IntArray, expiration: npt.NDArray[np.datetime64]
) -> IntArray:
    """Return the sessions each row is open: dates from its own up to, not including, expiry."""
    later = np.searchsorted(dates, expiration, side="left")
    return np.asarray(np.maximum(later - session, 1), dtype=np.int64)


def prepare(options: pd.DataFrame, *, suffix: str = "") -> PreparedOptions:
    """Keep the out-of-sample options, sort them and order them once per ranking.

    Args:
        options: Scored, settled options with ``OPTION_COLUMNS`` (and the suffixed
            map-dependent columns when ``suffix`` is given), in any order.
        suffix: ``""`` for the chosen map's scores, or ``"_pooled"`` for the pooled map's.

    Returns:
        The prepared options.

    Raises:
        ValueError: If a column is missing.
    """
    needed = (*OPTION_COLUMNS, *(f"{c}{suffix}" for c in VARIANT_COLUMNS if suffix))
    require_columns(options, tuple(dict.fromkeys(needed)), "options")
    frame = options.loc[options["is_out_of_sample"].astype(bool)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).astype("datetime64[ns]")
    frame["expiration"] = pd.to_datetime(frame["expiration"]).astype("datetime64[ns]")
    sort = ["trade_date", "underlying", "expiration", "right"]
    if "strike" in frame.columns:
        sort.append("strike")
    frame = frame.sort_values(sort, kind="stable").reset_index(drop=True)
    dates, session = np.unique(frame["trade_date"].to_numpy(), return_inverse=True)
    session = np.asarray(session, dtype=np.int64).reshape(-1)
    group = frame.groupby(["trade_date", "underlying", "expiration"], sort=False).ngroup()
    cache: dict[str, FloatArray] = {}
    tie = np.arange(len(frame), dtype=np.int64)
    orders: dict[str, IntArray] = {}
    for rank_by in RANK_BYS:
        score = _floats(frame, f"{rank_by}{suffix}")
        cache[f"{rank_by}{suffix}"] = score
        ranked = np.where(np.isnan(score), -np.inf, score)
        orders[rank_by] = np.lexsort((tie, -ranked, session)).astype(np.int64)
    return PreparedOptions(
        frame=frame,
        suffix=suffix,
        orders=orders,
        session=session,
        group=np.asarray(group.to_numpy(), dtype=np.int64),
        session_dates=pd.DatetimeIndex(dates),
        hold=_holding_sessions(dates, session, frame["expiration"].to_numpy()),
        _cache=cache,
    )


def gate_mask(prepared: PreparedOptions, rule: GrowthRule) -> BoolArray:
    """Return the rows that pass the rule's right, DTE, moneyness, regime and POP gates."""
    frame = prepared.frame
    mask = np.ones(len(frame), dtype=np.bool_)
    if rule.right != "both":
        mask &= (frame["right"] == rule.right).to_numpy(dtype=np.bool_)
    if rule.dte_band is not None:
        dte = prepared.column("dte_days")
        mask &= (dte >= rule.dte_band[0]) & (dte < rule.dte_band[1])
    if rule.moneyness_band is not None:
        money = prepared.column("moneyness")
        mask &= (money >= rule.moneyness_band[0]) & (money < rule.moneyness_band[1])
    if rule.regime == "calm":
        mask &= prepared.column("atm_iv_change_5") < CALM_MAX_IV_CHANGE
    elif rule.regime == "trend_up":
        mask &= prepared.column("ret_20") > 0.0
    elif rule.regime == "high_iv_rank":
        mask &= prepared.column("iv_rank_120") >= IV_RANK_EDGES[1]
    elif rule.regime == "low_iv_rank":
        mask &= prepared.column("iv_rank_120") < IV_RANK_EDGES[0]
    if rule.min_prob_profit > 0.0:
        mask &= prepared.column("prob_profit") >= rule.min_prob_profit
    return mask


def within_session_rank(session: IntArray) -> IntArray:
    """Return 0, 1, 2, ... within each run of equal, sorted session codes."""
    n = session.shape[0]
    index = np.arange(n, dtype=np.int64)
    if n == 0:
        return index
    start = np.concatenate([[True], session[1:] != session[:-1]])
    first = np.maximum.accumulate(np.where(start, index, 0))
    return np.asarray(index - first, dtype=np.int64)


def ranked_positions(prepared: PreparedOptions, rule: GrowthRule) -> tuple[IntArray, IntArray]:
    """Apply the gates, the ranking and the diversification, before the top ``N``.

    Args:
        prepared: Output of ``prepare``.
        rule: The rule; its ``top_n`` and ``sizing`` are ignored.

    Returns:
        Row positions by session and best first, and each one's rank within its session
        (0 is the best), so any top ``N`` is ``positions[rank < N]``.
    """
    mask = gate_mask(prepared, rule)
    order = prepared.orders[rule.rank_by]
    chosen = order[mask[order]]
    if rule.one_per_underlying_expiry and chosen.shape[0]:
        first = np.unique(prepared.group[chosen], return_index=True)[1]
        chosen = chosen[np.sort(first)]
    return np.asarray(chosen, dtype=np.int64), within_session_rank(prepared.session[chosen])


def select_positions(prepared: PreparedOptions, rule: GrowthRule) -> IntArray:
    """Apply a rule: gates, ranking, diversification, then the top ``N`` per session.

    Args:
        prepared: Output of ``prepare``.
        rule: The rule.

    Returns:
        Row positions of ``prepared.frame``, by session and best first within a session.
    """
    chosen, rank = ranked_positions(prepared, rule)
    return np.asarray(chosen[rank < rule.top_n], dtype=np.int64)


def random_positions(
    prepared: PreparedOptions, *, top_n: int, seed: int, eligible: BoolArray | None = None
) -> IntArray:
    """Pick ``top_n`` options per session uniformly at random, the equal-weight baseline.

    Args:
        prepared: Output of ``prepare``.
        top_n: Options per session, at least 1.
        seed: Seed of ``numpy.random.default_rng``; the result is deterministic.
        eligible: Rows that may be drawn, such as the calls; None for every row.

    Returns:
        Row positions by session.

    Raises:
        ValueError: If ``top_n`` is below 1.
    """
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    rng = np.random.default_rng(seed)
    order = np.lexsort((rng.random(len(prepared.frame)), prepared.session))
    if eligible is not None:
        order = order[eligible[order]]
    keep = within_session_rank(prepared.session[order]) < top_n
    return np.asarray(order[keep], dtype=np.int64)


# --- sizing and evaluation -------------------------------------------------------------------


def session_weights(
    session: IntArray, kelly: FloatArray, sizing: Sizing, *, f_max: float = F_MAX
) -> FloatArray:
    """Return each pick's fraction of the session's equity.

    Args:
        session: Session code of each pick.
        kelly: ``kelly_fraction`` of each pick, decimals in ``[0, f_max]``.
        sizing: ``equal`` (``f_max`` split equally across the session's picks) or ``kelly``
            (each its ``kelly_fraction``, scaled down so the session sums to at most
            ``f_max``).
        f_max: Largest share of equity per session, a decimal.

    Returns:
        Weights as decimals of equity, aligned with ``session``.
    """
    if session.shape[0] == 0:
        return np.zeros(0)
    codes, inverse = np.unique(session, return_inverse=True)
    if sizing == "equal":
        counts = np.bincount(inverse, minlength=codes.shape[0]).astype(np.float64)
        return np.asarray(f_max / counts[inverse], dtype=np.float64)
    raw = np.clip(np.nan_to_num(kelly, nan=0.0), 0.0, None)
    totals = np.bincount(inverse, weights=raw, minlength=codes.shape[0])
    scale = np.where(totals > f_max, f_max / np.where(totals > 0, totals, 1.0), 1.0)
    return np.asarray(raw * scale[inverse], dtype=np.float64)


def equity_returns(
    n_sessions: int, session: IntArray, weights: FloatArray, returns: FloatArray
) -> FloatArray:
    """Return the equity line's return on every session, 0 where nothing was staked.

    Args:
        n_sessions: Number of sessions; codes run from 0.
        session: Session code of each pick.
        weights: Fractions of equity.
        returns: Realised returns on premium, at least -1.

    Returns:
        ``sum(w_i R_i)`` per session code, decimals of equity.
    """
    return np.asarray(
        np.bincount(session, weights=weights * returns, minlength=n_sessions), dtype=np.float64
    )


def line_metrics(session_returns: FloatArray) -> dict[str, float]:
    """Summarise an equity line from its per-session returns.

    Args:
        session_returns: Returns per session as decimals of equity, each above -1.

    Returns:
        ``growth_per_session`` (mean ``log(1 + r)``, nats), ``total_growth`` (``V_end - 1``),
        ``max_drawdown`` (largest fall below the running peak, a share of the peak, with the
        line starting at 1) and ``sharpe_per_session`` (mean over sample standard
        deviation, nan with fewer than two sessions or no spread).
    """
    out = dict.fromkeys(
        ("growth_per_session", "total_growth", "max_drawdown", "sharpe_per_session"), math.nan
    )
    n = session_returns.shape[0]
    if n == 0:
        return out
    logs = np.log1p(session_returns)
    path = np.cumsum(logs)
    peak = np.maximum.accumulate(np.concatenate([[0.0], path]))[1:]
    out["growth_per_session"] = float(logs.mean())
    out["total_growth"] = float(np.expm1(path[-1]))
    out["max_drawdown"] = max(0.0, float(-np.expm1(np.min(path - peak))))
    if n >= 2:
        std = float(np.std(session_returns, ddof=1))
        out["sharpe_per_session"] = float(session_returns.mean()) / std if std > 0 else math.nan
    return out


def period_sessions(prepared: PreparedOptions, years: Collection[int]) -> IntArray:
    """Return the session codes whose trade date falls in the given calendar years."""
    in_years = np.isin(prepared.session_dates.year, np.asarray(sorted(years), dtype=np.int64))
    return np.asarray(np.flatnonzero(in_years), dtype=np.int64)


def evaluate_positions(
    prepared: PreparedOptions,
    positions: IntArray,
    sizing: Sizing,
    *,
    dev_years: Collection[int],
    holdout_years: Collection[int],
    ci_min_dev_trades: int = 0,
    f_max: float = F_MAX,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict[str, dict[str, float]]:
    """Size selected options and measure them in the dev and hold-out periods.

    Args:
        prepared: Output of ``prepare``.
        positions: Selected row positions (any order).
        sizing: ``equal`` or ``kelly``.
        dev_years: Calendar years of the development period.
        holdout_years: Calendar years of the hold-out, disjoint from ``dev_years``.
        ci_min_dev_trades: Compute the bootstrap intervals of the mean return only when the
            dev period has at least this many trades (the sweep skips them for rules that
            cannot be ranked).
        f_max: Largest share of equity per session, a decimal.
        config: Bootstrap size and seed.

    Returns:
        ``{"dev": metrics, "holdout": metrics}`` with ``METRICS``.

    Raises:
        ValueError: If the periods overlap.
    """
    if set(dev_years) & set(holdout_years):
        raise ValueError("dev_years and holdout_years must not overlap")
    session = prepared.session[positions]
    kelly = prepared.column("kelly_fraction")[positions]
    weights = session_weights(session, kelly, sizing, f_max=f_max)
    returns = prepared.column("realised_return")[positions]
    n_sessions = prepared.session_dates.shape[0]
    bet = equity_returns(n_sessions, session, weights, returns)
    ladder = equity_returns(n_sessions, session, weights / prepared.hold[positions], returns)
    out: dict[str, dict[str, float]] = {}
    with_ci: bool | None = None
    for period, years in zip(PERIODS, (dev_years, holdout_years), strict=True):
        codes = period_sessions(prepared, years)
        inside = np.isin(session, codes) & (weights > 0.0)
        if with_ci is None:
            with_ci = int(inside.sum()) >= ci_min_dev_trades
        rows = positions[inside]
        values = dict.fromkeys(METRICS, math.nan)
        values["n_trades"] = float(rows.shape[0])
        values["n_sessions"] = float(codes.shape[0])
        values["n_sessions_traded"] = float(np.unique(session[inside]).shape[0])
        bet_line = line_metrics(bet[codes])
        ladder_line = line_metrics(ladder[codes])
        values["growth_per_session"] = bet_line["growth_per_session"]
        values["sharpe_per_session"] = bet_line["sharpe_per_session"]
        values["ladder_growth_per_session"] = ladder_line["growth_per_session"]
        values["ladder_total_growth"] = ladder_line["total_growth"]
        values["ladder_max_drawdown"] = ladder_line["max_drawdown"]
        if rows.shape[0]:
            realised = returns[inside]
            values["win_rate"] = float((realised > 0.0).mean())
            values["mean_return"] = float(realised.mean())
            values["mean_predicted_pop"] = float(prepared.column("prob_profit")[rows].mean())
            values["mean_tail_share"] = float(prepared.column("tail_share")[rows].mean())
            if with_ci:
                low, high = cluster_bootstrap_ci(
                    realised,
                    prepared.frame["expiration"].to_numpy()[rows],
                    resamples=config.bootstrap_resamples,
                    seed=config.bootstrap_seed,
                )
                values["mean_return_ci_low"], values["mean_return_ci_high"] = low, high
        out[period] = values
    return out


def evaluate(
    prepared: PreparedOptions,
    rule: GrowthRule,
    *,
    dev_years: Collection[int],
    holdout_years: Collection[int],
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> dict[str, dict[str, float]]:
    """Apply a rule and measure it; see ``evaluate_positions``."""
    return evaluate_positions(
        prepared,
        select_positions(prepared, rule),
        rule.sizing,
        dev_years=dev_years,
        holdout_years=holdout_years,
        config=config,
    )


def flatten(metrics: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
    """Flatten ``evaluate`` output to ``<metric>_<period>`` keys."""
    return {f"{name}_{period}": value for period, m in metrics.items() for name, value in m.items()}


def holdout_line(
    prepared: PreparedOptions, positions: IntArray, sizing: Sizing, holdout_years: Sequence[int]
) -> pd.DataFrame:
    """Return the hold-out ladder line of some selected options, starting at 1.

    Args:
        prepared: Output of ``prepare``.
        positions: Selected row positions.
        sizing: ``equal`` or ``kelly``.
        holdout_years: Calendar years of the hold-out.

    Returns:
        ``trade_date`` and ``equity`` (dollars per starting dollar) per hold-out session.
    """
    session = prepared.session[positions]
    weights = session_weights(session, prepared.column("kelly_fraction")[positions], sizing)
    weights = weights / prepared.hold[positions]
    returns = prepared.column("realised_return")[positions]
    line = equity_returns(prepared.session_dates.shape[0], session, weights, returns)
    codes = period_sessions(prepared, holdout_years)
    return pd.DataFrame(
        {
            "trade_date": prepared.session_dates[codes],
            "equity": np.exp(np.cumsum(np.log1p(line[codes]))),
        }
    )


# --- choosing rules --------------------------------------------------------------------------


@dataclass(frozen=True)
class Picks:
    """The protocol's choices from a sweep; only dev metrics choose.

    Attributes:
        qualified: Rules with at least the minimum dev trades and a finite dev growth,
            sorted by dev growth per session (best first, ties by ``rule_id``).
        best_growth: ``rule_id`` with the best dev growth per session, or None.
        best_low_drawdown: ``rule_id`` with the best dev growth among qualified rules whose
            dev ladder drawdown is below ``drawdown_median``, or None.
        drawdown_median: Median dev ladder drawdown of the qualified rules.
        median_rule: ``rule_id`` at the median dev-growth position, or None.
    """

    qualified: pd.DataFrame
    best_growth: str | None
    best_low_drawdown: str | None
    drawdown_median: float
    median_rule: str | None


def pick_rules(results: pd.DataFrame, *, min_dev_trades: int) -> Picks:
    """Apply the selection protocol to sweep results.

    Args:
        results: One row per rule with ``rule_id`` and the ``flatten`` columns.
        min_dev_trades: Fewest dev trades a rule needs to be ranked.

    Returns:
        The picks.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(
        results,
        ("rule_id", "n_trades_dev", "growth_per_session_dev", "ladder_max_drawdown_dev"),
        "results",
    )
    growth = results["growth_per_session_dev"].astype("float64")
    ok = (results["n_trades_dev"].astype("float64") >= min_dev_trades) & np.isfinite(growth)
    qualified = results.loc[ok].assign(_g=growth[ok])
    qualified = qualified.sort_values(["_g", "rule_id"], ascending=[False, True], kind="stable")
    qualified = qualified.drop(columns="_g").reset_index(drop=True)
    if qualified.empty:
        return Picks(qualified, None, None, math.nan, None)
    drawdown = qualified["ladder_max_drawdown_dev"].astype("float64")
    median = float(drawdown.median())
    low = qualified.loc[drawdown < median]
    return Picks(
        qualified=qualified,
        best_growth=str(qualified["rule_id"].iloc[0]),
        best_low_drawdown=str(low["rule_id"].iloc[0]) if not low.empty else None,
        drawdown_median=median,
        median_rule=str(qualified["rule_id"].iloc[(len(qualified) - 1) // 2]),
    )


def beat_counts(qualified: pd.DataFrame, baseline: Mapping[str, float]) -> tuple[int, int]:
    """Count qualified rules that beat a baseline's growth on dev, and of those on hold-out.

    Args:
        qualified: ``Picks.qualified``.
        baseline: Flattened metrics of the baseline.

    Returns:
        ``(beat_dev, beat_both)``.
    """
    dev = qualified["growth_per_session_dev"].astype("float64")
    beat = qualified.loc[dev > baseline["growth_per_session_dev"]]
    hold = beat["growth_per_session_holdout"].astype("float64")
    return len(beat), int((hold > baseline["growth_per_session_holdout"]).sum())
