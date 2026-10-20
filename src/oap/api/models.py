"""Response models of the explorer API.

Units: strikes, prices, credits and closes are in dollars per share ($/sh); implied volatility
is a decimal (0.20, not 20%); probabilities and returns on max loss are decimals in [0, 1]
(returns may leave that range); densities are probability per dollar (1/$); times are in
calendar days or in years (ACT/365).

Any float that can be non-finite in the gold tables is typed ``float | None`` and converted
to ``None`` in code. ``ser_json_inf_nan="null"`` is the second line of defence: a stray
infinity or NaN serialises as ``null`` instead of producing invalid JSON.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ErrorCode = Literal[
    "database_busy",
    "database_missing",
    "gold_missing",
    "not_found",
    "invalid",
    "view_required",
    "view_invalid",
    "no_distribution",
    "no_implied_vol",
]
SpreadSort = Literal["return", "edge", "reward_to_risk", "kelly", "pop", "pop_gap", "entry"]
MapChoice = Literal["auto", "production", "walk_forward"]
StructureKind = Literal[
    "long_call",
    "long_put",
    "bull_call_spread",
    "bear_put_spread",
    "bull_put_spread",
    "bear_call_spread",
    "long_straddle",
    "long_strangle",
    "iron_condor",
]
"""Structure kinds in the order of the spec table; the values of the engine's StructureKind."""
Direction = Literal["up", "down", "move", "range"]
"""The outcome a structure kind is built for."""
Fill = Literal["natural", "mid"]
"""natural: long legs at the ask and short legs at the bid; mid: every leg at the mid."""
PresetId = Literal["up", "up_moderate", "flat", "down_moderate", "down", "big_move"]
"""Quantile-based outcome presets, the ids of ``oap.analytics.views.PRESETS``."""


class ApiModel(BaseModel):
    """Base class of every response model: immutable, with non-finite floats as null."""

    model_config = ConfigDict(
        frozen=True,
        ser_json_inf_nan="null",
        json_schema_serialization_defaults_required=True,
    )


class HealthResponse(ApiModel):
    """State of the service and of the database file."""

    status: Literal["ok"] = Field(description="Always ok: the process is up.")
    db: Literal["ok", "busy", "missing"] = Field(
        description="ok when the file can be read, busy when a writer holds the lock, "
        "missing when the file does not exist."
    )
    db_path: str = Field(
        description="File name of the DuckDB file the service reads, without its directory."
    )
    last_good_signature_at: datetime | None = Field(
        description="UTC time at which the data in memory was last loaded from the file."
    )


class Underlying(ApiModel):
    """An underlying with the sessions available for it."""

    symbol: str = Field(description="Ticker symbol, such as SPY.")
    sector: str = Field(description="Sector label from gold.dim_underlying.")
    first_session: date = Field(description="First trade date with quotes.")
    last_session: date = Field(description="Last trade date with quotes.")
    n_sessions: int = Field(description="Number of trade dates with quotes.")


class UnderlyingsResponse(ApiModel):
    """All underlyings and the latest session of the whole table."""

    underlyings: list[Underlying]
    latest_session: date = Field(description="Latest trade date over all underlyings.")


class SessionSummary(ApiModel):
    """One trade date of an underlying."""

    session: date = Field(description="Trade date.")
    underlying_close: float | None = Field(description="Underlying close in dollars ($/sh).")
    n_expirations: int = Field(description="Number of expirations quoted.")
    n_quotes: int = Field(description="Number of option quotes, puts and calls.")
    atm_iv: float | None = Field(
        description="At-the-money implied volatility as a decimal: the out-of-the-money put "
        "with the smallest |moneyness - 1| and a positive source IV, in the shortest "
        "expiration with at least 7 days to expiry."
    )


class SessionsResponse(ApiModel):
    """The sessions of one underlying, ascending."""

    symbol: str
    sessions: list[SessionSummary]


