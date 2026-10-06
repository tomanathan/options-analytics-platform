from datetime import date, timedelta

import pandas as pd
import pytest

from oap.quality.bronze_suite import (
    CHECK_KEY_UNIQUE,
    CHECK_OCC_SYMBOL_NOT_NULL,
    CHECK_RIGHT_IN_SET,
    CHECK_STRIKE_POSITIVE,
    MIN_HISTORY_DAYS,
    BronzeQualityError,
    assert_bronze_ok,
    build_suite,
    row_count_bounds,
    row_count_check_name,
    validate_bronze,
)
from tests.bronze_factory import bronze_frame
from tests.quality.batches import (
    BATCH_DATE,
    BROKEN_FAILURES,
    BROKEN_SYMBOL,
    SHORT_HISTORY_SYMBOL,
    USUAL_ROWS,
    build_good,
)

START = date(2024, 1, 2)


def _history(counts: dict[str, list[int]]) -> pd.DataFrame:
    """Rows with only underlying and trade_date: ``counts[symbol][i]`` rows on day i."""
    records = [
        {"underlying": symbol, "trade_date": START + timedelta(days=i)}
        for symbol, per_day in counts.items()
        for i, n in enumerate(per_day)
        for _ in range(n)
    ]
    return pd.DataFrame(records, columns=["underlying", "trade_date"])


# row_count_bounds


def test_row_count_bounds_is_median_widened_by_the_band() -> None:
    bounds = row_count_bounds(_history({"SPY": [100] * 20}))

    assert bounds == {"SPY": (50, 150)}


def test_row_count_bounds_floors_the_minimum_and_ceils_the_maximum() -> None:
    bounds = row_count_bounds(_history({"SPY": [10, 10, 11, 11, 12, 12]}))

    assert bounds == {"SPY": (5, 17)}


def test_row_count_bounds_honours_a_custom_band() -> None:
    bounds = row_count_bounds(_history({"SPY": [100] * 10}), band=0.2)

    assert bounds == {"SPY": (80, 120)}


def test_row_count_bounds_uses_only_the_trailing_window() -> None:
    bounds = row_count_bounds(_history({"SPY": [1000] * 10 + [100] * 20}), window_days=20)

    assert bounds == {"SPY": (50, 150)}


def test_row_count_bounds_is_per_underlying() -> None:
    bounds = row_count_bounds(_history({"SPY": [100] * 6, "QQQ": [40] * 6}))

    assert bounds == {"SPY": (50, 150), "QQQ": (20, 60)}


def test_row_count_bounds_skips_underlyings_with_short_history() -> None:
    short = MIN_HISTORY_DAYS - 1
    bounds = row_count_bounds(_history({"SPY": [100] * MIN_HISTORY_DAYS, "NEW": [10] * short}))

    assert MIN_HISTORY_DAYS == 5
    assert "SPY" in bounds
    assert "NEW" not in bounds


def test_row_count_bounds_of_empty_history_is_empty() -> None:
    assert row_count_bounds(_history({})) == {}


@pytest.mark.parametrize(("window_days", "band"), [(0, 0.5), (-1, 0.5), (20, -0.1), (20, 1.5)])
def test_row_count_bounds_rejects_bad_parameters(window_days: int, band: float) -> None:
    with pytest.raises(ValueError):
        row_count_bounds(_history({"SPY": [100] * 20}), window_days=window_days, band=band)


def test_row_count_bounds_from_the_fixture_history(history: pd.DataFrame) -> None:
    bounds = row_count_bounds(history)

    assert set(bounds) == {"SPY", "QQQ"}
    for low, high in bounds.values():
        assert low <= USUAL_ROWS <= high
        assert high < 10 * USUAL_ROWS


# build_suite


def test_build_suite_names_every_expectation() -> None:
    suite = build_suite({"SPY": (50, 150), "QQQ": (20, 60)})

    names = sorted(e.meta["name"] for e in suite.expectations if e.meta)
    assert len(suite.expectations) == 6
    assert names == sorted(
        [
            CHECK_OCC_SYMBOL_NOT_NULL,
            CHECK_STRIKE_POSITIVE,
            CHECK_RIGHT_IN_SET,
            CHECK_KEY_UNIQUE,
            "row_count:SPY",
            "row_count:QQQ",
        ]
    )


def test_build_suite_without_bounds_has_only_row_checks() -> None:
    suite = build_suite({})

    assert len(suite.expectations) == 4


def test_row_count_check_name() -> None:
    assert row_count_check_name("SPY") == "row_count:SPY"


# validate_bronze and assert_bronze_ok


def test_good_batch_passes(good: pd.DataFrame, history: pd.DataFrame) -> None:
    assert validate_bronze(good, row_count_bounds(history)) == []


def test_broken_batch_names_all_five_failures(broken: pd.DataFrame, history: pd.DataFrame) -> None:
    assert validate_bronze(broken, row_count_bounds(history)) == BROKEN_FAILURES


def test_a_tenfold_symbol_fails_only_its_row_count(history: pd.DataFrame) -> None:
    batch = pd.concat(
        [
            bronze_frame(BATCH_DATE, underlyings=("SPY",), rows_per_underlying=USUAL_ROWS),
            bronze_frame(
                BATCH_DATE, underlyings=(BROKEN_SYMBOL,), rows_per_underlying=10 * USUAL_ROWS
            ),
        ],
        ignore_index=True,
    )

    assert validate_bronze(batch, row_count_bounds(history)) == [f"row_count:{BROKEN_SYMBOL}"]


def test_a_symbol_missing_from_the_batch_fails_its_row_count(history: pd.DataFrame) -> None:
    spy_only = bronze_frame(BATCH_DATE, underlyings=("SPY",), rows_per_underlying=USUAL_ROWS)

    assert validate_bronze(spy_only, row_count_bounds(history)) == ["row_count:QQQ"]


def test_without_bounds_row_counts_are_not_checked() -> None:
    batch = bronze_frame(BATCH_DATE, underlyings=("SPY",), rows_per_underlying=10 * USUAL_ROWS)

    assert validate_bronze(batch, {}) == []


def test_a_symbol_with_short_history_is_not_bounded(history: pd.DataFrame) -> None:
    batch = pd.concat(
        [
            build_good(),
            bronze_frame(
                BATCH_DATE,
                underlyings=(SHORT_HISTORY_SYMBOL,),
                rows_per_underlying=10 * USUAL_ROWS,
            ),
        ],
        ignore_index=True,
    )

    bounds = row_count_bounds(history)

    assert SHORT_HISTORY_SYMBOL not in bounds
    assert validate_bronze(batch, bounds) == []


def test_assert_bronze_ok_passes_a_good_batch(good: pd.DataFrame, history: pd.DataFrame) -> None:
    assert_bronze_ok(good, history)


def test_assert_bronze_ok_raises_listing_the_failures(
    broken: pd.DataFrame, history: pd.DataFrame
) -> None:
    with pytest.raises(BronzeQualityError) as excinfo:
        assert_bronze_ok(broken, history)

    assert excinfo.value.failed == BROKEN_FAILURES
    for name in BROKEN_FAILURES:
        assert name in str(excinfo.value)


def test_bronze_quality_error_carries_the_failed_names() -> None:
    error = BronzeQualityError(["key_unique", "row_count:SPY"])

    assert error.failed == ["key_unique", "row_count:SPY"]
    assert "row_count:SPY" in str(error)
