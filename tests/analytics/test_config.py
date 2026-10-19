from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from oap.analytics.config import (
    DEFAULT_CONFIG,
    DTE_BUCKETS,
    MONEYNESS_GRID,
    PRODUCTION_MAP_ID,
    AnalyticsConfig,
    dte_bucket,
    fold_map_id,
)
from oap.engine.calibration import DEFAULT_BINS, MIN_FIT_SAMPLES


def test_grid_has_thirteen_points_from_point_eight_to_one_point_one() -> None:
    assert len(MONEYNESS_GRID) == 13
    assert MONEYNESS_GRID[0] == 0.8
    assert MONEYNESS_GRID[-1] == 1.1
    assert MONEYNESS_GRID[4] == 0.9
    assert all(b > a for a, b in zip(MONEYNESS_GRID, MONEYNESS_GRID[1:], strict=False))


@pytest.mark.parametrize(
    ("days", "bucket"),
    [(1, "<=20d"), (20, "<=20d"), (21, "21-35d"), (35, "21-35d"), (36, "36-50d")]
    + [(50, "36-50d"), (51, ">50d"), (400, ">50d")],
)
def test_dte_bucket_edges(days: int, bucket: str) -> None:
    assert dte_bucket(days) == bucket
    assert bucket in DTE_BUCKETS


def test_map_ids() -> None:
    assert fold_map_id(2021) == "fold_2021"
    assert PRODUCTION_MAP_ID == "production"


def test_defaults() -> None:
    assert DEFAULT_CONFIG.min_fit_samples == MIN_FIT_SAMPLES
    assert DEFAULT_CONFIG.bins == DEFAULT_BINS
    assert DEFAULT_CONFIG.ticker_valid_from == (("META", date(2022, 6, 9)),)
    assert DEFAULT_CONFIG.moneyness_grid == MONEYNESS_GRID


@pytest.mark.parametrize(
    "change",
    [
        {"risk_free_apy": -1.0},
        {"cash_apy": -2.0},
        {"moneyness_grid": ()},
        {"moneyness_grid": (0.9, 0.9)},
        {"moneyness_grid": (0.0, 0.9)},
        {"min_dte_days": 0},
        {"split_abs_log_return": 0.0},
        {"min_fit_samples": 0},
        {"bins": 0},
        {"bootstrap_resamples": 0},
        {"max_width_fraction": 0.0},
        {"max_width_fraction": 1.5},
        {"min_credit": -0.01},
        {"min_prob_profit": 1.1},
        {"min_prob_profit": -0.1},
    ],
)
def test_invalid_config_raises(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(AnalyticsConfig(), **change)
