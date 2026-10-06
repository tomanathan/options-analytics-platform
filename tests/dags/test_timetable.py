from datetime import date

import pendulum
import pytest
from airflow.timetables.base import DagRunInfo, DataInterval, TimeRestriction
from pendulum import DateTime

from dags import timetables
from dags.timetables import NYSECloseTimetable, session_of, snapshot_at

NY = "America/New_York"
LONG_AGO = pendulum.datetime(2020, 1, 1, tz="UTC")


def ny(year: int, month: int, day: int, hour: int = 16, minute: int = 30) -> DateTime:
    return pendulum.datetime(year, month, day, hour, minute, tz=NY)


def interval_of(day: date) -> DataInterval:
    return NYSECloseTimetable().infer_manual_data_interval(
        run_after=ny(day.year, day.month, day.day, 23, 0)
    )


def next_run(
    last: DataInterval | None,
    *,
    earliest: DateTime | None = LONG_AGO,
    latest: DateTime | None = None,
    catchup: bool = True,
) -> DagRunInfo | None:
    return NYSECloseTimetable().next_dagrun_info(
        last_automated_data_interval=last,
        restriction=TimeRestriction(earliest=earliest, latest=latest, catchup=catchup),
    )


def test_snapshot_instant_follows_daylight_saving() -> None:
    assert snapshot_at(date(2024, 1, 16)) == pendulum.datetime(2024, 1, 16, 21, 30, tz="UTC")
    assert snapshot_at(date(2024, 7, 3)) == pendulum.datetime(2024, 7, 3, 20, 30, tz="UTC")


def test_run_after_a_friday_skips_the_weekend_and_mlk_day() -> None:
    info = next_run(interval_of(date(2024, 1, 12)))
    assert info is not None
    assert info.run_after == ny(2024, 1, 16)
    assert info.data_interval == DataInterval(ny(2024, 1, 12), ny(2024, 1, 16))
    assert session_of(info.data_interval.end) == date(2024, 1, 16)


def test_first_run_after_friday_evening_is_tuesday() -> None:
    info = next_run(None, earliest=ny(2024, 1, 12, 17, 0))
    assert info is not None
    assert info.run_after == ny(2024, 1, 16)


def test_first_run_on_a_wednesday_morning_is_that_afternoon() -> None:
    info = next_run(None, earliest=ny(2024, 1, 17, 10, 0))
    assert info is not None
    assert info.run_after == ny(2024, 1, 17)
    assert info.data_interval.start == ny(2024, 1, 16)


def test_half_day_still_runs_at_1630_and_the_holiday_is_skipped() -> None:
    info = next_run(interval_of(date(2024, 7, 2)))
    assert info is not None
    assert info.run_after == ny(2024, 7, 3)
    after = next_run(info.data_interval)
    assert after is not None
    assert after.run_after == ny(2024, 7, 5)


def test_latest_is_respected_and_inclusive() -> None:
    friday = interval_of(date(2024, 1, 12))
    assert next_run(friday, latest=ny(2024, 1, 16, 12, 0)) is None
    info = next_run(friday, latest=ny(2024, 1, 16))
    assert info is not None
    assert info.run_after == ny(2024, 1, 16)


def test_no_start_date_means_no_scheduled_runs() -> None:
    assert next_run(None, earliest=None) is None


def test_without_catchup_a_stale_dag_schedules_from_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timetables, "_utcnow", lambda: ny(2024, 3, 6, 12, 0).in_timezone("UTC"))
    info = next_run(interval_of(date(2024, 1, 12)), catchup=False)
    assert info is not None
    assert info.run_after == ny(2024, 3, 6)


def test_without_catchup_after_the_snapshot_the_next_session_is_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(timetables, "_utcnow", lambda: ny(2024, 3, 8, 17, 0).in_timezone("UTC"))
    info = next_run(interval_of(date(2024, 1, 12)), catchup=False)
    assert info is not None
    assert info.run_after == ny(2024, 3, 11)


def test_manual_run_on_a_holiday_is_for_the_previous_session() -> None:
    interval = NYSECloseTimetable().infer_manual_data_interval(run_after=ny(2024, 1, 15, 12, 0))
    assert interval == DataInterval(ny(2024, 1, 11), ny(2024, 1, 12))


def test_manual_run_before_the_snapshot_is_for_the_previous_session() -> None:
    interval = NYSECloseTimetable().infer_manual_data_interval(run_after=ny(2024, 1, 17, 10, 0))
    assert session_of(interval.end) == date(2024, 1, 16)


def test_serialize_round_trip() -> None:
    timetable = NYSECloseTimetable()
    assert timetable.serialize() == {}
    restored = NYSECloseTimetable.deserialize(timetable.serialize())
    assert isinstance(restored, NYSECloseTimetable)
    assert restored.summary == "NYSE close 16:30 ET"
