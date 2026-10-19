"""Score the latest session's put credit spreads with raw and calibrated probabilities.

For every underlying and expiration in the latest session the risk-neutral CDF comes from
``oap.analytics.sample.chain_cdf``, the same function the backtest uses, so the
calibration map is applied to the distribution it was trained on. Every candidate spread
is scored twice, once on the raw CDF and once on the CDF recomposed with the calibration
map, and ranked by calibrated annualised return on collateral.

Units: prices, strikes, credits and losses are in dollars per share; ``years`` is in
years (calendar days / 365); rates are decimal APYs; probabilities are decimals in [0, 1];
returns on collateral are decimals (0.02 is 2%) over the holding period, or per year when
annualised.
"""

from typing import Final

import numpy as np
import pandas as pd

from oap.analytics.config import DEFAULT_CONFIG, PRODUCTION_MAP_ID, AnalyticsConfig
from oap.analytics.sample import (
    QUOTE_COLUMNS,
    SNAPSHOT_KEY,
    chain_cdf,
    empty_frame,
    require_columns,
    usable_mask,
)
from oap.engine.calibration import CalibrationMap, apply_calibration
from oap.engine.conventions import dte_years
from oap.engine.implied_distribution import RiskNeutralCdf, usable_quotes
from oap.engine.spread_scoring import (
    SpreadScore,
    enumerate_spreads,
    rank_spreads,
    score_spread,
)

SPREAD_COLUMNS: Final[tuple[str, ...]] = (
    "spread_key",
    "underlying",
    "trade_date",
    "expiration",
    "dte_days",
    "years",
    "underlying_close",
    "short_strike",
    "long_strike",
    "width",
    "credit",
    "credit_natural",
    "max_loss",
    "breakeven",
    "short_moneyness",
    "prob_profit",
    "prob_profit_raw",
    "prob_max_loss",
    "expected_payoff",
    "interest",
    "expected_roc",
    "expected_roc_raw",
    "annualised_roc",
    "annualised_roc_raw",
    "kelly_fraction",
    "calibrated",
    "extrapolated",
    "flags",
    "eligible",
    "rank",
    "map_id",
    "cash_apy",
    "risk_free_apy",
)


def _natural_credits(puts: pd.DataFrame, shorts: list[float], longs: list[float]) -> list[float]:
    """Return the credit at fillable prices for each spread.

    Args:
        puts: Put quotes of one expiry, with ``strike`` (dollars), ``bid`` and ``ask``
            (dollars per share).
        shorts: Short strikes in dollars, one per spread.
        longs: Long strikes in dollars, one per spread.

    Returns:
        ``bid(short) - ask(long)`` in dollars per share for each spread.
    """
    usable = puts.loc[usable_mask(puts["bid"], puts["ask"])]
    bid = dict(zip(usable["strike"].tolist(), usable["bid"].tolist(), strict=True))
    ask = dict(zip(usable["strike"].tolist(), usable["ask"].tolist(), strict=True))
    return [bid[s] - ask[lo] for s, lo in zip(shorts, longs, strict=True)]


def _expiry_rows(
    chain: pd.DataFrame,
    cdf: RiskNeutralCdf,
    calibrated_cdf: RiskNeutralCdf,
    cmap: CalibrationMap,
    map_id: str,
    config: AnalyticsConfig,
) -> tuple[list[dict[str, object]], list[SpreadScore]]:
    """Score every candidate spread of one expiry.

    Args:
        chain: Quote rows of the snapshot.
        cdf: Raw risk-neutral CDF of the snapshot.
        calibrated_cdf: ``cdf`` recomposed with ``cmap``.
        cmap: Calibration map.
        map_id: Identifier of the map.
        config: Analytics parameters.

    Returns:
        Row dictionaries (without ``eligible`` and ``rank``) and the calibrated scores in
        the same order.
    """
    first = chain.iloc[0]
    underlying = str(first["underlying"])
    trade_date = pd.Timestamp(first["trade_date"])
    expiration = pd.Timestamp(first["expiration"])
    close = float(first["underlying_close"])
    puts = chain.loc[chain["option_right"] == "P"]
    strikes, mids = usable_quotes(puts["strike"], puts["bid"], puts["ask"])
    spreads = enumerate_spreads(
        underlying,
        expiration.date(),
        cdf.years,
        strikes,
        mids,
        max_width=config.max_width_fraction * close,
        min_credit=config.min_credit,
    )
    naturals = _natural_credits(
        puts, [s.short_strike for s in spreads], [s.long_strike for s in spreads]
    )
    rows: list[dict[str, object]] = []
    scores: list[SpreadScore] = []
    for spread, natural in zip(spreads, naturals, strict=True):
        raw = score_spread(spread, cdf, cash_apy=config.cash_apy)
        cal = score_spread(spread, calibrated_cdf, cash_apy=config.cash_apy)
        scores.append(cal)
        eligible = (
            not cal.extrapolated
            and natural > 0
            and spread.short_strike < close
            and cal.prob_profit >= config.min_prob_profit
        )
        rows.append(
            {
                "spread_key": (
                    f"{underlying}|{trade_date.date()}|{expiration.date()}"
                    f"|{spread.short_strike:.3f}|{spread.long_strike:.3f}"
                ),
                "underlying": underlying,
                "trade_date": trade_date,
                "expiration": expiration,
                "dte_days": int(first["dte_days"]),
                "years": spread.years,
                "underlying_close": close,
                "short_strike": spread.short_strike,
                "long_strike": spread.long_strike,
                "width": spread.width,
                "credit": spread.credit,
                "credit_natural": natural,
                "max_loss": spread.max_loss,
                "breakeven": spread.breakeven,
                "short_moneyness": spread.short_strike / close,
                "prob_profit": cal.prob_profit,
                "prob_profit_raw": raw.prob_profit,
                "prob_max_loss": cal.prob_max_loss,
                "expected_payoff": cal.expected_payoff,
                "interest": cal.interest,
                "expected_roc": cal.expected_return_on_collateral,
                "expected_roc_raw": raw.expected_return_on_collateral,
                "annualised_roc": cal.annualised_return,
                "annualised_roc_raw": raw.annualised_return,
                "kelly_fraction": cal.kelly_fraction,
                "calibrated": not cmap.is_identity,
                "extrapolated": cal.extrapolated,
                "eligible": eligible,
                "flags": ",".join(sorted(f.value for f in cdf.flags)),
                "map_id": map_id,
                "cash_apy": config.cash_apy,
                "risk_free_apy": config.risk_free_apy,
            }
        )
    return rows, scores


