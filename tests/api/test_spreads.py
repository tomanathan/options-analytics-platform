from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.api.spreads import (
    MAX_SPREAD_ROWS,
    SpreadFilters,
    filter_spreads,
    payoff_curve,
    prepare_spreads,
)


def _frame() -> pd.DataFrame:
    rows = [
        # key, underlying, expiration, width, credit, pop, eligible, rank, annualised
        ("a", "SPY", date(2024, 3, 28), 5.0, 1.0, 0.70, True, 2, 0.30),
        ("b", "SPY", date(2024, 3, 28), 10.0, 2.0, 0.60, True, 1, 0.50),
        ("c", "XLF", date(2024, 4, 19), 1.0, 0.2, 0.55, True, 3, 0.10),
        ("d", "XLF", date(2024, 4, 19), 2.0, 0.5, 0.40, False, None, 0.90),
        ("e", "XLF", date(2024, 4, 19), 2.0, 0.5, 0.30, False, None, np.nan),
        ("f", "SPY", date(2024, 4, 19), 5.0, 0.9, 0.20, False, None, 0.20),
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "spread_key",
            "underlying",
            "expiration",
            "width",
            "credit",
            "prob_profit",
            "eligible",
            "rank",
            "annualised_roc",
        ],
    )
    frame["expiration"] = pd.to_datetime(frame["expiration"])
    frame["flags"] = ["", "clipped", None, "", "", ""]
    return frame


def _keys(frame: pd.DataFrame, **filters: object) -> list[str]:
    return filter_spreads(prepare_spreads(frame), SpreadFilters(**filters)).spread_key.tolist()  # type: ignore[arg-type]


def test_prepare_orders_by_rank_then_annualised_return_with_nulls_last() -> None:
    prepared = prepare_spreads(_frame())
    assert prepared["spread_key"].tolist() == ["b", "a", "c", "d", "f", "e"]
    assert str(prepared["rank"].dtype) == "Int64"
    assert prepared["flags"].tolist() == ["clipped", "", "", "", "", ""]
    assert all(isinstance(flag, str) for flag in prepared["flags"])


def test_eligible_only_is_the_default() -> None:
    assert _keys(_frame()) == ["b", "a", "c"]
    assert _keys(_frame(), eligible_only=False) == ["b", "a", "c", "d", "f", "e"]


def test_filters_combine_with_and() -> None:
    frame = _frame()
    assert _keys(frame, eligible_only=False, underlyings=("XLF",)) == ["c", "d", "e"]
    assert _keys(frame, eligible_only=False, expiration=date(2024, 4, 19)) == ["c", "d", "f", "e"]
    assert _keys(frame, eligible_only=False, min_width=5.0) == ["b", "a", "f"]
    assert _keys(frame, eligible_only=False, max_width=2.0) == ["c", "d", "e"]
    assert _keys(frame, eligible_only=False, min_pop=0.55) == ["b", "a", "c"]
    assert _keys(frame, eligible_only=False, min_credit=0.9) == ["b", "a", "f"]
    assert _keys(
        frame, eligible_only=False, underlyings=("SPY",), expiration=date(2024, 4, 19)
    ) == ["f"]
    assert _keys(frame, underlyings=("ZZZ",)) == []


def test_filter_does_not_apply_the_limit() -> None:
    assert SpreadFilters().limit == MAX_SPREAD_ROWS == 5000
    assert len(_keys(_frame(), eligible_only=False, limit=1)) == 6


@given(
    long=st.floats(min_value=10.0, max_value=500.0),
    width=st.floats(min_value=0.5, max_value=50.0),
    credit_fraction=st.floats(min_value=0.05, max_value=0.95),
    close_gap=st.floats(min_value=-0.1, max_value=0.2),
)
def test_payoff_curve_properties(
    long: float, width: float, credit_fraction: float, close_gap: float
) -> None:
    short = long + width
    credit = credit_fraction * width
    breakeven = short - credit
    close = short * (1.0 + close_gap) + 1.0
    points = payoff_curve(short, long, credit, breakeven, close)
    prices = np.array([p.price for p in points])
    payoff = np.array([p.payoff for p in points])
    assert np.all(np.diff(prices) > 0)
    assert {long, short, breakeven} <= set(prices.tolist())
    assert prices[0] >= 0.0
    assert prices[0] <= long - 2.0 * width + 1e-9 or prices[0] == 0.0
    assert prices[-1] >= max(short + 2.0 * width, 1.04 * close) - 1e-9
    assert np.all(payoff[prices >= short] == pytest.approx(credit))
    assert np.all(payoff[prices <= long] == pytest.approx(credit - width))
    assert np.all(np.diff(payoff) >= -1e-9)
    at_breakeven = payoff[prices == breakeven][0]
    assert at_breakeven == pytest.approx(0.0, abs=1e-9)
