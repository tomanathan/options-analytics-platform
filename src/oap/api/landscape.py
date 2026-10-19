"""The landscape of one session: chain, risk-neutral distributions and probability heatmap.

Pure functions over frames: no I/O and no state. The CDF of each expiration is built the way
the backtest builds it, ``chain_cdf`` at the configured risk-free rate, and the calibration
map is applied with ``apply_calibration``; the calibrated curve is then evaluated at the raw
knots, so a response never carries the roughly 400 knots of the composed CDF.

Units: strikes, prices and closes are in dollars per share ($/sh); implied volatility is a
decimal; probabilities are decimals in [0, 1]; densities are probability per dollar (1/$);
time is in years (ACT/365) or calendar days; moneyness is a strike divided by the underlying
close.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import pandas as pd

from oap.analytics.config import DEFAULT_CONFIG, PRODUCTION_MAP_ID, AnalyticsConfig, fold_map_id
from oap.analytics.sample import STRIKE_DECIMALS, chain_cdf, usable_mask
from oap.api.models import (
    ChainExpiry,
    ChainQuote,
    ChainResponse,
    DistributionCurve,
    DistributionResponse,
    ExpiryDistribution,
    HeatmapResponse,
    HeatmapRow,
    MapChoice,
    SessionSummary,
)
from oap.engine.calibration import CalibrationMap, apply_calibration
from oap.engine.conventions import dte_years
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import RiskNeutralCdf

HEATMAP_MONEYNESS: Final[tuple[float, ...]] = tuple(round(0.80 + 0.01 * i, 2) for i in range(41))
"""Display columns of the heatmap: moneyness 0.80, 0.81, ..., 1.20."""

IDENTITY_MAP_ID: Final = "identity"
"""Identifier reported when no stored map applies."""


@dataclass(frozen=True)
class MapMeta:
    """Provenance of a stored calibration map.

    Attributes:
        fold: Calendar year the map is applied to; None for the production map.
        train_cutoff: First date the map may not use; None for the production map.
        train_max_expiration: Latest expiration among the training outcomes; None if none.
        n_samples: Number of outcomes the map was fitted on.
    """

    fold: int | None
    train_cutoff: date | None
    train_max_expiration: date | None
    n_samples: int


@dataclass(frozen=True, eq=False)
class ChosenMap:
    """A calibration map picked for a session.

    Attributes:
        map_id: Identifier of the map, or ``identity`` when none applied.
        cmap: The map from raw to calibrated probabilities (decimals in [0, 1]).
        train_max_expiration: Latest expiration among the training outcomes; None if unknown.
        look_ahead: True when the map was fitted on outcomes that settle after the session.
    """

    map_id: str
    cmap: CalibrationMap
    train_max_expiration: date | None
    look_ahead: bool


@dataclass(frozen=True, eq=False)
class ExpiryCurves:
    """The CDFs of one expiration, kept so a spread can be scored against exactly them.

    Attributes:
        expiration: Expiration date.
        close: Underlying close in dollars.
        forward: Forward price in dollars; nan when unknown.
        cdf: Raw risk-neutral CDF from ``chain_cdf``.
        cal: ``cdf`` composed with the calibration map (exact, with extra knots).
        curve: The response form, evaluated at the raw knots.
    """

    expiration: date
    close: float
    forward: float
    cdf: RiskNeutralCdf
    cal: RiskNeutralCdf
    curve: DistributionCurve


@dataclass(frozen=True, eq=False)
class SessionBundle:
    """Everything the API serves for one underlying, session and calibration map.

    Attributes:
        symbol: Ticker symbol.
        session: Trade date.
        chain: The option chain.
        distribution: The distributions, with ``map_choice`` ``auto`` (the caller sets it).
        heatmap: The probability heatmap.
        curves: Exact CDFs per expiration that has a curve.
    """

    symbol: str
    session: date
    chain: ChainResponse
    distribution: DistributionResponse
    heatmap: HeatmapResponse
    curves: Mapping[date, ExpiryCurves]


@dataclass(frozen=True, eq=False)
class QuotesBundle:
    """All quotes and outcomes of one underlying, indexed by session.

    Attributes:
        quotes: Quote rows sorted by trade date.
        outcomes: Settlement closes of the underlying, in dollars.
        sessions: One summary per trade date, ascending.
        ranges: Row range ``(start, stop)`` of each session in ``quotes``.
    """

    quotes: pd.DataFrame
    outcomes: pd.DataFrame
    sessions: list[SessionSummary]
    ranges: Mapping[date, tuple[int, int]]

    def session_quotes(self, session: date) -> pd.DataFrame | None:
        """Return the quotes of one session.

        Args:
            session: Trade date.

        Returns:
            The rows of that session, or None when the underlying has none.
        """
        span = self.ranges.get(session)
        if span is None:
            return None
        return self.quotes.iloc[span[0] : span[1]]


def finite_or_none(value: object) -> float | None:
    """Return a float, or None when it is null, NaN or infinite.

    Args:
        value: A number, None or a pandas null.

    Returns:
        The value as a float if it is a finite number, otherwise None.
    """
    if not isinstance(value, int | float | np.integer | np.floating):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _positive(value: object) -> float | None:
    """Return a finite, strictly positive float, or None.

    Args:
        value: A number, None or a pandas null.

    Returns:
        The value as a float if finite and above zero, otherwise None.
    """
    number = finite_or_none(value)
    return number if number is not None and number > 0 else None


def sessions_summary(
    quotes: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG
) -> list[SessionSummary]:
    """Summarise every trade date of one underlying's quotes.

    The at-the-money volatility is that of the out-of-the-money put (moneyness below 1) with
    the smallest ``1 - moneyness`` and a positive source IV, in the shortest expiration with
    at least ``config.min_dte_days`` days to expiry.

    Args:
        quotes: Quote rows with ``trade_date``, ``expiration``, ``strike``, ``option_right``,
            ``moneyness``, ``source_iv`` (decimal), ``dte_days`` and ``underlying_close``
            (dollars).
        config: Analytics parameters; ``min_dte_days`` is the shortest expiry considered.

    Returns:
        One summary per trade date, ascending; empty when there are no quotes.
    """
    if quotes.empty:
        return []
    base = quotes.groupby("trade_date", sort=True, observed=True).agg(
        close=("underlying_close", "first"),
        n_expirations=("expiration", "nunique"),
        n_quotes=("strike", "size"),
    )
    puts = quotes.loc[
        (quotes["option_right"] == "P")
        & (quotes["dte_days"] >= config.min_dte_days)
        & (quotes["moneyness"] < 1.0)
        & (quotes["source_iv"] > 0.0)
        & np.isfinite(quotes["source_iv"].to_numpy(dtype=np.float64))
    ]
    ordered = puts.assign(gap=1.0 - puts["moneyness"]).sort_values(
        ["trade_date", "expiration", "gap"], kind="stable"
    )
    atm = ordered.groupby("trade_date", sort=True, observed=True)["source_iv"].first()
    summaries: list[SessionSummary] = []
    for stamp, row in base.iterrows():
        summaries.append(
            SessionSummary(
                session=pd.Timestamp(str(stamp)).date(),
                underlying_close=finite_or_none(row["close"]),
                n_expirations=int(row["n_expirations"]),
                n_quotes=int(row["n_quotes"]),
                atm_iv=finite_or_none(atm.get(stamp)),
            )
        )
    return summaries


def build_quotes_bundle(
    quotes: pd.DataFrame, outcomes: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG
) -> QuotesBundle:
    """Index one underlying's quotes by session and summarise the sessions.

    Args:
        quotes: Quote rows as in ``sessions_summary``.
        outcomes: ``expiration``, ``settlement_date`` and ``settlement_close`` (dollars).
        config: Analytics parameters.

    Returns:
        The bundle; ``quotes`` is sorted by trade date with a fresh index.
    """
    ordered = quotes.sort_values("trade_date", kind="stable").reset_index(drop=True)
    ranges: dict[date, tuple[int, int]] = {}
    if not ordered.empty:
        stamps = ordered["trade_date"].to_numpy()
        sessions = np.unique(stamps)
        starts = np.searchsorted(stamps, sessions, side="left")
        stops = np.searchsorted(stamps, sessions, side="right")
        for stamp, start, stop in zip(sessions, starts, stops, strict=True):
            ranges[pd.Timestamp(stamp).date()] = (int(start), int(stop))
    return QuotesBundle(
        quotes=ordered,
        outcomes=outcomes,
        sessions=sessions_summary(ordered, config),
        ranges=ranges,
    )


def _named(
    map_id: str,
    session: date,
    maps: Mapping[str, CalibrationMap],
    meta: Mapping[str, MapMeta],
) -> ChosenMap:
    """Return the stored map with this id, or the identity map when it is absent.

    Args:
        map_id: Identifier to look up.
        session: Trade date the map is applied to.
        maps: Calibration maps keyed by id.
        meta: Provenance keyed by id.

    Returns:
        The chosen map. ``look_ahead`` is true when the map's latest training expiration is
        after the session, so the map has seen an outcome that was not known then.
    """
    cmap = maps.get(map_id)
    if cmap is None:
        return ChosenMap(IDENTITY_MAP_ID, CalibrationMap.identity(), None, False)
    info = meta.get(map_id)
    trained_to = None if info is None else info.train_max_expiration
    return ChosenMap(map_id, cmap, trained_to, trained_to is not None and trained_to > session)


def named_map(
    map_id: str,
    session: date,
    maps: Mapping[str, CalibrationMap],
    meta: Mapping[str, MapMeta],
) -> ChosenMap | None:
    """Return the stored map with this id for a session.

    Args:
        map_id: Identifier, such as the ``map_id`` of a gold spread row.
        session: Trade date the map is applied to.
        maps: Calibration maps keyed by id.
        meta: Provenance keyed by id.

    Returns:
        The chosen map, or None when no stored map has that id.
    """
    if map_id not in maps:
        return None
    return _named(map_id, session, maps, meta)


def pick_map(
    choice: MapChoice,
    session: date,
    latest: date | None,
    maps: Mapping[str, CalibrationMap],
    meta: Mapping[str, MapMeta],
) -> ChosenMap:
    """Choose the calibration map for a session.

    ``production`` is the map fitted on every settled outcome. ``walk_forward`` is
    ``fold_<year of the session>``, which saw only outcomes before 1 January of that year.
    ``auto`` is ``production`` for the latest session and ``walk_forward`` for any earlier
    one, so history is not shown through a map that has seen its outcomes. A missing map
    falls back to the identity map.

    Args:
        choice: The requested selection.
        session: Trade date.
        latest: Latest session of the whole table; None if unknown.
        maps: Calibration maps keyed by id.
        meta: Provenance keyed by id.

    Returns:
        The chosen map.
    """
    use_production = choice == "production" or (choice == "auto" and session == latest)
    map_id = PRODUCTION_MAP_ID if use_production else fold_map_id(session.year)
    return _named(map_id, session, maps, meta)


def _years(session: date, expiration: date) -> float:
    """Return the time to expiration in years, ACT/365, never negative.

    Args:
        session: Trade date.
        expiration: Expiration date.

    Returns:
        ``dte_years`` when the expiration is not before the session, otherwise 0.0.
    """
    if expiration < session:
        return 0.0
    return dte_years(session, expiration)


def _chain_response(
    symbol: str, session: date, quotes: pd.DataFrame, close: float | None
) -> ChainResponse:
    """Group a session's quotes by expiration.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        quotes: Quote rows of the session.
        close: Underlying close in dollars.

    Returns:
        The chain, expirations ascending, strikes ascending with calls before puts.
    """
    usable = usable_mask(quotes["bid"], quotes["ask"]).to_numpy(dtype=np.bool_)
    frame = quotes.assign(
        usable=usable, right=quotes["option_right"].astype(str), mid=quotes["mid"].astype("float64")
    ).sort_values(["expiration", "strike", "right"], kind="stable")
    expiries: list[ChainExpiry] = []
    for stamp, chain in frame.groupby("expiration", sort=True, observed=True):
        rows = [
            ChainQuote(
                strike=float(strike),
                option_right="C" if right == "C" else "P",
                bid=finite_or_none(bid),
                ask=finite_or_none(ask),
                mid=finite_or_none(mid),
                iv=_positive(iv),
                delta=finite_or_none(delta),
                moneyness=finite_or_none(moneyness),
                usable=bool(ok),
            )
            for strike, right, bid, ask, mid, iv, delta, moneyness, ok in zip(
                chain["strike"],
                chain["right"],
                chain["bid"],
                chain["ask"],
                chain["mid"],
                chain["source_iv"],
                chain["source_delta"],
                chain["moneyness"],
                chain["usable"],
                strict=True,
            )
        ]
        expiries.append(
            ChainExpiry(
                expiration=pd.Timestamp(str(stamp)).date(),
                dte_days=int(chain["dte_days"].iloc[0]),
                quotes=rows,
            )
        )
    return ChainResponse(
        symbol=symbol, session=session, underlying_close=close, expirations=expiries
    )


def _curve(cdf: RiskNeutralCdf, cal: RiskNeutralCdf, close: float) -> DistributionCurve:
    """Build the response curve, with the calibrated CDF evaluated at the raw knots.

    Args:
        cdf: Raw risk-neutral CDF.
        cal: ``cdf`` composed with the calibration map.
        close: Underlying close in dollars.

    Returns:
        The curve: knots in dollars, moneyness, the three CDFs and the densities (1/$).
    """
    knots = cdf.strikes
    calibrated = cal.prob_below_array(knots)
    mid, density = cdf.density()
    density_cal = np.diff(calibrated) / np.diff(knots)
    return DistributionCurve(
        knots=knots.tolist(),
        moneyness=(knots / close).tolist(),
        cdf=cdf.cdf.tolist(),
        raw_cdf=cdf.raw_cdf.tolist(),
        cdf_calibrated=calibrated.tolist(),
        density_mid=mid.tolist(),
        density=density.tolist(),
        density_calibrated=density_cal.tolist(),
    )


def _build_cdf(
    dte_days: int, close: float | None, chain: pd.DataFrame, session: date, expiration: date
) -> tuple[RiskNeutralCdf | None, str | None]:
    """Build the CDF of one expiration, or say why there is none.

    Args:
        dte_days: Calendar days to expiration.
        close: Underlying close in dollars; None if null.
        chain: Quote rows of the expiration.
        session: Trade date.
        expiration: Expiration date.

    Returns:
        ``(cdf, None)``, or ``(None, reason)`` with reason ``expired``, ``no_close``,
        ``too_few_puts`` or ``engine_error: <message>``.
    """
    if dte_days < 1:
        return None, "expired"
    if close is None or close <= 0:
        return None, "no_close"
    try:
        cdf = chain_cdf(chain, years=_years(session, expiration), rate=DEFAULT_CONFIG.risk_free_apy)
    except EngineInputError as exc:
        return None, f"engine_error: {exc}"
    if cdf is None:
        return None, "too_few_puts"
    return cdf, None


def _heatmap_row(expiration: date, dte_days: int, curves: ExpiryCurves) -> HeatmapRow:
    """Evaluate P(S < K) on the display grid, without extrapolating.

    Args:
        expiration: Expiration date.
        dte_days: Calendar days to expiration.
        curves: The CDFs of the expiration.

    Returns:
        The row. A column is null outside ``[knots[0], knots[-1]]``, the backtest's
        no-extrapolation rule; targets are ``moneyness * close`` rounded to 1e-6 dollars.
    """
    targets = np.round(np.asarray(HEATMAP_MONEYNESS) * curves.close, STRIKE_DECIMALS)
    knots = curves.cdf.strikes
    inside = (targets >= knots[0]) & (targets <= knots[-1])
    raw = curves.cdf.prob_below_array(targets)
    calibrated = curves.cal.prob_below_array(targets)
    forward = finite_or_none(curves.forward)
    return HeatmapRow(
        expiration=expiration,
        dte_days=dte_days,
        target_strikes=targets.tolist(),
        prob_below=[float(p) if ok else None for p, ok in zip(raw, inside, strict=True)],
        prob_below_calibrated=[
            float(p) if ok else None for p, ok in zip(calibrated, inside, strict=True)
        ],
        forward_moneyness=None if forward is None else forward / curves.close,
    )


def session_bundle(
    symbol: str,
    session: date,
    quotes: pd.DataFrame,
    outcomes: pd.DataFrame,
    chosen: ChosenMap,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> SessionBundle:
    """Build the chain, distributions and heatmap of one session.

    Per expiration the CDF is ``chain_cdf`` at ``config.risk_free_apy``, and the calibrated
    CDF is ``apply_calibration`` of the chosen map. An expiration without a curve is still
    listed, with the reason. Expirations with fewer than ``config.min_dte_days`` days are
    shown and flagged ``short_dated``.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        quotes: Quote rows of this session only, as in ``sessions_summary``.
        outcomes: Settlement closes of the underlying: ``expiration``, ``settlement_date``
            and ``settlement_close`` (dollars).
        chosen: The calibration map to apply.
        config: Analytics parameters.

    Returns:
        The bundle. ``distribution.map_choice`` is ``auto``; the caller overrides it.
    """
    settled = {
        pd.Timestamp(e).date(): (pd.Timestamp(d).date(), float(c))
        for e, d, c in zip(
            outcomes["expiration"],
            outcomes["settlement_date"],
            outcomes["settlement_close"],
            strict=True,
        )
    }
    closes = quotes["underlying_close"].dropna()
    session_close = finite_or_none(closes.iloc[0]) if not closes.empty else None
    distributions: list[ExpiryDistribution] = []
    rows: list[HeatmapRow] = []
    curves: dict[date, ExpiryCurves] = {}
    for stamp, chain in quotes.groupby("expiration", sort=True, observed=True):
        expiration = pd.Timestamp(str(stamp)).date()
        dte_days = int(chain["dte_days"].iloc[0])
        exp_closes = chain["underlying_close"].dropna()
        close = finite_or_none(exp_closes.iloc[0]) if not exp_closes.empty else None
        cdf, reason = _build_cdf(dte_days, close, chain, session, expiration)
        outcome = settled.get(expiration)
        settlement_date = None if outcome is None else outcome[0]
        settlement_close = None if outcome is None else outcome[1]
        short_dated = dte_days < config.min_dte_days
        if cdf is None or close is None:
            n_usable = int(usable_mask(chain["bid"], chain["ask"]).sum())
            distributions.append(
                ExpiryDistribution(
                    expiration=expiration,
                    dte_days=dte_days,
                    years=_years(session, expiration),
                    forward=None,
                    underlying_close=close,
                    n_quotes=n_usable,
                    n_knots=0,
                    flags=[],
                    short_dated=short_dated,
                    curve=None,
                    unavailable_reason=reason,
                    settlement_date=settlement_date,
                    settlement_close=settlement_close,
                    prob_below_settlement=None,
                    prob_below_settlement_calibrated=None,
                )
            )
            continue
        cal = apply_calibration(cdf, chosen.cmap)
        curve = _curve(cdf, cal, close)
        expiry_curves = ExpiryCurves(expiration, close, cdf.forward, cdf, cal, curve)
        curves[expiration] = expiry_curves
        rows.append(_heatmap_row(expiration, dte_days, expiry_curves))
        distributions.append(
            ExpiryDistribution(
                expiration=expiration,
                dte_days=dte_days,
                years=cdf.years,
                forward=finite_or_none(cdf.forward),
                underlying_close=close,
                n_quotes=cdf.n_quotes,
                n_knots=int(cdf.strikes.shape[0]),
                flags=sorted(f.value for f in cdf.flags),
                short_dated=short_dated,
                curve=curve,
                unavailable_reason=None,
                settlement_date=settlement_date,
                settlement_close=settlement_close,
                prob_below_settlement=None if outcome is None else cdf.prob_below(outcome[1]),
                prob_below_settlement_calibrated=(
                    None if outcome is None else cal.prob_below(outcome[1])
                ),
            )
        )
    return SessionBundle(
        symbol=symbol,
        session=session,
        chain=_chain_response(symbol, session, quotes, session_close),
        distribution=DistributionResponse(
            symbol=symbol,
            session=session,
            map_choice="auto",
            map_id=chosen.map_id,
            map_is_identity=chosen.cmap.is_identity,
            map_train_max_expiration=chosen.train_max_expiration,
            look_ahead=chosen.look_ahead,
            risk_free_apy=config.risk_free_apy,
            expirations=distributions,
        ),
        heatmap=HeatmapResponse(
            symbol=symbol,
            session=session,
            map_id=chosen.map_id,
            moneyness=list(HEATMAP_MONEYNESS),
            backtest_grid=list(config.moneyness_grid),
            rows=rows,
        ),
        curves=curves,
    )
