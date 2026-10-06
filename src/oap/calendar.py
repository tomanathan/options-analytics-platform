"""NYSE trading calendar: which dates trade, and when the session closes.

Every ingest job asks this module which dates to fetch, so a holiday or a weekend is never
requested from a vendor and never mistaken for missing data. The calendar comes from
``pandas_market_calendars`` (exchange holidays and early closes, including the 13:00 closes
around Independence Day, Thanksgiving and Christmas). It is built once per process and cached
at module level; building it is the only cost, and every function here is otherwise a pure
lookup with no network access.

Dates are calendar dates in the exchange's time zone (America/New_York). Times returned are
timezone-aware datetimes in America/New_York.
"""

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

NYSE = "NYSE"

NEW_YORK = ZoneInfo("America/New_York")
"""Exchange time zone of the NYSE."""

REGULAR_CLOSE = time(16, 0)
"""Closing time of a full NYSE session, New York time."""

_SEARCH_DAYS = 14
"""Calendar days searched for an adjacent session; the longest NYSE closure is far shorter."""

_CALENDAR = mcal.get_calendar(NYSE)


@lru_cache(maxsize=64)
def _closes(year: int) -> dict[date, datetime]:
    """Return session date to close time (New York) for every NYSE session in a year."""
    schedule = _CALENDAR.schedule(start_date=f"{year}-01-01", end_date=f"{year}-12-31")
    return {
        pd.Timestamp(session).date(): pd.Timestamp(close).tz_convert(NEW_YORK).to_pydatetime()
        for session, close in schedule["market_close"].items()
    }


def _close(d: date) -> datetime | None:
    """Return the session close on ``d`` in New York time, or None if ``d`` is no session."""
    return _closes(d.year).get(d)


def is_trading_day(d: date) -> bool:
    """Return whether the NYSE holds a regular or early-close session on ``d``.

    Args:
        d: Calendar date in America/New_York.

    Returns:
        True for a session day (including half days), False for weekends and exchange
        holidays.
    """
    return _close(d) is not None


def trading_days(start: date, end: date) -> list[date]:
    """List the NYSE session days between two dates, both inclusive.

    Args:
        start: First calendar date of the range.
        end: Last calendar date of the range.

    Returns:
        Session days in ascending order. Empty when the range holds no session.

    Raises:
        ValueError: If ``start`` is after ``end``.
    """
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    days: list[date] = []
    for year in range(start.year, end.year + 1):
        days.extend(d for d in sorted(_closes(year)) if start <= d <= end)
    return days


def is_half_day(d: date) -> bool:
    """Return whether ``d`` is an NYSE early-close session.

    Args:
        d: Calendar date in America/New_York.

    Returns:
        True when the exchange closes before 16:00 on ``d``; False for full sessions and for
        dates that are not sessions at all.
    """
    close = _close(d)
    return close is not None and close.time() < REGULAR_CLOSE


def close_time(d: date) -> datetime:
    """Return the NYSE closing time on a session day.

    Args:
        d: A session day.

    Returns:
        Timezone-aware datetime in America/New_York: 16:00 on a full session, 13:00 on an
        early close.

    Raises:
        ValueError: If ``d`` is not a session day.
    """
    close = _close(d)
    if close is None:
        raise ValueError(f"{d} is not an NYSE trading day")
    return close


def previous_trading_day(d: date) -> date:
    """Return the last session day strictly before ``d``.

    Args:
        d: Any calendar date; it need not be a session day.

    Returns:
        The closest earlier session day.
    """
    for offset in range(1, _SEARCH_DAYS + 1):
        candidate = d - timedelta(days=offset)
        if is_trading_day(candidate):
            return candidate
    raise LookupError(f"no NYSE session in the {_SEARCH_DAYS} days before {d}")


def next_trading_day(d: date) -> date:
    """Return the first session day strictly after ``d``.

    Args:
        d: Any calendar date; it need not be a session day.

    Returns:
        The closest later session day.
    """
    for offset in range(1, _SEARCH_DAYS + 1):
        candidate = d + timedelta(days=offset)
        if is_trading_day(candidate):
            return candidate
    raise LookupError(f"no NYSE session in the {_SEARCH_DAYS} days after {d}")
