"""Preset outcomes, tail volatilities and the expiration choice of the structure calculator.

Preset outcomes are quantile ranges of the calibrated, tail-completed distribution, so "up,
moderately" means the same thing for a quiet ETF and a volatile single name. The tail
volatilities that complete the distribution come from the outermost usable quotes of the
expiration's chain.

Pure functions over frames and engine objects: no I/O, no state. Units: strikes and prices in
dollars per share; implied volatility as a decimal (0.20, not 20%); probabilities and
quantile levels as decimals in [0, 1]; days to expiration in calendar days.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

import numpy as np
import pandas as pd

from oap.analytics.sample import usable_mask
from oap.engine.errors import EngineInputError
from oap.engine.positions import TailCompletedCdf, View

PresetId = Literal["up", "up_moderate", "flat", "down_moderate", "down", "big_move"]


@dataclass(frozen=True)
class Preset:
    """A preset outcome: a quantile range of the price at expiry, or its complement.

    Attributes:
        id: Stable identifier used by the API.
        label: Human-readable label with its quantiles.
        lo_q: Lower quantile level, a decimal in (0, 1); None for no lower bound.
        hi_q: Upper quantile level, a decimal in (0, 1); None for no upper bound.
        outside: True for the prices outside the range (a big move).
    """

    id: PresetId
    label: str
    lo_q: float | None
    hi_q: float | None
    outside: bool


PRESETS: Final[tuple[Preset, ...]] = (
    Preset("up", "Up, above the 75th percentile", 0.75, None, False),
    Preset("up_moderate", "Up, moderately (55th to 85th)", 0.55, 0.85, False),
    Preset("flat", "Flat (25th to 75th)", 0.25, 0.75, False),
    Preset("down_moderate", "Down, moderately (15th to 45th)", 0.15, 0.45, False),
    Preset("down", "Down, below the 25th percentile", None, 0.25, False),
    Preset("big_move", "Big move, outside the 10th to 90th", 0.10, 0.90, True),
)
"""The six preset outcomes, in display order."""


def preset_by_id(preset_id: str) -> Preset:
    """Return the preset with an id.

    Args:
        preset_id: One of the ids in ``PRESETS``.

    Returns:
        The preset.

    Raises:
        ValueError: If no preset has the id.
    """
    for preset in PRESETS:
        if preset.id == preset_id:
            return preset
    raise ValueError(f"unknown preset: {preset_id}")


def resolve_preset(preset: Preset, dist: TailCompletedCdf) -> View:
    """Turn a preset into prices with the quantiles of a distribution.

    Args:
        preset: The preset outcome.
        dist: The calibrated, tail-completed distribution of the price at expiry.

    Returns:
        The view, bounds in dollars.
    """
    lo = None if preset.lo_q is None else dist.quantile(preset.lo_q)
    hi = None if preset.hi_q is None else dist.quantile(preset.hi_q)
    return View(lo, hi, preset.outside)


def _positive_iv(chain: pd.DataFrame) -> pd.Series:
    """Return the source IVs as floats, nan where not finite and positive.

    Args:
        chain: Quote rows with ``source_iv`` (decimal).

    Returns:
        The IVs aligned with ``chain``.
    """
    iv = pd.to_numeric(chain["source_iv"], errors="coerce").astype("float64")
    return iv.where(np.isfinite(iv) & (iv > 0))


def tail_sigmas(chain: pd.DataFrame) -> tuple[float, float]:
    """Pick the volatilities of the lower and upper tails from one expiration's quotes.

    The lower tail takes the IV of the lowest-strike usable put with a positive source IV,
    the upper tail that of the highest-strike usable call with one. When that side has none,
    the usable quote of either right nearest that end (lowest strike for the lower tail,
    highest for the upper) with a positive IV is used; failing that, the median positive IV
    of the expiration, usable or not.

    Args:
        chain: Quote rows of one expiration with ``strike`` (dollars), ``option_right`` (C or
            P), ``bid`` and ``ask`` (dollars per share) and ``source_iv`` (decimal).

    Returns:
        ``(sigma_lo, sigma_hi)`` as decimals.

    Raises:
        EngineInputError: If no quote of the expiration has a positive IV.
    """
    iv = _positive_iv(chain)
    if not iv.notna().any():
        raise EngineInputError("no quote of the expiration has a positive implied volatility")
    usable = usable_mask(chain["bid"], chain["ask"]) & iv.notna()
    right = chain["option_right"].astype(str)
    strikes = pd.to_numeric(chain["strike"], errors="coerce").astype("float64")
    median = float(iv.median())

    def pick(mask: pd.Series, lowest: bool) -> float | None:
        if not mask.any():
            return None
        candidates = strikes[mask]
        index = candidates.idxmin() if lowest else candidates.idxmax()
        return float(iv.loc[index])

    sigma_lo = pick(usable & (right == "P"), True)
    if sigma_lo is None:
        sigma_lo = pick(usable, True)
    sigma_hi = pick(usable & (right == "C"), False)
    if sigma_hi is None:
        sigma_hi = pick(usable, False)
    return (
        median if sigma_lo is None or not math.isfinite(sigma_lo) else sigma_lo,
        median if sigma_hi is None or not math.isfinite(sigma_hi) else sigma_hi,
    )


def pick_expiration(
    expirations: Sequence[tuple[date, int]], target_dte: int, min_dte: int
) -> date | None:
    """Return the expiration whose days to expiry are nearest a target.

    Args:
        expirations: ``(expiration, dte_days)`` pairs, in any order.
        target_dte: Target calendar days to expiration.
        min_dte: Fewest calendar days to expiration considered.

    Returns:
        The expiration with ``dte_days >= min_dte`` nearest ``target_dte``, the earlier one
        on a tie; None when no expiration qualifies.
    """
    eligible = [(abs(dte - target_dte), dte, exp) for exp, dte in expirations if dte >= min_dte]
    if not eligible:
        return None
    return min(eligible)[2]
