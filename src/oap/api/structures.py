"""The structure calculator: frames and curves in, response models out.

Pure functions, no I/O. Each expiration is scored against exactly the landscape's raw and
calibrated CDFs (``oap.api.landscape.ExpiryCurves``), completed with lognormal tails
(``oap.engine.positions.TailCompletedCdf``) whose volatilities come from the outermost usable
quotes (``oap.analytics.views.tail_sigmas``). A ``StructureBook`` holds what does not depend
on the outcome (the distributions and the enumerated structures), so the store caches it and
scores a new outcome without enumerating again.

Units: strikes, prices, premiums and profit and loss in dollars per share ($/sh); volatility
as a decimal; probabilities and returns on max loss as decimals; densities in 1/$; time in
years (ACT/365) or calendar days; moneyness is a price divided by the underlying close.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import pandas as pd

from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.sample import usable_mask
from oap.analytics.views import PRESETS, pick_expiration, preset_by_id, resolve_preset, tail_sigmas
from oap.api.errors import NotFound, Unprocessable
from oap.api.landscape import ChosenMap, ExpiryCurves, expiry_curves, finite_or_none
from oap.api.models import (
    DistributionResponse,
    DominanceSegment,
    Fill,
    KindBest,
    OutcomeCell,
    OutcomeMapResponse,
    OutcomeRow,
    PresetId,
    PresetInfo,
    StructureRow,
    StructuresResponse,
    TailInfo,
    ViewInfo,
)
from oap.api.models import Verdict as VerdictModel
from oap.engine.errors import EngineInputError
from oap.engine.positions import (
    Position,
    StructureKind,
    StructureScore,
    TailCompletedCdf,
    View,
    score_structures,
)
from oap.engine.structures import (
    ChainSide,
    Verdict,
    best_per_kind,
    dominance,
    enumerate_structures,
    ranked,
    verdict,
)

GRID_POINTS: Final = 161
"""Terminal prices in the response grid."""
GRID_QUANTILES: Final = (0.005, 0.995)
"""The grid spans these quantiles of the calibrated, tail-completed distribution."""
TARGET_DTE: Final = 35
"""Calendar days to expiration of the default expiration."""
DEFAULT_MIN_POP_GIVEN: Final = 0.5
"""Default smallest P(profit | outcome), a decimal, for a structure to qualify."""


@dataclass(frozen=True)
class StructuresQuery:
    """The query of ``GET /api/structures/{symbol}/{session}``.

    Attributes:
        expiration: Requested expiration; the one nearest ``TARGET_DTE`` days when None.
        preset: A preset outcome; takes precedence over the custom bounds.
        lo: Lower bound of a custom outcome as a fraction of the close; None when open.
        hi: Upper bound of a custom outcome as a fraction of the close; None when open.
        outside: True for the prices outside ``[lo, hi)``.
        fill: natural or mid fills.
        min_pop_given: Smallest P(profit | outcome), a decimal, for a structure to qualify.
        limit: Most ranking rows.
    """

    expiration: date | None = None
    preset: PresetId | None = None
    lo: float | None = None
    hi: float | None = None
    outside: bool = False
    fill: Fill = "natural"
    min_pop_given: float = 0.5
    limit: int = 25


@dataclass(frozen=True, eq=False)
class StructureBook:
    """One expiration's distributions and enumerated structures, independent of the outcome.

    Attributes:
        symbol: Ticker symbol.
        session: Trade date.
        expiration: Expiration date.
        dte_days: Calendar days from the session to expiration.
        curves: The landscape's raw and calibrated CDFs of the expiration.
        dist: The calibrated CDF, tail-completed.
        market: The raw (market-implied) CDF, completed with the same tail volatilities.
        fill: The fill of every leg price.
        positions: The enumerated structures.
    """

    symbol: str
    session: date
    expiration: date
    dte_days: int
    curves: ExpiryCurves
    dist: TailCompletedCdf
    market: TailCompletedCdf
    fill: Fill
    positions: tuple[Position, ...]


def chain_sides(chain: pd.DataFrame) -> tuple[ChainSide, ChainSide]:
    """Split one expiration's quotes into usable calls and puts.

    Args:
        chain: Quote rows with ``strike`` (dollars), ``option_right``, ``bid`` and ``ask``
            (dollars per share).

    Returns:
        ``(calls, puts)``, usable quotes only (``oap.analytics.sample.usable_mask``),
        strikes ascending.
    """
    usable = chain.loc[usable_mask(chain["bid"], chain["ask"]).to_numpy(dtype=np.bool_)]
    sides: list[ChainSide] = []
    for right in ("C", "P"):
        rows = usable.loc[usable["option_right"].astype(str) == right].sort_values(
            "strike", kind="stable"
        )
        sides.append(
            ChainSide(
                rows["strike"].to_numpy(dtype=np.float64),
                rows["bid"].to_numpy(dtype=np.float64),
                rows["ask"].to_numpy(dtype=np.float64),
            )
        )
    return sides[0], sides[1]


def build_book(
    symbol: str,
    session: date,
    dte_days: int,
    chain: pd.DataFrame,
    curves: ExpiryCurves,
    fill: Fill,
) -> StructureBook:
    """Complete the expiration's distributions and enumerate its structures.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        dte_days: Calendar days to expiration.
        chain: Quote rows of the expiration, with ``source_iv`` (decimal).
        curves: The landscape's CDFs of the expiration.
        fill: natural or mid fills.

    Returns:
        The book.

    Raises:
        Unprocessable: ``no_implied_vol`` when no quote of the expiration has a positive IV.
    """
    try:
        sigma_lo, sigma_hi = tail_sigmas(chain)
    except EngineInputError as exc:
        raise Unprocessable("no_implied_vol", f"{curves.expiration}: {exc}") from exc
    dist = TailCompletedCdf.complete(curves.cal, sigma_lo, sigma_hi)
    market = TailCompletedCdf.complete(curves.cdf, sigma_lo, sigma_hi)
    calls, puts = chain_sides(chain)
    positions = enumerate_structures(
        calls,
        puts,
        close=curves.close,
        years=curves.cdf.years,
        knot_lo=float(curves.cdf.strikes[0]),
        knot_hi=float(curves.cdf.strikes[-1]),
        fill=fill,
    )
    return StructureBook(
        symbol=symbol,
        session=session,
        expiration=curves.expiration,
        dte_days=dte_days,
        curves=curves,
        dist=dist,
        market=market,
        fill=fill,
        positions=tuple(positions),
    )


def choose_expiration(
    distribution: DistributionResponse, requested: date | None
) -> tuple[date, int]:
    """Pick the expiration to score.

    Args:
        distribution: The landscape's distributions of the session.
        requested: The requested expiration, or None for the default.

    Returns:
        ``(expiration, dte_days)``. The default is the expiration with a distribution and at
        least ``DEFAULT_CONFIG.min_dte_days`` days whose days to expiry are nearest
        ``TARGET_DTE``.

    Raises:
        NotFound: If the requested expiration is not quoted that session.
        Unprocessable: ``no_distribution`` when the requested expiration has no curve (the
            landscape's reason is echoed) or no expiration qualifies for the default.
    """
    if requested is not None:
        for expiry in distribution.expirations:
            if expiry.expiration == requested:
                if expiry.curve is None:
                    raise Unprocessable(
                        "no_distribution", f"{requested}: {expiry.unavailable_reason}"
                    )
                return requested, expiry.dte_days
        raise NotFound(
            f"{distribution.symbol} has no expiration {requested} on {distribution.session}"
        )
    candidates = [(e.expiration, e.dte_days) for e in distribution.expirations if e.curve]
    picked = pick_expiration(candidates, TARGET_DTE, DEFAULT_CONFIG.min_dte_days)
    if picked is None:
        raise Unprocessable(
            "no_distribution",
            f"no expiration with at least {DEFAULT_CONFIG.min_dte_days} days to expiry has a "
            "distribution",
        )
    return picked, dict(candidates)[picked]


def resolve_view(
    query: StructuresQuery, dist: TailCompletedCdf, close: float
) -> tuple[View, PresetId | None]:
    """Turn the query's preset or custom bounds into a view in dollars.

    Args:
        query: The query; ``preset`` wins over ``lo``, ``hi`` and ``outside``.
        dist: The calibrated, tail-completed distribution (for presets).
        close: Underlying close in dollars (custom bounds are fractions of it).

    Returns:
        The view and the preset id (None for a custom view).

    Raises:
        Unprocessable: ``view_required`` without a preset or a bound, ``view_invalid`` when
            ``lo >= hi`` or a preset collapses to a single price.
    """
    if query.preset is not None:
        try:
            return resolve_preset(preset_by_id(query.preset), dist), query.preset
        except EngineInputError as exc:
            raise Unprocessable("view_invalid", f"preset {query.preset}: {exc}") from exc
    if query.lo is None and query.hi is None:
        raise Unprocessable("view_required", "give a preset, or lo and/or hi as moneyness")
    if query.lo is not None and query.hi is not None and query.lo >= query.hi:
        raise Unprocessable("view_invalid", f"lo ({query.lo}) must be below hi ({query.hi})")
    lo = None if query.lo is None else query.lo * close
    hi = None if query.hi is None else query.hi * close
    return View(lo, hi, query.outside), None


def _nan_to_none(value: float) -> float | None:
    """Return None for a non-finite float."""
    return finite_or_none(value)


def _row_fields(score: StructureScore) -> dict[str, object]:
    """Return the ``StructureRow`` fields of a score.

    Args:
        score: The score.

    Returns:
        Field values; non-finite optional numbers become None.
    """
    position = score.position
    return {
        "kind": position.kind.value,
        "direction": position.direction,
        "legs": position.legs_text,
        "strikes": list(position.kinks),
        "net_premium": position.net_premium,
        "max_loss": position.max_loss,
        "max_gain": _nan_to_none(position.max_gain),
        "breakevens": list(position.breakevens),
        "prob_profit": score.prob_profit,
        "expected_return": score.expected_return,
        "annualised_return": _nan_to_none(score.annualised_return),
        "reward_to_risk": _nan_to_none(score.reward_to_risk),
        "prob_profit_given_view": _nan_to_none(score.prob_profit_given_view),
        "return_if_right": _nan_to_none(score.return_if_right),
        "return_if_wrong": _nan_to_none(score.return_if_wrong),
        "worst_in_view": _nan_to_none(score.worst_in_view),
        "pnl_std": score.pnl_std,
        "tail_share": score.tail_share,
    }


def structure_row(score: StructureScore) -> StructureRow:
    """Convert a score to a ranking row.

    Args:
        score: The score.

    Returns:
        The row.
    """
    return StructureRow.model_validate(_row_fields(score))


def kind_best(score: StructureScore, grid: np.ndarray) -> KindBest:
    """Convert a kind's best score to a row with its payoff curve.

    Args:
        score: The score.
        grid: Terminal prices in dollars.

    Returns:
        The row; ``curve`` is ``pnl / max_loss`` at each grid price.
    """
    curve = score.position.pnl(grid) / score.position.max_loss
    return KindBest.model_validate({**_row_fields(score), "curve": curve.tolist()})


def verdict_model(found: Verdict) -> VerdictModel:
    """Convert an engine verdict to the response model.

    Args:
        found: The engine verdict.

    Returns:
        The model; nan returns become None.
    """
    return VerdictModel(
        best_kind=None if found.best_kind is None else found.best_kind.value,
        spread_kind=None if found.best_spread_kind is None else found.best_spread_kind.value,
        single_kind=None if found.best_single_kind is None else found.best_single_kind.value,
        spread_return_if_right=_nan_to_none(found.spread_return_if_right),
        single_return_if_right=_nan_to_none(found.single_return_if_right),
        advantage=_nan_to_none(found.advantage),
        reason=found.reason,
    )


def response_grid(dist: TailCompletedCdf) -> np.ndarray:
    """Return the terminal price grid of a response.

    Args:
        dist: The calibrated, tail-completed distribution re-knotted at the raw knots
            (``TailCompletedCdf.coarsened``), the one whose density the response carries.

    Returns:
        ``GRID_POINTS`` evenly spaced prices in dollars between its ``GRID_QUANTILES``.
    """
    lo, hi = (dist.quantile(q) for q in GRID_QUANTILES)
    return np.linspace(lo, hi, GRID_POINTS)


def structures_response(
    book: StructureBook,
    view: View,
    preset: PresetId | None,
    query: StructuresQuery,
    chosen: ChosenMap,
) -> StructuresResponse:
    """Score the book's structures against a view and assemble the response.

    Args:
        book: The expiration's distributions and structures.
        view: The outcome in dollars.
        preset: The preset id, or None for a custom view.
        query: The query (threshold and row limit).
        chosen: The calibration map behind ``book.dist``.

    Returns:
        The response.
    """
    dist, close = book.dist, book.curves.close
    scores = score_structures(book.positions, dist, view)
    qualifying = ranked(scores, min_prob_profit_given_view=query.min_pop_given)
    bests = best_per_kind(scores, min_prob_profit_given_view=query.min_pop_given)
    display = dist.coarsened(book.curves.cdf.strikes)
    grid = response_grid(display)
    m_lo, m_hi = dist.tail_mass()
    return StructuresResponse(
        symbol=book.symbol,
        session=book.session,
        expiration=book.expiration,
        dte_days=book.dte_days,
        years=book.curves.cdf.years,
        underlying_close=close,
        forward=finite_or_none(book.curves.forward),
        fill=book.fill,
        map_id=chosen.map_id,
        map_is_identity=chosen.cmap.is_identity,
        look_ahead=chosen.look_ahead,
        tails=TailInfo(
            sigma_lo=dist.sigma_lo,
            sigma_hi=dist.sigma_hi,
            mass_lo=m_lo,
            mass_hi=m_hi,
            location=dist.location,
        ),
        view=ViewInfo(
            preset=preset,
            lo=view.lo,
            hi=view.hi,
            outside=view.outside,
            lo_moneyness=None if view.lo is None else view.lo / close,
            hi_moneyness=None if view.hi is None else view.hi / close,
            prob=dist.prob_view(view),
            prob_market=book.market.prob_view(view),
        ),
        grid=grid.tolist(),
        density=display.density_array(grid).tolist(),
        kinds=[kind_best(score, grid) for score in bests.values()],
        ranking=[structure_row(score) for score in qualifying[: query.limit]],
        dominance=[
            DominanceSegment.model_validate({"from": a, "to": b, "kind": kind.value})
            for a, b, kind in dominance(bests, grid)
        ],
        verdict=verdict_model(verdict(bests, view)),
        n_structures=len(book.positions),
        n_qualifying=len(qualifying),
    )


def _best_of(
    bests: Mapping[StructureKind, StructureScore], kind: StructureKind | None
) -> StructureScore | None:
    """Return the best score of a kind, or None."""
    return None if kind is None else bests.get(kind)


def outcome_cells(book: StructureBook, min_pop_given: float) -> list[OutcomeCell]:
    """Return the verdict numbers of one book for every preset outcome.

    Args:
        book: The expiration's distributions and structures.
        min_pop_given: Smallest P(profit | outcome), a decimal, for a structure to qualify.

    Returns:
        One cell per preset, in ``PRESETS`` order.

    Raises:
        Unprocessable: ``view_invalid`` when a preset collapses to a single price.
    """
    cells: list[OutcomeCell] = []
    for preset in PRESETS:
        view, _ = resolve_view(StructuresQuery(preset=preset.id), book.dist, book.curves.close)
        scores = score_structures(book.positions, book.dist, view)
        bests = best_per_kind(scores, min_prob_profit_given_view=min_pop_given)
        found = verdict(bests, view)
        best = _best_of(bests, found.best_kind)
        cells.append(
            OutcomeCell(
                preset=preset.id,
                lo=view.lo,
                hi=view.hi,
                prob=book.dist.prob_view(view),
                prob_market=book.market.prob_view(view),
                best_kind=None if found.best_kind is None else found.best_kind.value,
                best_return_if_right=None if best is None else _nan_to_none(best.return_if_right),
                best_legs=None if best is None else best.position.legs_text,
                spread_kind=None
                if found.best_spread_kind is None
                else found.best_spread_kind.value,
                spread_return_if_right=_nan_to_none(found.spread_return_if_right),
                single_kind=None
                if found.best_single_kind is None
                else found.best_single_kind.value,
                single_return_if_right=_nan_to_none(found.single_return_if_right),
                advantage=_nan_to_none(found.advantage),
            )
        )
    return cells


def _outcome_row(
    symbol: str,
    session: date,
    quotes: pd.DataFrame,
    chosen: ChosenMap,
    target_dte: int,
    fill: Fill,
    min_pop_given: float,
) -> OutcomeRow:
    """Build the outcome-map row of one underlying.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        quotes: The underlying's quotes of the session.
        chosen: The calibration map.
        target_dte: Target calendar days to expiration.
        fill: natural or mid fills.
        min_pop_given: Smallest P(profit | outcome), a decimal, for a structure to qualify.

    Returns:
        The row, or a row without cells and with ``unavailable_reason``.
    """
    curves: dict[date, tuple[ExpiryCurves, int, pd.DataFrame]] = {}
    for stamp, chain in quotes.groupby("expiration", sort=True, observed=True):
        dte_days = int(chain["dte_days"].iloc[0])
        if dte_days < DEFAULT_CONFIG.min_dte_days:
            continue
        expiration = pd.Timestamp(str(stamp)).date()
        found, _ = expiry_curves(chain, session, expiration, chosen)
        if found is not None:
            curves[expiration] = (found, dte_days, chain)
    closes = quotes["underlying_close"].dropna()
    close = finite_or_none(closes.iloc[0]) if not closes.empty else None
    picked = pick_expiration(
        [(e, dte) for e, (_, dte, _) in curves.items()], target_dte, DEFAULT_CONFIG.min_dte_days
    )
    if picked is None:
        return OutcomeRow(
            symbol=symbol,
            expiration=None,
            dte_days=None,
            underlying_close=close,
            cells=[],
            unavailable_reason=(
                f"no_distribution: no expiration with at least {DEFAULT_CONFIG.min_dte_days} "
                "days to expiry has a distribution"
            ),
        )
    found, dte_days, chain = curves[picked]
    try:
        book = build_book(symbol, session, dte_days, chain, found, fill)
        cells = outcome_cells(book, min_pop_given)
    except Unprocessable as exc:
        return OutcomeRow(
            symbol=symbol,
            expiration=picked,
            dte_days=dte_days,
            underlying_close=close,
            cells=[],
            unavailable_reason=f"{exc.code}: {exc.detail}",
        )
    return OutcomeRow(
        symbol=symbol,
        expiration=picked,
        dte_days=dte_days,
        underlying_close=found.close,
        cells=cells,
        unavailable_reason=None,
    )


def outcome_map(
    session: date,
    quotes: pd.DataFrame,
    chosen: ChosenMap,
    *,
    target_dte: int,
    fill: Fill,
    min_pop_given: float,
) -> OutcomeMapResponse:
    """Build the outcome map of one session: every underlying against every preset.

    Args:
        session: Trade date.
        quotes: Every underlying's quotes of the session (``SESSION_QUOTES_SQL``).
        chosen: The calibration map for the session.
        target_dte: Target calendar days to expiration.
        fill: natural or mid fills.
        min_pop_given: Smallest P(profit | outcome), a decimal, for a structure to qualify.

    Returns:
        One row per underlying, by symbol.
    """
    rows: list[OutcomeRow] = []
    for symbol, part in quotes.groupby("underlying", sort=True, observed=True):
        rows.append(
            _outcome_row(str(symbol), session, part, chosen, target_dte, fill, min_pop_given)
        )
    return OutcomeMapResponse(
        session=session,
        target_dte=target_dte,
        fill=fill,
        map_id=chosen.map_id,
        presets=[PresetInfo(id=p.id, label=p.label) for p in PRESETS],
        rows=rows,
    )