class ChainQuote(ApiModel):
    """One option quote."""

    strike: float = Field(description="Strike in dollars ($/sh).")
    option_right: Literal["C", "P"] = Field(description="C for a call, P for a put.")
    bid: float | None = Field(description="Bid in dollars per share ($/sh).")
    ask: float | None = Field(description="Ask in dollars per share ($/sh).")
    mid: float | None = Field(description="Mid in dollars per share ($/sh).")
    iv: float | None = Field(
        description="Source implied volatility as a decimal; null when not positive."
    )
    delta: float | None = Field(description="Source delta (dimensionless).")
    moneyness: float | None = Field(description="Strike divided by the underlying close.")
    usable: bool = Field(
        description="True when the engine keeps the quote: finite, bid > 0 and ask >= bid."
    )


class ChainExpiry(ApiModel):
    """The quotes of one expiration, strike ascending, calls before puts."""

    expiration: date
    dte_days: int = Field(description="Calendar days from the session to expiration.")
    quotes: list[ChainQuote]


class ChainResponse(ApiModel):
    """The option chain of one session."""

    symbol: str
    session: date
    underlying_close: float | None = Field(description="Underlying close in dollars ($/sh).")
    expirations: list[ChainExpiry]


class DistributionCurve(ApiModel):
    """The risk-neutral CDF and density of one expiration, evaluated at the raw knots."""

    knots: list[float] = Field(description="Raw CDF knots: strikes in dollars ($/sh).")
    moneyness: list[float] = Field(description="Knots divided by the underlying close.")
    cdf: list[float] = Field(description="Raw risk-neutral P(S < K) after repair, in [0, 1].")
    raw_cdf: list[float] = Field(
        description="P(S < K) before monotonicity repair and clipping; may leave [0, 1]."
    )
    cdf_calibrated: list[float] = Field(
        description="Calibrated P(S < K) at the raw knots, in [0, 1]."
    )
    density_mid: list[float] = Field(description="Midpoints between knots in dollars ($/sh).")
    density: list[float] = Field(description="Raw probability density between knots (1/$).")
    density_calibrated: list[float] = Field(
        description="Calibrated probability density between knots (1/$)."
    )


class ExpiryDistribution(ApiModel):
    """The distribution of one expiration, or the reason there is none."""

    expiration: date
    dte_days: int = Field(description="Calendar days from the session to expiration.")
    years: float = Field(description="Time to expiration in years (ACT/365).")
    forward: float | None = Field(description="Forward price in dollars ($/sh); null if unknown.")
    underlying_close: float | None = Field(description="Underlying close in dollars ($/sh).")
    n_quotes: int = Field(description="Number of usable quotes behind the curve.")
    n_knots: int = Field(description="Number of raw CDF knots; 0 without a curve.")
    flags: list[str] = Field(description="Sorted quality flags of the raw CDF.")
    short_dated: bool = Field(description="True below the backtest's minimum days to expiry.")
    curve: DistributionCurve | None
    unavailable_reason: str | None = Field(
        description="Why there is no curve: expired, no_close, too_few_puts or "
        "engine_error: <message>."
    )
    settlement_date: date | None = Field(description="Settlement date when the expiry settled.")
    settlement_close: float | None = Field(description="Settlement close in dollars ($/sh).")
    prob_below_settlement: float | None = Field(
        description="Raw P(S < settlement close), a decimal. None when the settlement is "
        "outside the quoted strikes; the CDF is not extrapolated."
    )
    prob_below_settlement_calibrated: float | None = Field(
        description="Calibrated P(S < settlement close), a decimal. None when the "
        "settlement is outside the quoted strikes; the CDF is not extrapolated."
    )


class DistributionResponse(ApiModel):
    """The distributions of every expiration of one session."""

    symbol: str
    session: date
    map_choice: MapChoice = Field(description="The map selection that was requested.")
    map_id: str = Field(description="The calibration map that was applied.")
    map_is_identity: bool = Field(description="True when the map leaves probabilities unchanged.")
    map_train_max_expiration: date | None = Field(
        description="Latest expiration among the map's training outcomes."
    )
    look_ahead: bool = Field(
        description="True when the map was fitted on outcomes that settle after this session."
    )
    risk_free_apy: float = Field(description="Risk-free rate used for every CDF, decimal APY.")
    expirations: list[ExpiryDistribution]


