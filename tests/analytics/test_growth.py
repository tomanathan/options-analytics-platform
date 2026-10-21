import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.growth import (
    F_MAX,
    OPTION_COLUMNS,
    POOLED_SUFFIX,
    SCORED_COLUMNS,
    VARIANT_COLUMNS,
    Quadrature,
    ReturnGrid,
    build_quadrature,
    expected_log_growth,
    growth_optimum,
    leaking_options,
    mean_return,
    option_book,
    option_returns,
    score_expiration,
    score_session,
    session_map_id,
)
from oap.analytics.regime_calibration import regime_map_id
from oap.analytics.sample import chain_cdf
from oap.engine.calibration import CalibrationMap, apply_calibration
from oap.engine.positions import (
    EVERYTHING,
    StructureKind,
    TailCompletedCdf,
    build,
    score_structures,
)
from tests.analytics.frames import lognormal_quotes, outcomes_frame

TRADE = date(2024, 3, 1)
EXPIRY = date(2024, 3, 29)
STRIKES = np.arange(80.0, 121.0)
MC_POINTS = 20_000

# A map that fattens both tails: low probabilities up, high probabilities down.
FAT_TAILS = CalibrationMap(
    knots=np.array([0.0, 0.1, 0.9, 1.0]),
    values=np.array([0.0, 0.14, 0.86, 1.0]),
    n_samples=1000,
    is_identity=False,
)


def _chain(vol: float = 0.3, close: float = 100.0) -> pd.DataFrame:
    chain = lognormal_quotes("SPY", TRADE, EXPIRY, close, vol, 0.045, STRIKES)
    chain["source_iv"] = vol
    return chain


def _dist(cmap: CalibrationMap | None = None) -> TailCompletedCdf:
    chain = _chain()
    cdf = chain_cdf(chain, years=28 / 365, rate=0.045)
    assert cdf is not None
    base = cdf if cmap is None else apply_calibration(cdf, cmap)
    return TailCompletedCdf.complete(base, 0.3, 0.3)


def _monte_carlo(dist: TailCompletedCdf, seed: int) -> np.ndarray:
    u = np.random.default_rng(seed).uniform(1e-9, 1 - 1e-9, size=MC_POINTS)
    return np.array([dist.quantile(float(p)) for p in u])


def _returns(x: np.ndarray, strike: float, ask: float, call: bool) -> np.ndarray:
    payoff = np.maximum(x - strike, 0.0) if call else np.maximum(strike - x, 0.0)
    return payoff / ask - 1.0


@pytest.mark.parametrize("cmap", [None, FAT_TAILS], ids=["raw", "calibrated"])
def test_growth_integrand_matches_monte_carlo(cmap: CalibrationMap | None) -> None:
    dist = _dist(cmap)
    options = [(105.0, 0.9, True), (95.0, 0.7, False), (100.0, 3.2, True), (85.0, 0.05, False)]
    strikes = np.array([o[0] for o in options])
    asks = np.array([o[1] for o in options])
    calls = np.array([o[2] for o in options])
    quad = build_quadrature(dist, strikes)
    grid = option_returns(quad, strikes, asks, calls)
    samples = _monte_carlo(dist, seed=11)
    for f in (0.02, 0.1, 0.25):
        exact = expected_log_growth(quad, grid, np.full(len(options), f))
        for i, (strike, ask, call) in enumerate(options):
            values = np.log1p(f * _returns(samples, strike, ask, call))
            error = 4.0 * values.std() / math.sqrt(MC_POINTS)
            assert exact[i] == pytest.approx(values.mean(), abs=error + 1e-6)


def test_quadrature_is_a_probability_measure_with_the_exact_mean() -> None:
    dist = _dist(FAT_TAILS)
    strikes = np.array([90.0, 100.0, 110.0, 118.5])
    quad = build_quadrature(dist, strikes)
    total = quad.segment_masses.sum() + quad.masses.sum()
    assert total == pytest.approx(1.0, abs=1e-15)
    assert np.all(np.diff(quad.edges) > 0)
    assert set(strikes[(strikes > dist.k_lo) & (strikes < dist.k_hi)]) <= set(quad.edges)
    asks = np.array([2.0, 3.0, 1.0, 0.2])
    calls = np.array([False, True, True, True])
    positions = [
        build(StructureKind.LONG_CALL if c else StructureKind.LONG_PUT, [k], [a], dist.years)
        for k, a, c in zip(strikes, asks, calls, strict=True)
    ]
    exact = [s.expected_return for s in score_structures(positions, dist, EVERYTHING)]
    approx = mean_return(quad, option_returns(quad, strikes, asks, calls))
    np.testing.assert_allclose(approx, exact, rtol=1e-4, atol=1e-5)


