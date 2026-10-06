"""Airflow timetables driven by the NYSE calendar.

``NYSECloseTimetable`` schedules one run per NYSE session day at 16:30 America/New_York,
half an hour after the regular close, so the end-of-day snapshot is taken once the session
is over. Weekends and exchange holidays get no run. Early-close days (13:00) still run at
16:30: the snapshot is end-of-day either way, and one fixed time keeps runs comparable.

The class is registered with Airflow by ``plugins/oap_timetables.py``; the scheduler can only
deserialize a DAG that uses a custom timetable when a plugin registers it under the same
import path the DAG file used (``dags.timetables.NYSECloseTimetable``).
"""

from datetime import date, datetime, time
from typing import Any

import pendulum
from airflow.timetables.base import DagRunInfo, DataInterval, TimeRestriction, Timetable
from pendulum import DateTime

NEW_YORK = pendulum.timezone("America/New_York")
SNAPSHOT_TIME = time(16, 30)


def _utcnow() -> DateTime:
    """Return the current time; a seam so tests can freeze the clock."""
    return pendulum.now("UTC")


def snapshot_at(day: date) -> DateTime:
    """Return the snapshot instant of a session day, 16:30 America/New_York, in UTC.

    Args:
        day: Calendar date in America/New_York.

    Returns:
        Timezone-aware UTC datetime.
    """
    local = pendulum.datetime(
        day.year, day.month, day.day, SNAPSHOT_TIME.hour, SNAPSHOT_TIME.minute, tz=NEW_YORK
    )
    return local.in_timezone("UTC")


def session_of(interval_end: datetime) -> date:
    """Return the NYSE session day a ``NYSECloseTimetable`` interval belongs to.

    Args:
        interval_end: The run's ``data_interval_end``.

    Returns:
        The session date in America/New_York.
    """
    return pendulum.instance(interval_end).in_timezone(NEW_YORK).date()


def _first_session_at_or_after(moment: datetime) -> date:
    """Return the first session day whose snapshot instant is at or after ``moment``."""
    from oap import calendar

    day = session_of(moment)
    if calendar.is_trading_day(day) and snapshot_at(day) >= moment:
        return day
    return calendar.next_trading_day(day)


def _last_session_at_or_before(moment: datetime) -> date:
    """Return the last session day whose snapshot instant is at or before ``moment``."""
    from oap import calendar

    day = session_of(moment)
    if calendar.is_trading_day(day) and snapshot_at(day) <= moment:
        return day
    return calendar.previous_trading_day(day)


def _interval_for(day: date) -> DataInterval:
    """Return the data interval of a session day: previous snapshot to this snapshot."""
    from oap import calendar

    return DataInterval(start=snapshot_at(calendar.previous_trading_day(day)), end=snapshot_at(day))


class NYSECloseTimetable(Timetable):
    """One run per NYSE session day at 16:30 America/New_York.

    The data interval of the run for session day ``D`` is
    ``[16:30 ET on the previous session day, 16:30 ET on D]``: it covers everything between
    two consecutive end-of-day snapshots, so the intervals tile time with no gaps or overlaps
    across weekends and holidays. The run fires at the interval end (Airflow's usual
    contract), and the session a run is for is the America/New_York date of
    ``data_interval_end`` (``session_of``). The logical date is therefore the previous
    session's snapshot time, as with any interval timetable.

    Scheduling rules:

    * ``restriction.earliest`` (``start_date``): no run whose snapshot instant is before it.
    * ``restriction.latest`` (``end_date``): no run whose snapshot instant is after it.
    * ``catchup=False``: missed sessions are not replayed; the next run is the first
      snapshot instant at or after now.
    * A manual trigger maps to the most recent snapshot instant at or before the trigger time,
      so a trigger on a holiday, a weekend or before 16:30 is for the previous session.
    """

    description = "One run per NYSE session day at 16:30 America/New_York"

    @property
    def summary(self) -> str:
        """Short text shown in the Airflow UI's schedule column."""
        return "NYSE close 16:30 ET"

    def serialize(self) -> dict[str, Any]:
        """Return the serialized form; the timetable has no parameters."""
        return {}

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> "NYSECloseTimetable":
        """Rebuild the timetable from ``serialize``'s output.

        Args:
            data: The serialized form, an empty dict.

        Returns:
            A new timetable.
        """
        return cls()

    def infer_manual_data_interval(self, *, run_after: DateTime) -> DataInterval:
        """Return the interval of the latest session whose snapshot is at or before the trigger.

        Args:
            run_after: When the manual run was triggered.

        Returns:
            That session's data interval.
        """
        return _interval_for(_last_session_at_or_before(run_after))

    def next_dagrun_info(
        self,
        *,
        last_automated_data_interval: DataInterval | None,
        restriction: TimeRestriction,
    ) -> DagRunInfo | None:
        """Return the next scheduled run, or None when the restriction allows no more runs.

        Args:
            last_automated_data_interval: Interval of the latest scheduled run, if any.
            restriction: ``start_date``, ``end_date`` and ``catchup`` of the DAG.

        Returns:
            The next run, firing at its interval end, or None.
        """
        if restriction.earliest is None:
            # No start_date: the DAG is never scheduled automatically.
            return None
        candidate = _first_session_at_or_after(restriction.earliest)
        if last_automated_data_interval is not None:
            from oap import calendar

            after_last = calendar.next_trading_day(session_of(last_automated_data_interval.end))
            candidate = max(candidate, after_last)
        if not restriction.catchup:
            candidate = max(candidate, _first_session_at_or_after(_utcnow()))
        interval = _interval_for(candidate)
        if restriction.latest is not None and interval.end > restriction.latest:
            return None
        return DagRunInfo.interval(start=interval.start, end=interval.end)
