import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.engine._isotonic import isotonic_non_decreasing
from oap.engine.errors import EngineInputError

_values = st.lists(
    st.floats(-1e3, 1e3, allow_nan=False, allow_infinity=False), min_size=1, max_size=50
)
_weight = st.floats(0.01, 100, allow_nan=False, allow_infinity=False)


@st.composite
def _weighted(draw: st.DrawFn) -> tuple[list[float], list[float]]:
    y = draw(_values)
    w = draw(st.lists(_weight, min_size=len(y), max_size=len(y)))
    return y, w


def test_pools_a_full_violation() -> None:
    assert isotonic_non_decreasing([3, 1, 2]).tolist() == [2.0, 2.0, 2.0]


def test_pools_a_tail_violation() -> None:
    assert isotonic_non_decreasing([1, 3, 2]).tolist() == [1.0, 2.5, 2.5]


def test_weights_shift_the_pooled_level() -> None:
    result = isotonic_non_decreasing([1, 3, 2], [1, 1, 3])
    assert result.tolist() == pytest.approx([1.0, 2.25, 2.25])


def test_empty_input_gives_empty_output() -> None:
    assert isotonic_non_decreasing([]).shape == (0,)


@pytest.mark.parametrize("weights", [[1, 0, 1], [1, -1, 1], [1, np.nan, 1], [1, 1]])
def test_bad_weights_raise(weights: list[float]) -> None:
    with pytest.raises(EngineInputError):
        isotonic_non_decreasing([1, 2, 3], weights)


def test_non_finite_values_raise() -> None:
    with pytest.raises(EngineInputError):
        isotonic_non_decreasing([1, np.nan])


@given(_weighted())
def test_output_is_non_decreasing(data: tuple[list[float], list[float]]) -> None:
    y, w = data
    assert np.all(np.diff(isotonic_non_decreasing(y, w)) >= 0)


@given(_weighted())
def test_weighted_mean_is_preserved(data: tuple[list[float], list[float]]) -> None:
    y, w = data
    fit = isotonic_non_decreasing(y, w)
    tol = 1e-9 * (1 + max(abs(v) for v in y))
    assert np.average(fit, weights=w) == pytest.approx(np.average(y, weights=w), abs=tol)


@given(_weighted())
def test_idempotent(data: tuple[list[float], list[float]]) -> None:
    y, w = data
    fit = isotonic_non_decreasing(y, w)
    assert isotonic_non_decreasing(fit, w).tolist() == fit.tolist()


@given(_weighted())
def test_sorted_input_is_unchanged(data: tuple[list[float], list[float]]) -> None:
    y, w = data
    ordered = sorted(y)
    assert isotonic_non_decreasing(ordered, w).tolist() == ordered


@given(_weighted())
def test_beats_running_maximum_in_weighted_sse(data: tuple[list[float], list[float]]) -> None:
    y, w = data
    ya, wa = np.array(y), np.array(w)
    fit = isotonic_non_decreasing(ya, wa)
    sse = float(np.sum(wa * (fit - ya) ** 2))
    sse_max = float(np.sum(wa * (np.maximum.accumulate(ya) - ya) ** 2))
    assert sse <= sse_max + 1e-9