def test_segment_means_are_exact_for_an_affine_payoff() -> None:
    # One uniform segment [0, 1] with R(s) = 2 s - 1: E[log(1 + f R)] in closed form.
    quad = Quadrature(np.array([0.0, 1.0]), np.array([1.0]), np.zeros(0), np.zeros(0))
    grid = ReturnGrid(np.array([[-1.0, 1.0]]), np.zeros((1, 0)))
    for f in (1e-9, 1e-4, 0.1, 0.25):
        a, b = 1.0 - f, 1.0 + f
        expected = ((b * math.log(b) - b) - (a * math.log(a) - a)) / (b - a)
        got = float(expected_log_growth(quad, grid, np.array([f]))[0])
        assert got == pytest.approx(expected, rel=1e-9, abs=1e-15)


def test_an_option_above_its_calibrated_value_gets_no_fraction() -> None:
    dist = _dist()
    strikes = np.array([100.0, 100.0])
    quad = build_quadrature(dist, strikes)
    fair = float(
        mean_return(quad, option_returns(quad, strikes, np.ones(2), np.array([True, False])))[0]
    )
    value = fair + 1.0  # the call's expected payoff per dollar of strike notional at ask 1
    asks = np.array([value * 1.05, value * 0.95])
    grid = option_returns(quad, strikes, asks, np.array([True, True]))
    kelly, growth = growth_optimum(quad, grid)
    assert mean_return(quad, grid)[0] < 0 < mean_return(quad, grid)[1]
    assert kelly[0] == 0.0 and growth[0] == 0.0
    assert kelly[1] > 0.0 and growth[1] > 0.0


def test_growth_optimum_matches_a_brute_force_search() -> None:
    dist = _dist(FAT_TAILS)
    strikes = np.array([88.0, 95.0, 104.0, 112.0, 100.0])
    calls = np.array([False, False, True, True, True])
    quad = build_quadrature(dist, strikes)
    fair = mean_return(quad, option_returns(quad, strikes, np.ones(5), calls)) + 1.0
    asks = fair * np.array([0.6, 0.999, 0.8, 0.5, 0.3])
    grid = option_returns(quad, strikes, asks, calls)
    kelly, growth = growth_optimum(quad, grid)
    fine = np.linspace(0.0, F_MAX, 20_001)
    for i in range(len(strikes)):
        one = ReturnGrid(grid.at_edges[i : i + 1], grid.at_nodes[i : i + 1])
        values = expected_log_growth(quad, one, fine[None, :])[0]
        best = int(np.argmax(values))
        assert growth[i] >= values[best] - 1e-12
        assert kelly[i] == pytest.approx(fine[best], abs=2 * F_MAX / 20_000)
    assert kelly[4] == pytest.approx(F_MAX)  # at the money at 30% of value: the cap binds
    assert 0.0 < kelly[3] < F_MAX  # far out of the money: high variance, small fraction


@settings(max_examples=30, deadline=None)
@given(
    strike=st.sampled_from([90.0, 97.0, 100.0, 103.0, 110.0]),
    call=st.booleans(),
    discounts=st.lists(st.floats(0.3, 1.3), min_size=2, max_size=6),
)
def test_growth_rate_is_monotone_in_the_edge(
    strike: float, call: bool, discounts: list[float]
) -> None:
    dist = _dist(FAT_TAILS)
    quad = build_quadrature(dist, np.array([strike]))
    fair = (
        float(
            mean_return(
                quad, option_returns(quad, np.array([strike]), np.ones(1), np.array([call]))
            )[0]
        )
        + 1.0
    )
    asks = fair * np.sort(np.asarray(discounts))[::-1]  # rising edge
    n = asks.shape[0]
    grid = option_returns(quad, np.full(n, strike), asks, np.full(n, call))
    _, growth = growth_optimum(quad, grid)
    assert np.all(np.diff(growth) >= -1e-12)
    assert np.all(growth >= 0.0)


def test_growth_optimum_validates_its_parameters() -> None:
    quad = Quadrature(np.array([0.0, 1.0]), np.array([1.0]), np.zeros(0), np.zeros(0))
    grid = ReturnGrid(np.array([[-1.0, 1.0]]), np.zeros((1, 0)))
    with pytest.raises(ValueError, match="f_max"):
        growth_optimum(quad, grid, f_max=1.0)
    with pytest.raises(ValueError, match="grid_size"):
        growth_optimum(quad, grid, grid_size=1)


