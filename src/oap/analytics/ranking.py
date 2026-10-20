"""Rankings of scored put credit spreads, shared by the live entry rule and the rule lab.

The live scoring (``oap.analytics.scoring``) orders the "Top to enter" candidates with one of
these rankings (``AnalyticsConfig.entry_rank``), and the rule lab (``oap.analytics.rulelab``)
sweeps all of them, so a rule tested in the lab is ranked by the same function in the
product. Every function is pure and works on frames with the columns of ``SPREAD_COLUMNS``.

Rankings (higher is better; nan ranks last), with natural credit ``c_n``, width ``W``,
natural max loss ``L_n = W - c_n``, natural odds ``b = c_n / L_n``, calibrated POP ``p`` and
holding period ``years``; annualising is ``(1 + r) ** (1 / years) - 1`` as in the engine:

* ``return_mid``: ``annualised_roc`` (mid credit, interest included);
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

Units: credits and widths in dollars per share; probabilities are decimals in [0, 1]; returns
are decimals on max loss (0.02 is 2%) over the holding period unless annualised; ``years`` is
calendar days / 365; ``dte_days`` is calendar days; moneyness is short strike over close.
"""

from collections.abc import Mapping
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from oap.analytics.config import RankBy
from oap.engine._types import FloatArray

BoolArray = npt.NDArray[np.bool_]

KELLY_CAP: Final = 0.5
"""Largest Kelly fraction used by ``kelly_growth``, a decimal share of capital."""
POP_SHRINK: Final = 0.5
"""Weight of ``pop_implied`` in the shrunk POP of ``pop_shrunk_return``."""

RANK_WORDS: Final[Mapping[RankBy, str]] = {
    "return_mid": "annualised return on max loss at the mid credit",
    "return_natural": "annualised calibrated return on max loss at the natural credit",
    "reward_to_risk": "reward to risk (expected payoff over its standard deviation)",
    "kelly_growth": "expected log growth of a capped Kelly bet at natural odds",
    "pop_shrunk_return": (
        "annualised natural return with the POP shrunk halfway toward the market-implied POP"
    ),
}
"""Each ranking in words, for rule descriptions."""


def floats(frame: pd.DataFrame, column: str) -> FloatArray:
    """Return a column as a float64 array.

    Args:
        frame: Any frame.
        column: Name of a numeric column.

    Returns:
        The values as float64; nulls become nan.
    """
    return np.asarray(frame[column].to_numpy(dtype=np.float64, na_value=np.nan), dtype=np.float64)


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
    """Return ``credit_natural / (width - credit_natural)``, the odds at the natural fill.

    Args:
        frame: Scored spreads with ``credit_natural`` and ``width`` in dollars per share.

    Returns:
        Win over loss per dollar risked at the natural credit; infinite or nan where the
        natural max loss is 0.
    """
    natural = floats(frame, "credit_natural")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(natural / (floats(frame, "width") - natural), dtype=np.float64)


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
    """Return the calibrated POP shrunk toward the market-implied POP by ``POP_SHRINK``.

    Args:
        prob: Calibrated probability of profit, decimals in [0, 1].
        pop_implied: Probability of profit the price implies (max loss over width), decimals.

    Returns:
        ``(1 - POP_SHRINK) * prob + POP_SHRINK * pop_implied``, decimals in [0, 1].
    """
    return np.asarray((1.0 - POP_SHRINK) * prob + POP_SHRINK * pop_implied, dtype=np.float64)


def rank_score(frame: pd.DataFrame, rank_by: RankBy) -> FloatArray:
    """Return the ranking score of every row; higher ranks first.

    Args:
        frame: Scored spreads with ``SPREAD_COLUMNS``.
        rank_by: The ranking; see the module docstring.

    Returns:
        One float per row: an annualised return on max loss (decimal per year) for the
        return rankings, a per-trade ratio for ``reward_to_risk`` and log growth per trade
        for ``kelly_growth``; nan where the score is undefined.
    """
    if rank_by == "return_mid":
        return floats(frame, "annualised_roc")
    if rank_by == "reward_to_risk":
        return floats(frame, "reward_to_risk")
    odds = natural_odds(frame)
    prob = floats(frame, "prob_profit")
    years = floats(frame, "years")
    if rank_by == "kelly_growth":
        return kelly_growth(prob, odds, floats(frame, "kelly_fraction"))
    if rank_by == "return_natural":
        loss = floats(frame, "width") - floats(frame, "credit_natural")
        with np.errstate(divide="ignore", invalid="ignore"):
            return annualise(floats(frame, "edge_natural") / loss, years)
    q = shrunk_pop(prob, floats(frame, "pop_implied"))
    with np.errstate(invalid="ignore"):
        return annualise(q * odds - (1.0 - q), years)


def band_mask(values: FloatArray, band: tuple[float, float] | None) -> BoolArray:
    """Return where ``lo <= value < hi``; everything when ``band`` is None.

    Args:
        values: Values in the band's units (calendar days, or short strike over close).
        band: ``(lo, hi)``, or None for no bound.

    Returns:
        One boolean per value; nan is outside every band.
    """
    if band is None:
        return np.ones(values.shape[0], dtype=np.bool_)
    lo, hi = band
    return np.asarray((values >= lo) & (values < hi), dtype=np.bool_)
