"""Response models of the explorer API.

Units: strikes, prices, credits and closes are in dollars per share ($/sh); implied volatility
is a decimal (0.20, not 20%); probabilities and returns on collateral are decimals in [0, 1]
(returns may leave that range); densities are probability per dollar (1/$); times are in
calendar days or in years (ACT/365).

Any float that can be non-finite in the gold tables is typed ``float | None`` and converted
to ``None`` in code. ``ser_json_inf_nan="null"`` is the second line of defence: a stray
infinity or NaN serialises as ``null`` instead of producing invalid JSON.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ErrorCode = Literal["database_busy", "database_missing", "gold_missing", "not_found", "invalid"]
MapChoice = Literal["auto", "production", "walk_forward"]


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
        description="Calibrated expected return on collateral over the holding period."
    )
    expected_roc_raw: float = Field(
        description="Raw expected return on collateral over the holding period."
    )
    annualised_roc: float | None = Field(
        description="Calibrated annualised return on collateral; null when not finite."
    )
    kelly_fraction: float = Field(description="Kelly fraction of capital, a decimal in [0, 1].")
    eligible: bool = Field(description="True when the spread passes the eligibility rules.")
    rank: int | None = Field(description="1 is best among eligible spreads; null otherwise.")
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
    rows: list[SpreadRow] = Field(
        description="Rank ascending with nulls last, then annualised_roc descending."
    )


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
    interest: float = Field(description="Interest on the collateral in dollars ($/sh).")
    annualised_roc_raw: float | None = Field(
        description="Raw annualised return on collateral; null when not finite."
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