def test_option_book_keeps_usable_quotes_inside_the_knots() -> None:
    chain = _chain()
    chain.loc[chain["strike"] == 100.0, "bid"] = 0.0
    book = option_book(chain, 85.5, 115.5)
    assert np.all((book.strikes >= 85.5) & (book.strikes <= 115.5))
    assert 100.0 not in set(book.strikes)
    assert np.all(book.asks > 0)
    assert list(book.is_call[: int(book.is_call.sum())]) == [True] * int(book.is_call.sum())


def test_score_expiration_scores_each_option_at_the_ask() -> None:
    chain = _chain()
    frame = score_expiration(
        chain, trade_date=TRADE, expiration=EXPIRY, maps={"": FAT_TAILS}, config=DEFAULT_CONFIG
    )
    assert frame is not None
    assert list(frame.columns) == list(OPTION_COLUMNS)
    np.testing.assert_array_equal(frame["expected_return"], frame["edge_pct"])
    np.testing.assert_allclose(
        frame["growth_gap"], frame["growth_rate"] - frame["growth_rate_market"]
    )
    assert frame["prob_profit"].between(0, 1).all()
    assert frame["kelly_fraction"].between(0, F_MAX).all()
    assert ((frame["growth_rate"] > 0) == (frame["kelly_fraction"] > 0)).all()
    assert ((frame["growth_rate"] > 0) <= (frame["expected_return"] > -1e-6)).all()
    assert frame["tail_share"].between(0, 1).all()
    # At the ask the market (raw) distribution prices every option above its value.
    assert (frame["expected_return_market"] < 0.02).all()
    row = frame.loc[(frame["right"] == "call") & (frame["strike"] == 105.0)].iloc[0]
    dist = _dist(FAT_TAILS)
    position = build(StructureKind.LONG_CALL, [105.0], [row["ask"]], dist.years)
    score = score_structures([position], dist, EVERYTHING)[0]
    assert row["expected_return"] == pytest.approx(score.expected_return)
    assert row["prob_profit"] == pytest.approx(score.prob_profit)
    assert row["return_std"] == pytest.approx(score.pnl_std / row["ask"])


def test_score_expiration_adds_suffixed_columns_and_skips_unusable_chains() -> None:
    chain = _chain()
    identity = CalibrationMap.identity(10)
    frame = score_expiration(
        chain, trade_date=TRADE, expiration=EXPIRY, maps={"": FAT_TAILS, POOLED_SUFFIX: identity}
    )
    assert frame is not None
    assert list(frame.columns) == [
        *OPTION_COLUMNS,
        *(f"{c}{POOLED_SUFFIX}" for c in VARIANT_COLUMNS),
    ]
    np.testing.assert_allclose(frame["growth_rate_pooled"], frame["growth_rate_market"])
    no_iv = chain.assign(source_iv=0.0)
    assert score_expiration(no_iv, trade_date=TRADE, expiration=EXPIRY, maps={"": identity}) is None
    few = chain.loc[chain["strike"].isin([99.0, 100.0])]
    assert score_expiration(few, trade_date=TRADE, expiration=EXPIRY, maps={"": identity}) is None


def _session_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    quotes = pd.concat(
        [
            lognormal_quotes("SPY", TRADE, EXPIRY, 100.0, 0.3, 0.045, STRIKES),
            lognormal_quotes(
                "AAPL", TRADE, EXPIRY, 190.0, 0.3, 0.045, np.arange(160.0, 221.0, 2.0)
            ),
            lognormal_quotes("SPY", TRADE, date(2024, 3, 5), 100.0, 0.3, 0.045, STRIKES),
        ],
        ignore_index=True,
    )
    quotes["source_iv"] = 0.3
    snapshots = quotes[["underlying", "trade_date", "expiration"]].drop_duplicates()
    snapshots = snapshots.assign(status="ok")
    outcomes = outcomes_frame(
        [
            ("SPY", EXPIRY, EXPIRY, 108.0),
            ("AAPL", EXPIRY, EXPIRY, 180.0),
            ("SPY", date(2024, 3, 5), date(2024, 3, 5), 100.0),
        ]
    )
    features = pd.DataFrame(
        {
            "underlying": ["SPY", "AAPL"],
            "trade_date": pd.Timestamp(TRADE),
            "ret_20": [0.02, -0.03],
            "iv_rank_120": [0.9, float("nan")],
            "atm_iv_change_5": [0.1, 0.3],
        }
    )
    return quotes, snapshots, outcomes, features


