import math

import numpy as np
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from oap.engine._types import Right
from oap.engine.black_scholes import (
    call_price,
    delta,
    implied_forward,
    implied_vol,
    option_price,
    price_bounds,
    put_call_parity_forward,
    put_price,
    vega,
)
from oap.engine.errors import EngineInputError
from tests.engine.chains import synthetic_chain

R = math.expm1(0.05)
CALL = 10.450583572185565
PUT = 5.573526022256967
ABS = 1e-9


def _f(lo: float, hi: float) -> st.SearchStrategy[float]:
    return st.floats(lo, hi, allow_nan=False, allow_infinity=False)


@st.composite
def _market(draw: st.DrawFn) -> tuple[float, float, float, float, float, float]:
    spot = draw(_f(1, 5000))
    strike = spot * draw(_f(0.2, 3))
    years = draw(_f(1 / 365, 3))
    vol = draw(_f(0.02, 3))
    rate = draw(_f(0, 0.1))
    q = draw(_f(0, 0.05))
    return spot, strike, years, rate, vol, q


_rights: st.SearchStrategy[Right] = st.sampled_from(["C", "P"])


def test_call_price_reference() -> None:
    assert float(call_price(100, 100, 1, R, 0.2)) == pytest.approx(CALL, abs=ABS)


def test_put_price_reference() -> None:
    assert float(put_price(100, 100, 1, R, 0.2)) == pytest.approx(PUT, abs=ABS)


def test_deltas_reference() -> None:
    assert float(delta(100, 100, 1, R, 0.2, "C")) == pytest.approx(0.6368306511756191, abs=ABS)
    assert float(delta(100, 100, 1, R, 0.2, "P")) == pytest.approx(-0.3631693488243809, abs=ABS)


def test_vega_reference() -> None:
    assert float(vega(100, 100, 1, R, 0.2)) == pytest.approx(37.52403469169379, abs=ABS)


def test_implied_vol_reference() -> None:
    assert float(implied_vol(CALL, 100, 100, 1, R, "C")) == pytest.approx(0.2, abs=ABS)
    assert float(implied_vol(PUT, 100, 100, 1, R, "P")) == pytest.approx(0.2, abs=ABS)


def test_put_call_parity_forward_reference() -> None:
    forward = put_call_parity_forward(CALL, PUT, 100, 1, R)
    assert forward == pytest.approx(100 * math.exp(0.05), abs=ABS)


def test_scalar_inputs_give_zero_dimensional_arrays() -> None:
    assert call_price(100, 100, 1, R, 0.2).shape == ()


def test_broadcasting_over_strikes() -> None:
    prices = call_price(100, np.array([90.0, 100.0, 110.0]), 1, R, 0.2)
    assert prices.shape == (3,)
    assert np.all(np.diff(prices) < 0)


def test_dividend_yield_lowers_call_price() -> None:
    plain = float(call_price(100, 100, 1, R, 0.2))
    with_div = float(call_price(100, 100, 1, R, 0.2, dividend_yield=0.03))
    assert with_div < plain


def test_implied_forward_recovers_forward() -> None:
    strikes, puts, calls, forward = synthetic_chain(100.0, 0.25, 0.25, 0.04, 0.2)
    assert implied_forward(strikes[:3], calls[:3], puts[:3], years=0.25, rate=0.04) == (
        pytest.approx(forward, abs=ABS)
    )
    assert implied_forward(strikes, calls, puts, years=0.25, rate=0.04) == pytest.approx(
        forward, abs=ABS
    )


def test_implied_forward_validates() -> None:
    with pytest.raises(EngineInputError):
        implied_forward([100, 90], [1, 2], [2, 1], years=1, rate=0.01)
    with pytest.raises(EngineInputError):
        implied_forward([90, 100], [1], [2, 1], years=1, rate=0.01)
    with pytest.raises(EngineInputError):
        implied_forward([], [], [], years=1, rate=0.01)


@pytest.mark.parametrize("price", [0.0, 1e-12, 100.0, math.nan, -1.0])
def test_implied_vol_is_nan_outside_bounds(price: float) -> None:
    # Call lower bound is 100 - 100 / 1.05 = 4.76; upper bound is the spot of 100.
    below = float(implied_vol(price, 100, 100, 1, R, "C"))
    assert math.isnan(below)


def test_implied_vol_is_nan_for_put_above_upper_bound() -> None:
    assert math.isnan(float(implied_vol(100.0, 100, 100, 1, R, "P")))


def test_implied_vol_nan_is_elementwise() -> None:
    result = implied_vol(np.array([CALL, math.nan, -1.0]), 100, 100, 1, R, "C")
    assert result[0] == pytest.approx(0.2, abs=ABS)
    assert np.isnan(result[1:]).all()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"spot": 0.0},
        {"years": 0.0},
        {"vol": 0.0},
        {"strike": math.nan},
        {"rate": -1.0},
        {"dividend_yield": -1.0},
        {"spot": math.inf},
    ],
)
def test_invalid_inputs_raise(kwargs: dict[str, float]) -> None:
    args = {"spot": 100.0, "strike": 100.0, "years": 1.0, "rate": R, "vol": 0.2}
    args.update(kwargs)
    dividend_yield = args.pop("dividend_yield", 0.0)
    with pytest.raises(EngineInputError):
        call_price(**args, dividend_yield=dividend_yield)