class HeatmapRow(ApiModel):
    """P(S < K) across the display grid for one expiration."""

    expiration: date
    dte_days: int = Field(description="Calendar days from the session to expiration.")
    target_strikes: list[float] = Field(description="Strikes in dollars ($/sh), one per column.")
    prob_below: list[float | None] = Field(
        description="Raw P(S < K) per column; null outside the quoted strikes."
    )
    prob_below_calibrated: list[float | None] = Field(
        description="Calibrated P(S < K) per column; null outside the quoted strikes."
    )
    forward_moneyness: float | None = Field(description="Forward divided by the close.")


class HeatmapResponse(ApiModel):
    """The probability heatmap of one session."""

    symbol: str
    session: date
    map_id: str
    moneyness: list[float] = Field(description="Display grid: strike divided by the close.")
    backtest_grid: list[float] = Field(description="The backtest's moneyness grid, for ticks.")
    rows: list[HeatmapRow]


class SpreadRow(ApiModel):
    """One scored put credit spread."""

    spread_key: str = Field(description="Underlying|session|expiration|short|long.")
    underlying: str
    expiration: date
    dte_days: int = Field(description="Calendar days from the session to expiration.")
    short_strike: float = Field(description="Strike of the sold put in dollars ($/sh).")
    long_strike: float = Field(description="Strike of the bought put in dollars ($/sh).")
    width: float = Field(description="Short minus long strike in dollars ($/sh).")
    credit: float = Field(description="Mid credit in dollars per share ($/sh).")
    credit_natural: float = Field(description="Short bid minus long ask in dollars ($/sh).")
    max_loss: float = Field(description="Width minus credit in dollars per share ($/sh).")
    breakeven: float = Field(description="Short strike minus credit in dollars ($/sh).")
    short_moneyness: float = Field(description="Short strike divided by the close.")
    prob_profit: float = Field(description="Calibrated probability of profit, a decimal.")
    prob_profit_raw: float = Field(description="Raw probability of profit, a decimal.")
    prob_max_loss: float = Field(description="Calibrated probability of the maximum loss.")
    expected_roc: float = Field(
        description="Calibrated expected return on max loss (collateral) over the holding period."
    )
    expected_roc_raw: float = Field(
        description="Raw expected return on max loss (collateral) over the holding period."
    )
    annualised_roc: float | None = Field(
        description="Calibrated annualised return on max loss (collateral); null when not finite."
    )
    kelly_fraction: float = Field(description="Kelly fraction of capital, a decimal in [0, 1].")
    fair_credit: float = Field(
        description="Calibrated fair credit in dollars per share ($/sh): the expected payout of "
        "the long put spread, undiscounted, between 0 and the width."
    )
    edge: float = Field(
        description="Mid credit minus the calibrated fair credit in dollars per share ($/sh)."
    )
    edge_natural: float = Field(
        description="Natural credit minus the calibrated fair credit in dollars per share ($/sh)."
    )
    edge_pct: float = Field(description="Edge as a decimal share of the mid credit, at most 1.")
    edge_pop: float = Field(
        description="Calibrated minus raw probability of profit, a decimal in [-1, 1]."
    )
    pop_implied: float = Field(
        description="Probability of profit implied by the price (max loss divided by width), "
        "a decimal in [0, 1]."
    )
    pop_gap: float = Field(
        description="Calibrated probability of profit minus pop_implied, a decimal; positive "
        "when the market pays more than the calibrated probability justifies."
    )
    payoff_std: float = Field(
        description="Standard deviation of the spread payoff in dollars per share ($/sh), "
        "between 0 and half the width."
    )
    reward_to_risk: float | None = Field(
        description="Expected payoff divided by payoff_std, per trade and not annualised; null "
        "when payoff_std is 0."
    )
    eligible: bool = Field(description="True when the spread passes the eligibility rules.")
    rank: int | None = Field(description="1 is best among eligible spreads; null otherwise.")
    rank_edge: int | None = Field(
        description="1 is best by edge_pct among guarded eligible spreads; null otherwise."
    )
    rank_rr: int | None = Field(
        description="1 is best by reward_to_risk among guarded eligible spreads; null otherwise."
    )
    rank_entry: int | None = Field(
        description="1 is best in the Top to enter ranking (see entry_rule); null otherwise."
    )
    score_entry: float | None = Field(
        description="The entry ranking's score: annualised return on max loss at the natural "
        "credit with the calibrated POP shrunk halfway toward pop_implied, a decimal per year; "
        "rank_entry orders by it; null when not finite."
    )
    extrapolated: bool = Field(description="True when the long strike is outside the CDF knots.")
    flags: list[str] = Field(description="Quality flags of the raw CDF.")


