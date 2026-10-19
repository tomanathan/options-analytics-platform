import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oap.engine._types import BoolArray, FloatArray
from oap.engine.calibration import (
    CalibrationMap,
    apply_calibration,
    brier_score,
    expected_calibration_error,
    fit_isotonic_calibration,
    log_loss,
    reliability_table,
)
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import QualityFlag, implied_cdf

_pairs = st.lists(
    st.tuples(
        st.floats(0, 1, allow_nan=False, allow_infinity=False),
        st.booleans(),
    ),
    min_size=1,
    max_size=300,
)


def _split(pairs: list[tuple[float, bool]]) -> tuple[FloatArray, BoolArray]:
    return np.array([p for p, _ in pairs]), np.array([y for _, y in pairs])


def test_brier_score() -> None:
    assert brier_score([0.1, 0.9], [0, 1]) == pytest.approx(0.01)


def test_log_loss() -> None:
    assert log_loss([0.1, 0.9], [0, 1]) == pytest.approx(0.105360515657826, abs=1e-12)


def test_log_loss_is_finite_for_certain_wrong_prediction() -> None:
    assert math.isfinite(log_loss([0.0], [1]))


def test_reliability_bin_assignment() -> None:
    table = reliability_table([1.0, 0.1, 0.55], [1, 0, 1], bins=10)
    assert len(table) == 10
    assert table[9].n == 1 and table[9].mean_predicted == 1.0
    assert table[1].n == 1 and table[1].mean_predicted == 0.1
    assert table[5].n == 1
    assert table[0].n == 0
    assert math.isnan(table[0].mean_predicted)
    assert math.isnan(table[0].frequency_realised)


@pytest.mark.parametrize(
    ("predicted", "realised", "bins"),
    [
        ([1.2], [1], 10),
        ([math.nan], [1], 10),
        ([0.5, 0.5], [1], 10),
        ([], [], 10),
        ([0.5], [2], 10),
        ([[0.5]], [[1]], 10),
    ],
)
def test_validation_errors(predicted: object, realised: object, bins: int) -> None:
    with pytest.raises(EngineInputError):
        reliability_table(predicted, realised, bins=bins)  # type: ignore[arg-type]
    with pytest.raises(EngineInputError):
        brier_score(predicted, realised)  # type: ignore[arg-type]


@pytest.mark.parametrize("bins", [0, -1])
def test_bins_must_be_positive(bins: int) -> None:
    with pytest.raises(EngineInputError):
        reliability_table([0.5], [1], bins=bins)
    with pytest.raises(EngineInputError):
        expected_calibration_error([0.5], [1], bins=bins)


def test_few_samples_give_identity_map() -> None:
    cmap = fit_isotonic_calibration([0.2, 0.8], [0, 1])
    assert cmap.is_identity
    assert cmap.n_samples == 2
    assert cmap.apply(0.37) == pytest.approx(0.37)


def test_known_pav_case() -> None:
    cmap = fit_isotonic_calibration([0.1, 0.2, 0.3], [1, 0, 1], min_samples=1)
    assert not cmap.is_identity
    assert cmap.knots.tolist() == [0.1, 0.2, 0.3]
    assert cmap.values.tolist() == pytest.approx([0.5, 0.5, 1.0])


def test_ties_in_predictions_are_averaged() -> None:
    cmap = fit_isotonic_calibration([0.5, 0.5, 0.5, 0.9], [1, 0, 0, 1], min_samples=1)
    assert cmap.knots.tolist() == [0.5, 0.9]
    assert cmap.values.tolist() == pytest.approx([1 / 3, 1.0])


def test_map_extrapolates_flat() -> None:
    cmap = fit_isotonic_calibration([0.4, 0.6], [0, 1], min_samples=1)
    assert cmap.apply(0.0) == 0.0
    assert cmap.apply(1.0) == 1.0
    assert cmap.apply(0.5) == pytest.approx(0.5)


def test_frame_round_trip() -> None:
    cmap = fit_isotonic_calibration([0.1, 0.2, 0.3], [1, 0, 1], min_samples=1)
    frame = cmap.to_frame()
    assert list(frame.columns) == [
        "knot_index",
        "predicted",
        "calibrated",
        "n_samples",
        "is_identity",
    ]
    assert frame["knot_index"].dtype == np.int64
    assert frame["n_samples"].dtype == np.int64
    assert frame["is_identity"].dtype == np.bool_
    back = CalibrationMap.from_frame(frame.sample(frac=1.0, random_state=0))
    assert np.array_equal(back.knots, cmap.knots)
    assert np.array_equal(back.values, cmap.values)
    assert back.n_samples == cmap.n_samples
    assert back.is_identity == cmap.is_identity


