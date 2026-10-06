from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.calendar import (
    NYSE,
    close_time,
    is_half_day,
    is_trading_day,
    next_trading_day,
    previous_trading_day,
    trading_days,
)

NEW_YORK = ZoneInfo("America/New_York")


def test_calendar_is_nyse() -> None:
    assert NYSE == "NYSE"


@pytest.mark.parametrize(
    "holiday",
    [
        date(2024, 1, 1),
        date(2024, 1, 15),
        date(2024, 7, 4),
        date(2024, 11, 28),
        date(2024, 12, 25),
    ],
    ids=["new-year", "mlk", "independence-day", "thanksgiving", "christmas"],
)
def test_holidays_do_not_trade(holiday: date) -> None:
    assert not is_trading_day(holiday)


@pytest.mark.parametrize("weekend", [date(2024, 1, 6), date(2024, 1, 7)])
def test_weekends_do_not_trade(weekend: date) -> None:
    assert not is_trading_day(weekend)


def test_a_regular_weekday_trades() -> None:
    assert is_trading_day(date(2024, 1, 2))


@pytest.mark.parametrize("half_day", [date(2024, 7, 3), date(2024, 11, 29), date(2024, 12, 24)])
def test_early_closes_are_half_days_and_still_trade(half_day: date) -> None:
    assert is_trading_day(half_day)
    assert is_half_day(half_day)


@pytest.mark.parametrize("day", [date(2024, 7, 5), date(2024, 7, 4), date(2024, 7, 6)])
def test_full_sessions_and_non_sessions_are_not_half_days(day: date) -> None:
    assert not is_half_day(day)


def test_trading_days_first_week_of_2024() -> None:
    assert trading_days(date(2024, 1, 1), date(2024, 1, 7)) == [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 5),
    ]


def test_trading_days_is_inclusive_at_both_ends() -> None:
    assert trading_days(date(2024, 1, 2), date(2024, 1, 2)) == [date(2024, 1, 2)]


def test_trading_days_over_a_weekend_only_is_empty() -> None:
    assert trading_days(date(2024, 1, 6), date(2024, 1, 7)) == []


def test_trading_days_rejects_start_after_end() -> None:
    with pytest.raises(ValueError):
        trading_days(date(2024, 1, 7), date(2024, 1, 1))


@given(
    st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    st.integers(min_value=0, max_value=60),
)
def test_trading_days_agree_with_is_trading_day(start: date, span: int) -> None:
    end = date.fromordinal(start.toordinal() + span)
    days = trading_days(start, end)

    assert days == sorted(set(days))
    assert all(start <= d <= end for d in days)
    expected = [
        date.fromordinal(o)
        for o in range(start.toordinal(), end.toordinal() + 1)
        if is_trading_day(date.fromordinal(o))
    ]
    assert days == expected


def test_close_time_on_a_half_day_is_one_pm_new_york() -> None:
    closes = close_time(date(2024, 7, 3))

    assert closes == datetime(2024, 7, 3, 13, 0, tzinfo=NEW_YORK)
    assert closes.utcoffset() == NEW_YORK.utcoffset(datetime(2024, 7, 3, 13, 0))


def test_close_time_on_a_full_day_is_four_pm_new_york() -> None:
    assert close_time(date(2024, 7, 5)) == datetime(2024, 7, 5, 16, 0, tzinfo=NEW_YORK)


def test_close_time_in_winter_is_four_pm_eastern_standard_time() -> None:
    closes = close_time(date(2024, 1, 2))

    assert closes == datetime(2024, 1, 2, 16, 0, tzinfo=NEW_YORK)
    assert closes.tzinfo is not None


def test_close_time_rejects_a_non_trading_day() -> None:
    with pytest.raises(ValueError):
        close_time(date(2024, 7, 4))


def test_previous_trading_day_skips_the_weekend() -> None:
    assert previous_trading_day(date(2024, 1, 8)) == date(2024, 1, 5)


def test_previous_trading_day_from_a_saturday() -> None:
    assert previous_trading_day(date(2024, 1, 6)) == date(2024, 1, 5)


def test_next_trading_day_skips_the_weekend() -> None:
    assert next_trading_day(date(2024, 1, 5)) == date(2024, 1, 8)


def test_next_trading_day_is_strictly_after() -> None:
    assert next_trading_day(date(2024, 1, 2)) == date(2024, 1, 3)


def test_next_trading_day_skips_a_holiday_after_a_weekend() -> None:
    assert next_trading_day(date(2024, 1, 12)) == date(2024, 1, 16)


def test_previous_trading_day_skips_a_holiday() -> None:
    assert previous_trading_day(date(2024, 7, 5)) == date(2024, 7, 3)
