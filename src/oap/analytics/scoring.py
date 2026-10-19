"""Score the latest session's put credit spreads with raw and calibrated probabilities.

For every underlying and expiration in the latest session the risk-neutral CDF comes from
``oap.analytics.sample.chain_cdf``, the same function the backtest uses, so the
calibration map is applied to the distribution it was trained on. Every candidate spread
is scored twice, once on the raw CDF and once on the CDF recomposed with the calibration
map, and ranked by calibrated annualised return on max loss.

Edge, fair credit and the alternative ranks. The fair credit is the expected payout of the
long put spread under the CDF, so the edge is the market mid credit minus that expected
payout under the *pooled* production map (``expected_payoff``; ``edge_raw`` uses the raw CDF).
It reads as the historical variance risk premium applied to this chain, plus whatever
mid-versus-natural gap the mid holds. It is not contract-specific mispricing, it is correlated
across the strikes and expiries of one underlying, the map is in-sample for the latest session
and comes from a hindsight universe (ADR 0010), and the largest edges sit in the far tail where
the map rests on the fewest breaches. ``rank`` keeps the return ordering. ``rank_edge`` and
``rank_rr`` order one guarded candidate set by edge as a share of the mid and by reward to
risk. ``pop_implied`` is ``max_loss / width``, the probability of profit the price implies
under the binary approximation (the credit and max loss are the odds), and ``pop_gap`` is the
calibrated probability of profit minus it: the probability-space twin of ``edge_pct``, positive
when the market pays more than the calibrated probability justifies. ``pop_gap_raw`` is the
same under the risk-neutral CDF and is the control: it is near 0 except for partial-loss and
interest effects. ``rank_entry`` is the "Top to enter" ranking and follows one rule, printed by the
API and the report from ``ENTRY_RULE``: a spread passes every guard (eligible, calibrated POP
at least ``entry_min_pop``, credit at least ``min_edge_credit``, natural credit at least
``min_natural_fraction`` of the mid with a positive natural edge, inside the quoted strikes,
none of the tail, sparse or unknown-forward flags) and is ranked by annualised return on max
loss, then reward to risk. It ranks a historical calibration; it is not trade advice.

Units: prices, strikes, credits and losses are in dollars per share; ``years`` is in
years (calendar days / 365); rates are decimal APYs; probabilities are decimals in [0, 1];
returns on max loss are decimals (0.02 is 2%) over the holding period, or per year when
annualised; fair credits, edges and payoff standard deviations are dollars per share.
Collateral equals the maximum loss for a cash-secured spread, so the engine's
``expected_return_on_collateral``, stored as ``expected_roc``, is the expected return on max
loss.
"""

import math
from typing import Final, cast

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
from oap.engine.implied_distribution import QualityFlag, RiskNeutralCdf, usable_quotes
from oap.engine.spread_scoring import (
    RankBy,
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
    "fair_credit",
    "fair_credit_raw",
    "edge",
    "edge_raw",
    "edge_natural",
    "edge_pct",
    "edge_pop",
    "pop_implied",
    "pop_gap",
    "pop_gap_raw",
    "payoff_std",
    "reward_to_risk",
    "calibrated",
    "extrapolated",
    "flags",
    "eligible",
    "rank",
    "rank_edge",
    "rank_rr",
    "rank_entry",
    "map_id",
    "cash_apy",
    "risk_free_apy",
)

ENTRY_RULE: Final = (
    "Passes every guard (eligible, "
    f"calibrated POP \u2265 {DEFAULT_CONFIG.entry_min_pop:.0%}, "
    f"credit \u2265 ${DEFAULT_CONFIG.min_edge_credit:.2f}, "
    f"natural credit \u2265 {DEFAULT_CONFIG.min_natural_fraction:.0%} of mid "
    "with positive natural edge, inside quoted strikes, no tail flags), "
    "ranked by annualised return on max loss, then reward/risk."
)
"""One sentence stating the entry ranking, with the thresholds of ``DEFAULT_CONFIG``."""