class SpreadsResponse(ApiModel):
    """Scored spreads after the filters, with the facets of the whole table."""

    as_of: date | None = Field(description="Session the scores were computed for.")
    source: Literal["gold", "recomputed"] = Field(description="Where the scores come from.")
    total: int = Field(description="Rows in gold.spread_scores.")
    matched: int = Field(description="Rows that match the filters, before the limit.")
    min_prob_profit: float = Field(description="Eligibility threshold on prob_profit (config).")
    underlyings: list[str] = Field(description="Underlyings in the table, ascending.")
    expirations: list[date] = Field(description="Expirations in the table, ascending.")
    sort: SpreadSort = Field(description="The order of rows.")
    entry_rule: str = Field(description="The rule behind rank_entry, in one sentence.")
    entry_evidence: str = Field(
        description="How the entry rule tested on the rule lab's hold-out, in one sentence."
    )
    rows: list[SpreadRow] = Field(description="Rows ordered by sort.")


class PayoffPoint(ApiModel):
    """The payoff of a spread at one expiry price."""

    price: float = Field(description="Underlying price at expiry in dollars ($/sh).")
    payoff: float = Field(description="Payoff at expiry in dollars per share, before interest.")


class RawCalibrated(ApiModel):
    """A probability on the raw and on the calibrated distribution."""

    raw: float = Field(description="Probability on the raw CDF, a decimal.")
    calibrated: float = Field(description="Probability on the calibrated CDF, a decimal.")


class SpreadRegions(ApiModel):
    """Probabilities of the three payoff regions of a put credit spread."""

    prob_max_loss: RawCalibrated = Field(description="P(S <= long strike).")
    prob_partial_loss: RawCalibrated = Field(description="P(long strike < S < breakeven).")
    prob_profit: RawCalibrated = Field(description="P(S >= breakeven).")


class SpreadDetail(SpreadRow):
    """A spread with every gold column, its payoff curve and the densities behind it."""

    trade_date: date = Field(description="Session the spread was scored on.")
    years: float = Field(description="Time to expiration in years (ACT/365).")
    underlying_close: float = Field(description="Underlying close in dollars ($/sh).")
    expected_payoff: float = Field(description="Calibrated expected payoff in dollars ($/sh).")
    fair_credit_raw: float = Field(
        description="Fair credit under the raw risk-neutral CDF in dollars per share ($/sh)."
    )
    edge_raw: float = Field(
        description="Mid credit minus the raw fair credit in dollars per share ($/sh)."
    )
    pop_gap_raw: float = Field(
        description="Raw probability of profit minus pop_implied, a decimal; the control for "
        "pop_gap."
    )
    interest: float = Field(description="Interest on the collateral in dollars ($/sh).")
    annualised_roc_raw: float | None = Field(
        description="Raw annualised return on max loss (collateral); null when not finite."
    )
    calibrated: bool = Field(description="True when a non-identity map was applied.")
    map_id: str = Field(description="Calibration map the scores were computed with.")
    cash_apy: float = Field(description="Interest rate on the collateral, decimal APY.")
    risk_free_apy: float = Field(description="Risk-free rate used for the CDF, decimal APY.")
    forward: float | None = Field(description="Forward price in dollars ($/sh); null if unknown.")
    payoff: list[PayoffPoint]
    density_mid: list[float] = Field(description="Midpoints between knots in dollars ($/sh).")
    density_raw: list[float] = Field(description="Raw probability density (1/$).")
    density_calibrated: list[float] = Field(description="Calibrated probability density (1/$).")
    regions: SpreadRegions
    knot_range: tuple[float, float] = Field(
        description="Lowest and highest CDF knot in dollars ($/sh)."
    )