def test_score_session_settles_every_option_with_its_years_map() -> None:
    quotes, snapshots, outcomes, features = _session_inputs()
    maps = {"fold_2024": FAT_TAILS}
    result = score_session(quotes, snapshots, outcomes, features, maps, chosen="pooled")
    options = result.options
    assert list(options.columns) == list(SCORED_COLUMNS)
    assert result.snapshots == 3
    assert result.skipped == 1  # the 4-day expiry is below min_dte_days
    assert set(options["underlying"]) == {"SPY", "AAPL"}
    assert (options["map_id"] == "fold_2024").all()
    assert options["is_out_of_sample"].all()
    assert (options["fold"] == 2024).all()
    spy = options.loc[options["underlying"] == "SPY"]
    assert (spy["regime"] == "high_up").all()
    assert (options.loc[options["underlying"] == "AAPL", "regime"] == "unknown").all()
    assert spy["atm_iv_change_5"].eq(0.1).all()
    call = spy.loc[(spy["right"] == "call") & (spy["strike"] == 100.0)].iloc[0]
    assert call["realised_payoff"] == pytest.approx(8.0)
    assert call["realised_return"] == pytest.approx(8.0 / call["ask"] - 1.0)
    assert call["win"] == (call["realised_return"] > 0)
    put = spy.loc[(spy["right"] == "put") & (spy["strike"] == 100.0)].iloc[0]
    assert put["realised_return"] == -1.0
    np.testing.assert_allclose(
        options["moneyness"], options["strike"] / options["underlying_close"]
    )
    assert (options["years"] == 28 / 365).all()


def test_score_session_with_regime_maps_scores_the_pooled_map_too() -> None:
    quotes, snapshots, outcomes, features = _session_inputs()
    maps = {
        "fold_2024": CalibrationMap.identity(10),
        regime_map_id(2024, "high_up"): FAT_TAILS,
        regime_map_id(2024, "unknown"): CalibrationMap.identity(10),
    }
    maps["fold_2024"] = CalibrationMap(
        knots=np.array([0.0, 1.0]), values=np.array([0.0, 1.0]), n_samples=10, is_identity=False
    )
    result = score_session(quotes, snapshots, outcomes, features, maps, chosen="regime")
    options = result.options
    assert list(options.columns) == [
        *SCORED_COLUMNS,
        *(f"{c}{POOLED_SUFFIX}" for c in VARIANT_COLUMNS),
    ]
    spy = options.loc[options["underlying"] == "SPY"]
    assert (spy["map_id"] == "fold_2024_high_up").all()
    assert spy["is_out_of_sample"].all()
    aapl = options.loc[options["underlying"] == "AAPL"]
    assert not aapl["is_out_of_sample"].any()  # the unknown map is the identity here
    np.testing.assert_allclose(spy["growth_rate_pooled"], spy["growth_rate_market"])
    assert (spy["growth_rate"] != spy["growth_rate_pooled"]).any()


def test_score_session_skips_years_without_a_map_and_validates() -> None:
    quotes, snapshots, outcomes, features = _session_inputs()
    result = score_session(quotes, snapshots, outcomes, features, {}, chosen="pooled")
    assert result.options.empty
    assert list(result.options.columns) == list(SCORED_COLUMNS)
    assert result.skipped == 3
    with pytest.raises(ValueError, match="map choice"):
        score_session(quotes, snapshots, outcomes, features, {}, chosen="best")
    two = pd.concat([quotes, quotes.assign(trade_date=pd.Timestamp("2024-03-04"))])
    with pytest.raises(ValueError, match="single trade_date"):
        score_session(two, snapshots, outcomes, features, {}, chosen="pooled")
    with pytest.raises(ValueError, match="map choice"):
        session_map_id(2024, "high_up", "other")
    assert session_map_id(2024, "high_up", "pooled") == "fold_2024"
    assert session_map_id(2024, "high_up", "regime") == "fold_2024_high_up"


def test_leaking_options_flags_late_and_unknown_maps() -> None:
    options = pd.DataFrame(
        {
            "map_id": ["fold_2024", "fold_2024", "fold_2025", "other"],
            "trade_date": pd.to_datetime(["2024-01-02", "2023-12-01", "2025-01-02", "2025-01-02"]),
        }
    )
    table = pd.DataFrame(
        {
            "map_id": ["fold_2024", "fold_2024", "fold_2025"],
            "train_max_expiration": pd.to_datetime(["2023-12-29", "2023-12-29", "2024-12-31"]),
        }
    )
    leaks = leaking_options(options, table)
    assert leaks.index.tolist() == [1, 3]