_ENTRY_BLOCKING_FLAGS: Final = frozenset(
    {
        QualityFlag.LEFT_TAIL_UNCOVERED,
        QualityFlag.RIGHT_TAIL_UNCOVERED,
        QualityFlag.SPARSE,
        QualityFlag.FORWARD_UNKNOWN,
    }
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
        Row dictionaries (without ``eligible`` and the ranks) and the calibrated scores in
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
                "fair_credit": cal.fair_credit,
                "fair_credit_raw": raw.fair_credit,
                "edge": cal.expected_payoff,
                "edge_raw": raw.expected_payoff,
                "edge_natural": natural - cal.fair_credit,
                "edge_pct": cal.edge_pct,
                "edge_pop": cal.prob_profit - raw.prob_profit,
                "pop_implied": spread.pop_implied,
                "pop_gap": cal.prob_profit - spread.pop_implied,
                "pop_gap_raw": raw.prob_profit - spread.pop_implied,
                "payoff_std": cal.payoff_std,
                "reward_to_risk": cal.reward_to_risk,
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
    a null rank. ``rank_edge``, ``rank_rr`` and ``rank_entry`` are described in
    ``_with_ranks``.

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
    return _with_ranks(rows, scores, config)


def _entry_key(score: SpreadScore) -> tuple[float, float, float, float, float, float]:
    """Return the sort key of the entry ranking, smallest first.

    Args:
        score: Calibrated score.

    Returns:
        Negated annualised return, a nan flag and negated reward to risk (nan last),
        negated probability of profit, negated short strike in dollars and long strike in
        dollars.
    """
    rr = score.reward_to_risk
    return (
        -score.annualised_return,
        float(math.isnan(rr)),
        0.0 if math.isnan(rr) else -rr,
        -score.prob_profit,
        -score.spread.short_strike,
        score.spread.long_strike,
    )


def _assign(ranks: list[int | None], ordered: list[int]) -> None:
    """Write ranks 1..k for row positions given best first.

    Args:
        ranks: Rank per row position, updated in place.
        ordered: Row positions, best first.
    """
    for rank, index in enumerate(ordered, start=1):
        ranks[index] = rank


def _with_ranks(
    rows: list[dict[str, object]], scores: list[SpreadScore], config: AnalyticsConfig
) -> pd.DataFrame:
    """Rank the eligible spreads and build the frame.

    ``rank`` is 1..k over the eligible rows in ``rank_spreads`` order. The candidate set of
    the alternative ranks is the eligible rows with ``credit >= min_edge_credit`` and
    ``credit_natural >= min_natural_fraction * credit``; ``rank_edge`` and ``rank_rr`` are
    1..k over it in ``rank_spreads(by="edge")`` and ``rank_spreads(by="reward_to_risk")``
    order. ``rank_entry`` is 1..k over the candidates that also have a calibrated
    probability of profit of at least ``entry_min_pop``, a positive natural edge (dollars per
    share) and none of the CDF's tail, sparse or unknown-forward flags, in ``_entry_key``
    order. Every rank is null outside its set.

    Args:
        rows: Row dictionaries, each with a boolean ``eligible``.
        scores: Calibrated scores in the same order as ``rows``.
        config: Analytics parameters.

    Returns:
        The frame with ``SPREAD_COLUMNS``.
    """
    position = {id(score): i for i, score in enumerate(scores)}
    columns: dict[str, list[int | None]] = {
        name: [None] * len(rows) for name in ("rank", "rank_edge", "rank_rr", "rank_entry")
    }
    eligible = [i for i, row in enumerate(rows) if row["eligible"]]
    _assign(columns["rank"], [position[id(s)] for s in rank_spreads(scores[i] for i in eligible)])
    credit = [cast(float, row["credit"]) for row in rows]
    natural = [cast(float, row["credit_natural"]) for row in rows]
    natural_edge = [cast(float, row["edge_natural"]) for row in rows]
    guarded = [
        i
        for i in eligible
        if credit[i] >= config.min_edge_credit
        and natural[i] >= config.min_natural_fraction * credit[i]
    ]
    alternatives: tuple[tuple[str, RankBy], ...] = (
        ("rank_edge", "edge"),
        ("rank_rr", "reward_to_risk"),
    )
    for name, by in alternatives:
        _assign(
            columns[name],
            [position[id(s)] for s in rank_spreads((scores[i] for i in guarded), by=by)],
        )
    entry = [
        i
        for i in guarded
        if scores[i].prob_profit >= config.entry_min_pop
        and natural_edge[i] > 0
        and not scores[i].extrapolated
        and not scores[i].flags & _ENTRY_BLOCKING_FLAGS
    ]
    _assign(columns["rank_entry"], sorted(entry, key=lambda i: _entry_key(scores[i])))
    frame = pd.DataFrame(rows)
    for name, ranks in columns.items():
        frame[name] = pd.array(ranks, dtype="Int64")
    return frame[list(SPREAD_COLUMNS)]