class MetricValue(ApiModel):
    """One out-of-sample calibration metric."""

    metric: str = Field(
        description="Metric name in gold.calibration_metrics: brier_score, log_loss or "
        "expected_calibration_error."
    )
    variant: Literal["raw", "calibrated", "delta"]
    value: float | None
    ci_low: float | None = Field(description="Lower end of the 95% cluster-bootstrap interval.")
    ci_high: float | None = Field(description="Upper end of the 95% cluster-bootstrap interval.")


class CalibrationSummary(ApiModel):
    """The production map and the out-of-sample evidence for it."""

    map_id: str = Field(description="The production map.")
    n_samples: int = Field(description="Outcomes the production map was fitted on.")
    train_max_expiration: date | None = Field(description="Latest expiration it was fitted on.")
    first_test_year: int = Field(description="First calendar year counted as out of sample.")
    n_predictions: int = Field(description="Out-of-sample predictions behind the metrics.")
    n_snapshots: int = Field(description="Out-of-sample chain snapshots behind the metrics.")
    n_clusters: int = Field(description="Expiration dates resampled by the bootstrap.")
    metrics: list[MetricValue]


class ErrorBody(ApiModel):
    """The body of every error response."""

    detail: str
    code: ErrorCode


class TailInfo(ApiModel):
    """The lognormal tails that complete the distribution outside the outer knots."""

    sigma_lo: float = Field(description="Volatility of the lower tail, a decimal (0.20 = 20%).")
    sigma_hi: float = Field(description="Volatility of the upper tail, a decimal (0.20 = 20%).")
    mass_lo: float = Field(
        description="Calibrated probability below the lowest knot, a decimal in [0, 1]."
    )
    mass_hi: float = Field(
        description="Calibrated probability above the highest knot, a decimal in [0, 1]."
    )
    location: float = Field(
        description="Centre of the lognormal tails in dollars ($/sh): the forward, or the "
        "calibrated median when the forward is unknown."
    )


class ViewInfo(ApiModel):
    """The outcome the structures are measured against, resolved to prices."""

    preset: PresetId | None = Field(description="The preset id; null for a custom range.")
    lo: float | None = Field(
        description="Lower bound of the range in dollars ($/sh), inclusive; null when open."
    )
    hi: float | None = Field(
        description="Upper bound of the range in dollars ($/sh), exclusive; null when open."
    )
    outside: bool = Field(
        description="True when the outcome is the price landing outside [lo, hi) (a big move)."
    )
    lo_moneyness: float | None = Field(description="lo divided by the underlying close.")
    hi_moneyness: float | None = Field(description="hi divided by the underlying close.")
    prob: float = Field(
        description="Probability of the outcome under the calibrated, tail-completed "
        "distribution, a decimal in [0, 1]."
    )
    prob_market: float = Field(
        description="Probability of the outcome under the raw (market-implied) risk-neutral "
        "distribution with the same tails, a decimal in [0, 1]."
    )