def test_from_frame_rejects_decreasing_calibrated() -> None:
    frame = CalibrationMap.identity().to_frame()
    frame["calibrated"] = [0.9, 0.1]
    with pytest.raises(EngineInputError):
        CalibrationMap.from_frame(frame)


def test_from_frame_rejects_missing_column() -> None:
    frame: pd.DataFrame = CalibrationMap.identity().to_frame().drop(columns=["n_samples"])
    with pytest.raises(EngineInputError):
        CalibrationMap.from_frame(frame)


def test_from_frame_rejects_empty_frame() -> None:
    frame = CalibrationMap.identity().to_frame().iloc[0:0]
    with pytest.raises(EngineInputError):
        CalibrationMap.from_frame(frame)


def test_map_arrays_are_read_only() -> None:
    with pytest.raises(ValueError, match="read-only"):
        CalibrationMap.identity().knots[0] = 0.5


def test_apply_identity_calibration_preserves_cdf() -> None:
    cdf = implied_cdf([90, 95, 100, 105, 110], [0.5, 1.5, 3.5, 7.0, 11.0], years=0.1, rate=0.02)
    out = apply_calibration(cdf, CalibrationMap.identity())
    assert out.prob_below_array(cdf.strikes).tolist() == pytest.approx(cdf.cdf.tolist(), abs=1e-12)
    assert np.all(np.diff(out.cdf) >= 0)
    assert QualityFlag.CALIBRATED in out.flags
    assert cdf.flags <= out.flags
    assert math.isnan(out.forward)


def test_apply_calibration_composes_exactly() -> None:
    cdf = implied_cdf([90, 95, 100, 105, 110], [0.5, 1.5, 3.5, 7.0, 11.0], years=0.1, rate=0.0)
    cmap = fit_isotonic_calibration([0.1, 0.3, 0.5, 0.7, 0.9], [0, 0, 1, 1, 1], min_samples=1)
    out = apply_calibration(cdf, cmap)
    grid = np.linspace(cdf.strikes[0] - 1, cdf.strikes[-1] + 1, 101)
    expected = cmap.apply_array(cdf.prob_below_array(grid))
    assert out.prob_below_array(grid).tolist() == pytest.approx(expected.tolist(), abs=1e-12)


@given(_pairs)
def test_reliability_bins_partition_the_data(pairs: list[tuple[float, bool]]) -> None:
    p, y = _split(pairs)
    table = reliability_table(p, y)
    assert sum(row.n for row in table) == len(pairs)
    for row in table:
        if row.n:
            assert row.lower <= row.mean_predicted <= row.upper


@given(_pairs)
def test_scores_are_bounded(pairs: list[tuple[float, bool]]) -> None:
    p, y = _split(pairs)
    assert 0.0 <= expected_calibration_error(p, y) <= 1.0
    assert 0.0 <= brier_score(p, y) <= 1.0


@given(_pairs)
def test_fitted_map_is_monotone_bounded_and_improves_brier(
    pairs: list[tuple[float, bool]],
) -> None:
    p, y = _split(pairs)
    cmap = fit_isotonic_calibration(p, y, min_samples=1)
    grid = cmap.apply_array(np.linspace(0, 1, 101))
    assert np.all(np.diff(grid) >= 0)
    assert grid.min() >= 0 and grid.max() <= 1
    assert brier_score(cmap.apply_array(p), y) <= brier_score(p, y) + 1e-12


@given(_pairs)
def test_identity_map_leaves_brier_unchanged(pairs: list[tuple[float, bool]]) -> None:
    p, y = _split(pairs)
    assert brier_score(CalibrationMap.identity().apply_array(p), y) == brier_score(p, y)


@settings(max_examples=25)
@given(st.integers(0, 2**32 - 1))
def test_calibrated_data_has_small_ece(seed: int) -> None:
    rng = np.random.default_rng(seed)
    p = rng.random(20000)
    y = rng.random(20000) < p
    assert expected_calibration_error(p, y) <= 0.03