def score_latest_session(
    quotes: pd.DataFrame,
    cmap: CalibrationMap,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    *,
    map_id: str = PRODUCTION_MAP_ID,
) -> pd.DataFrame:
    """Score and rank every put credit spread in the given quotes.

    Per ``(underlying, trade_date, expiration)`` the CDF comes from ``chain_cdf``;
    spreads are those of ``enumerate_spreads`` on usable put mids with width at most
    ``max_width_fraction`` of the close and mid credit at least ``min_credit``. Each is
    scored on the raw CDF and on the CDF recomposed with ``cmap`` (once per expiry, which
    gives the same numbers as ``score_spread(..., calibration=cmap)`` per spread).
    Snapshots with fewer than ``min_dte_days``, a null or non-positive close, or fewer
    than four usable puts are skipped.

    A spread is eligible when its long strike is inside the CDF's knots (not
    extrapolated), the natural credit (short bid minus long ask, dollars per share) is
    positive, the short strike is below the close, and the calibrated probability of
    profit is at least ``min_prob_profit``. Eligible spreads are ranked 1..k across all
    expiries by ``rank_spreads`` order (calibrated annualised return first); the rest have
    a null rank.

    Args:
        quotes: Quote rows as in ``classify_snapshots``, normally the global latest session
            from ``oap.analytics.io.read_latest_quotes``.
        cmap: Calibration map; the identity map gives calibrated equal to raw.
        config: Analytics parameters.
        map_id: Identifier recorded on every row.

    Returns:
        One row per spread with ``SPREAD_COLUMNS``, sorted by underlying, expiration and
        strikes. ``rank`` is a nullable integer; ``flags`` are the raw CDF's quality
        flags. Empty if nothing could be scored.

    Raises:
        ValueError: If a required column is missing.
        EngineInputError: If the engine rejects a chain.
    """
    require_columns(quotes, QUOTE_COLUMNS, "quotes")
    rows: list[dict[str, object]] = []
    scores: list[SpreadScore] = []
    for _, chain in quotes.groupby(list(SNAPSHOT_KEY), sort=True):
        first = chain.iloc[0]
        close = float(first["underlying_close"])
        if int(first["dte_days"]) < config.min_dte_days or not (np.isfinite(close) and close > 0):
            continue
        years = dte_years(
            pd.Timestamp(first["trade_date"]).date(), pd.Timestamp(first["expiration"]).date()
        )
        cdf = chain_cdf(chain, years=years, rate=config.risk_free_apy)
        if cdf is None:
            continue
        part_rows, part_scores = _expiry_rows(
            chain, cdf, apply_calibration(cdf, cmap), cmap, map_id, config
        )
        rows.extend(part_rows)
        scores.extend(part_scores)
    if not rows:
        return empty_frame(SPREAD_COLUMNS)
    return _with_ranks(rows, scores)


def _with_ranks(rows: list[dict[str, object]], scores: list[SpreadScore]) -> pd.DataFrame:
    """Rank the eligible spreads and build the frame.

    Args:
        rows: Row dictionaries, each with a boolean ``eligible``.
        scores: Calibrated scores in the same order as ``rows``.

    Returns:
        The frame with ``SPREAD_COLUMNS``; ``rank`` is 1..k over the eligible rows in
        ``rank_spreads`` order and null elsewhere.
    """
    position = {id(score): i for i, score in enumerate(scores)}
    ranks: list[int | None] = [None] * len(rows)
    candidates = [score for row, score in zip(rows, scores, strict=True) if row["eligible"]]
    for rank, score in enumerate(rank_spreads(candidates), start=1):
        ranks[position[id(score)]] = rank
    frame = pd.DataFrame(rows)
    frame["rank"] = pd.array(ranks, dtype="Int64")
    return frame[list(SPREAD_COLUMNS)]