class StructureRow(ApiModel):
    """One scored structure; profit and loss is per share at expiry, undiscounted."""

    kind: StructureKind = Field(description="The structure kind.")
    direction: Direction = Field(description="The outcome the kind is built for.")
    legs: str = Field(
        description="Legs as signed quantity, right and strike in dollars, such as "
        "'-1 P 250 / +1 P 245'."
    )
    strikes: list[float] = Field(description="Distinct strikes in dollars ($/sh), ascending.")
    net_premium: float = Field(
        description="Net premium in dollars per share ($/sh) at the fill: positive is a debit "
        "paid, negative a credit received."
    )
    max_loss: float = Field(
        description="Largest loss at expiry in dollars per share ($/sh), positive; the capital "
        "at risk."
    )
    max_gain: float | None = Field(
        description="Largest gain at expiry in dollars per share ($/sh); null when unbounded."
    )
    breakevens: list[float] = Field(
        description="Prices at expiry in dollars ($/sh) where profit and loss crosses zero, "
        "ascending."
    )
    prob_profit: float = Field(
        description="Calibrated probability that profit and loss at expiry is positive, a decimal."
    )
    expected_return: float = Field(
        description="Expected profit and loss divided by max loss (return on max loss) over the "
        "holding period, a decimal; no interest on the capital at risk."
    )
    annualised_return: float | None = Field(
        description="expected_return compounded to one year, a decimal; null when not finite."
    )
    reward_to_risk: float | None = Field(
        description="Expected profit and loss divided by its standard deviation, per trade and "
        "not annualised; null when the standard deviation is 0."
    )
    prob_profit_given_view: float | None = Field(
        description="Calibrated probability of a profit given the outcome, a decimal; null when "
        "the outcome has probability 0."
    )
    return_if_right: float | None = Field(
        description="Expected profit and loss given the outcome, divided by max loss (return on "
        "max loss), a decimal; null when the outcome has probability 0."
    )
    return_if_wrong: float | None = Field(
        description="Expected profit and loss given the price lands outside the outcome, divided "
        "by max loss, a decimal; null when the outcome has probability 1."
    )
    worst_in_view: float | None = Field(
        description="Lowest profit and loss over the prices of the outcome, divided by max loss, "
        "a decimal of at least -1; null when not finite."
    )
    pnl_std: float = Field(
        description="Standard deviation of profit and loss at expiry in dollars per share ($/sh)."
    )
    tail_share: float = Field(
        description="Share of the expected profit and loss that comes from beyond the outer "
        "knots (the completed tails), a decimal in [0, 1]."
    )


class KindBest(StructureRow):
    """The best structure of one kind, with its payoff curve on the response grid."""

    curve: list[float] = Field(
        description="Profit and loss divided by max loss (return on max loss) at each grid "
        "price, a decimal."
    )


class DominanceSegment(ApiModel):
    """A run of terminal prices over which one kind has the highest return on max loss."""

    from_: float = Field(alias="from", description="First grid price of the run in dollars ($/sh).")
    to: float = Field(
        description="First grid price of the next run in dollars ($/sh); the last grid price "
        "for the last run."
    )
    kind: StructureKind = Field(description="The kind with the highest pnl / max loss there.")


class Verdict(ApiModel):
    """Which kind serves the outcome best, and the best spread against the best single."""

    best_kind: StructureKind | None = Field(
        description="Kind with the highest return_if_right; null when no kind qualifies."
    )
    spread_kind: StructureKind | None = Field(
        description="Best qualifying spread (the four verticals and the iron condor); null when "
        "none qualifies."
    )
    single_kind: StructureKind | None = Field(
        description="Best qualifying outright long premium (long call, long put; the straddle "
        "and strangle too when the outcome is a move); null when none qualifies."
    )
    spread_return_if_right: float | None = Field(
        description="return_if_right of spread_kind (return on max loss), a decimal; null "
        "without one."
    )
    single_return_if_right: float | None = Field(
        description="return_if_right of single_kind (return on max loss), a decimal; null "
        "without one."
    )
    advantage: float | None = Field(
        description="spread_return_if_right minus single_return_if_right, a decimal; positive "
        "when the spread serves the outcome better; null when a side is missing."
    )
    reason: str = Field(description="One descriptive sentence that explains the comparison.")