def test_invalid_right_raises() -> None:
    with pytest.raises(EngineInputError):
        option_price(100, 100, 1, R, 0.2, "X")  # type: ignore[arg-type]


def test_implied_vol_rejects_invalid_market_inputs() -> None:
    with pytest.raises(EngineInputError):
        implied_vol(CALL, 0.0, 100, 1, R, "C")
    with pytest.raises(EngineInputError):
        implied_vol(CALL, 100, 100, 0.0, R, "C")


@given(_market(), _rights)
def test_price_within_no_arbitrage_bounds(
    m: tuple[float, float, float, float, float, float], right: Right
) -> None:
    spot, strike, years, rate, vol, q = m
    price = float(option_price(spot, strike, years, rate, vol, right, dividend_yield=q))
    lower, upper = price_bounds(spot, strike, years, rate, right, dividend_yield=q)
    assert float(lower) - 1e-9 * spot <= price <= float(upper) + 1e-9 * spot


@given(_market())
def test_put_call_parity(m: tuple[float, float, float, float, float, float]) -> None:
    spot, strike, years, rate, vol, q = m
    c = float(call_price(spot, strike, years, rate, vol, dividend_yield=q))
    p = float(put_price(spot, strike, years, rate, vol, dividend_yield=q))
    df_r = (1 + rate) ** -years
    df_q = (1 + q) ** -years
    assert abs(c - p - (spot * df_q - strike * df_r)) <= 1e-8 * max(1.0, spot)


@given(_market(), _rights, _f(0.01, 1))
def test_price_is_monotone_in_vol(
    m: tuple[float, float, float, float, float, float], right: Right, u: float
) -> None:
    spot, strike, years, rate, vol, q = m
    low = float(option_price(spot, strike, years, rate, vol, right, dividend_yield=q))
    high = float(option_price(spot, strike, years, rate, vol * (1 + u), right, dividend_yield=q))
    assert high >= low - 1e-10 * spot


@given(_market(), _f(0.01, 1))
def test_price_is_monotone_in_strike(
    m: tuple[float, float, float, float, float, float], u: float
) -> None:
    spot, strike, years, rate, vol, q = m
    k2 = strike * (1 + u)
    c1 = float(call_price(spot, strike, years, rate, vol, dividend_yield=q))
    c2 = float(call_price(spot, k2, years, rate, vol, dividend_yield=q))
    p1 = float(put_price(spot, strike, years, rate, vol, dividend_yield=q))
    p2 = float(put_price(spot, k2, years, rate, vol, dividend_yield=q))
    assert c2 <= c1 + 1e-10 * spot
    assert p2 >= p1 - 1e-10 * spot


@given(_market())
def test_delta_and_vega_bounds(m: tuple[float, float, float, float, float, float]) -> None:
    spot, strike, years, rate, vol, q = m
    df_q = (1 + q) ** -years
    d_call = float(delta(spot, strike, years, rate, vol, "C", dividend_yield=q))
    d_put = float(delta(spot, strike, years, rate, vol, "P", dividend_yield=q))
    v = float(vega(spot, strike, years, rate, vol, dividend_yield=q))
    assert 0.0 <= d_call <= df_q * (1 + 1e-12)
    assert -df_q * (1 + 1e-12) <= d_put <= 0.0
    assert v >= 0.0
    h = 1e-5
    up = float(call_price(spot, strike, years, rate, vol + h, dividend_yield=q))
    down = float(call_price(spot, strike, years, rate, vol - h, dividend_yield=q))
    fd = (up - down) / (2 * h)
    assert abs(v - fd) <= 1e-5 * spot + 1e-4 * v


@given(_f(1, 5000), _f(-3, 3), _f(1 / 365, 3), _f(0.02, 3), _f(0, 0.1), _rights)
def test_implied_vol_round_trip(
    spot: float, z: float, years: float, vol: float, rate: float, right: Right
) -> None:
    forward = spot * (1 + rate) ** years
    strike = forward * math.exp(-z * vol * math.sqrt(years))
    assume(0.2 * spot <= strike <= 3 * spot)
    assume(float(vega(spot, strike, years, rate, vol)) >= 1e-6 * spot)
    price = float(option_price(spot, strike, years, rate, vol, right))
    assert abs(float(implied_vol(price, spot, strike, years, rate, right)) - vol) <= 1e-6


@given(st.lists(st.tuples(_market(), _f(-0.2, 1.2), _rights), min_size=1, max_size=8))
def test_vectorised_implied_vol_equals_scalar(
    rows: list[tuple[tuple[float, float, float, float, float, float], float, Right]],
) -> None:
    for right in ("C", "P"):
        sel = [(m, frac) for m, frac, r in rows if r == right]
        if not sel:
            continue
        spot = np.array([m[0] for m, _ in sel])
        strike = np.array([m[1] for m, _ in sel])
        years = np.array([m[2] for m, _ in sel])
        rate = np.array([m[3] for m, _ in sel])
        vol = np.array([m[4] for m, _ in sel])
        base = option_price(spot, strike, years, rate, vol, right)
        price = base * np.array([frac + 1 for _, frac in sel])
        stacked = implied_vol(price, spot, strike, years, rate, right)
        for i in range(len(sel)):
            one = implied_vol(price[i], spot[i], strike[i], years[i], rate[i], right)
            assert np.array_equal(stacked[i], one, equal_nan=True)
