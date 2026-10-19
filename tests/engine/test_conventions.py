import math
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.engine.conventions import continuous_rate, discount_factor, dte_years, growth_factor
from oap.engine.errors import EngineInputError


def test_dte_years_is_act_365() -> None:
    assert dte_years(date(2024, 1, 1), date(2024, 1, 31)) == 30 / 365


def test_same_day_expiry_is_zero() -> None:
    assert dte_years(date(2024, 1, 5), date(2024, 1, 5)) == 0.0


def test_expiration_before_trade_date_raises() -> None:
    with pytest.raises(EngineInputError):
        dte_years(date(2024, 1, 5), date(2024, 1, 4))


def test_growth_factor_one_year() -> None:
    assert growth_factor(0.036, 1) == pytest.approx(1.036, abs=1e-15)


@given(
    st.floats(-0.5, 0.2, allow_nan=False, allow_infinity=False),
    st.floats(0, 5, allow_nan=False, allow_infinity=False),
)
def test_discount_times_growth_is_one(rate: float, years: float) -> None:
    assert discount_factor(rate, years) * growth_factor(rate, years) == pytest.approx(
        1.0, abs=1e-15
    )


def test_continuous_rate_inverts_expm1() -> None:
    assert continuous_rate(math.expm1(0.05)) == pytest.approx(0.05, abs=1e-15)


@pytest.mark.parametrize(
    ("rate", "years"), [(-1.0, 1.0), (math.nan, 1.0), (0.01, -0.1), (0.01, math.inf)]
)
def test_growth_factor_rejects_bad_inputs(rate: float, years: float) -> None:
    with pytest.raises(EngineInputError):
        growth_factor(rate, years)


@pytest.mark.parametrize("apy", [-1.0, -2.0, math.nan, math.inf])
def test_continuous_rate_rejects_bad_apy(apy: float) -> None:
    with pytest.raises(EngineInputError):
        continuous_rate(apy)