class StructuresResponse(ApiModel):
    """Every structure kind scored against one outcome for one expiration."""

    symbol: str = Field(description="Ticker symbol, such as SPY.")
    session: date = Field(description="Trade date.")
    expiration: date = Field(description="Expiration of every structure.")
    dte_days: int = Field(description="Calendar days from the session to expiration.")
    years: float = Field(description="Time to expiration in years (ACT/365).")
    underlying_close: float = Field(description="Underlying close in dollars ($/sh).")
    forward: float | None = Field(description="Forward price in dollars ($/sh); null if unknown.")
    fill: Fill = Field(description="The fill the premiums assume.")
    map_id: str = Field(description="The calibration map that was applied.")
    map_is_identity: bool = Field(description="True when the map leaves probabilities unchanged.")
    look_ahead: bool = Field(
        description="True when the map was fitted on outcomes that settle after this session."
    )
    tails: TailInfo = Field(description="The tails that complete the distribution.")
    view: ViewInfo = Field(description="The outcome, resolved to prices and probabilities.")
    grid: list[float] = Field(
        description="Terminal prices in dollars ($/sh): 161 evenly spaced points from the 0.5% "
        "to the 99.5% quantile of the calibrated, tail-completed distribution, read at the raw "
        "knots as density is."
    )
    density: list[float] = Field(
        description="Calibrated, tail-completed probability density at each grid price (1/$): "
        "inside the quoted strikes the calibrated probability of the raw knot interval holding "
        "the price divided by its width (the landscape's density_calibrated), beyond them the "
        "lognormal tail density."
    )
    kinds: list[KindBest] = Field(
        description="The best qualifying structure of each kind, in the order of the kind list."
    )
    ranking: list[StructureRow] = Field(
        description="The qualifying structures of every kind, highest return_if_right first, "
        "at most limit rows."
    )
    dominance: list[DominanceSegment] = Field(
        description="Over the grid, which of the kinds above has the highest pnl / max loss."
    )
    verdict: Verdict = Field(description="Which kind serves the outcome best, and why.")
    n_structures: int = Field(description="Structures enumerated and scored.")
    n_qualifying: int = Field(
        description="Structures with prob_profit_given_view at or above min_pop_given and a "
        "finite return_if_right."
    )


class PresetInfo(ApiModel):
    """A preset outcome."""

    id: PresetId = Field(description="The preset id.")
    label: str = Field(description="Human-readable label, with its quantiles.")


class OutcomeCell(ApiModel):
    """The verdict numbers of one underlying for one preset outcome."""

    preset: PresetId = Field(description="The preset id.")
    lo: float | None = Field(
        description="Lower bound of the outcome in dollars ($/sh); null when open."
    )
    hi: float | None = Field(
        description="Upper bound of the outcome in dollars ($/sh); null when open."
    )
    prob: float = Field(description="Calibrated probability of the outcome, a decimal.")
    prob_market: float = Field(
        description="Raw (market-implied) probability of the outcome, a decimal."
    )
    best_kind: StructureKind | None = Field(
        description="Kind with the highest return_if_right; null when none qualifies."
    )
    best_return_if_right: float | None = Field(
        description="return_if_right of best_kind (return on max loss), a decimal."
    )
    best_legs: str | None = Field(description="Legs of the best structure, as in legs.")
    spread_kind: StructureKind | None = Field(description="Best qualifying spread kind.")
    spread_return_if_right: float | None = Field(
        description="return_if_right of spread_kind (return on max loss), a decimal."
    )
    single_kind: StructureKind | None = Field(description="Best qualifying single kind.")
    single_return_if_right: float | None = Field(
        description="return_if_right of single_kind (return on max loss), a decimal."
    )
    advantage: float | None = Field(
        description="spread_return_if_right minus single_return_if_right, a decimal; null when "
        "a side is missing."
    )


class OutcomeRow(ApiModel):
    """One underlying across the preset outcomes."""

    symbol: str = Field(description="Ticker symbol, such as SPY.")
    expiration: date | None = Field(
        description="The expiration with a distribution nearest the target DTE; null without one."
    )
    dte_days: int | None = Field(description="Calendar days from the session to expiration.")
    underlying_close: float | None = Field(description="Underlying close in dollars ($/sh).")
    cells: list[OutcomeCell] = Field(description="One cell per preset, in preset order.")
    unavailable_reason: str | None = Field(
        description="Why there are no cells: no_distribution: <detail> or no_implied_vol: "
        "<detail>; null when there are cells."
    )


class OutcomeMapResponse(ApiModel):
    """For every underlying of a session, which structure serves each preset outcome best."""

    session: date = Field(description="Trade date.")
    target_dte: int = Field(description="Requested calendar days to expiration.")
    fill: Fill = Field(description="The fill the premiums assume.")
    map_id: str = Field(description="The calibration map that was applied.")
    presets: list[PresetInfo] = Field(description="The preset outcomes, in column order.")
    rows: list[OutcomeRow] = Field(
        description="One row per underlying with the session, by symbol."
    )
