from datetime import date
from typing import Any, cast

import pytest
from airflow.exceptions import AirflowFailException

from dags import backfill_chains
from dags.backfill_chains import month_jobs, plan_jobs
from dags.common import read_watchlist
from oap.calendar import is_trading_day


def test_two_months_two_symbols_give_four_jobs_bounded_by_sessions() -> None:
    jobs = plan_jobs(date(2024, 1, 2), date(2024, 2, 29), ["SPY", "QQQ"])
    assert jobs == [
        {"symbol": "SPY", "start": "2024-01-02", "end": "2024-01-31"},
        {"symbol": "QQQ", "start": "2024-01-02", "end": "2024-01-31"},
        {"symbol": "SPY", "start": "2024-02-01", "end": "2024-02-29"},
        {"symbol": "QQQ", "start": "2024-02-01", "end": "2024-02-29"},
    ]
    for job in jobs:
        assert is_trading_day(date.fromisoformat(job["start"]))
        assert is_trading_day(date.fromisoformat(job["end"]))


def test_month_bounds_are_clipped_to_sessions_not_calendar_days() -> None:
    # 2023-12-30/31 are a weekend and 2024-01-01 a holiday; 2024-03-29 is Good Friday.
    jobs = plan_jobs(date(2023, 12, 30), date(2024, 3, 31), ["SPY"])
    assert [(job["start"], job["end"]) for job in jobs] == [
        ("2024-01-02", "2024-01-31"),
        ("2024-02-01", "2024-02-29"),
        ("2024-03-01", "2024-03-28"),
    ]


def test_range_inside_one_month_gives_one_job_per_symbol() -> None:
    jobs = plan_jobs(date(2024, 1, 8), date(2024, 1, 19), ["SPY", "QQQ", "IWM"])
    assert [job["symbol"] for job in jobs] == ["SPY", "QQQ", "IWM"]
    assert {(job["start"], job["end"]) for job in jobs} == {("2024-01-08", "2024-01-19")}


def test_range_without_sessions_gives_no_jobs() -> None:
    assert plan_jobs(date(2024, 1, 13), date(2024, 1, 15), ["SPY"]) == []


def test_empty_symbol_list_falls_back_to_the_watchlist_seed() -> None:
    jobs = plan_jobs(date(2024, 1, 2), date(2024, 1, 31), [])
    assert len(jobs) == 11
    assert [job["symbol"] for job in jobs] == read_watchlist()


def test_symbols_are_cleaned() -> None:
    jobs = plan_jobs(date(2024, 1, 2), date(2024, 1, 5), [" spy", "SPY", "qqq "])
    assert [job["symbol"] for job in jobs] == ["SPY", "QQQ"]


def test_month_jobs_group_symbols_per_month() -> None:
    jobs = plan_jobs(date(2024, 1, 2), date(2024, 2, 29), ["SPY", "QQQ"])
    assert month_jobs(jobs) == [
        {"month": "2024-01", "start": "2024-01-02", "end": "2024-01-31", "symbols": ["SPY", "QQQ"]},
        {"month": "2024-02", "start": "2024-02-01", "end": "2024-02-29", "symbols": ["SPY", "QQQ"]},
    ]


@pytest.mark.parametrize("symbols", [["SPY", "SPY;DROP"], ["TOOLONGX"], ["1ABC"]])
def test_malformed_symbols_fail_the_plan(symbols: list[str]) -> None:
    with pytest.raises(ValueError, match="malformed symbols") as caught:
        plan_jobs(date(2024, 1, 2), date(2024, 1, 31), symbols)

    assert symbols[-1] in str(caught.value)


def test_non_string_symbol_fails() -> None:
    with pytest.raises(ValueError, match="symbols must be strings"):
        plan_jobs(date(2024, 1, 2), date(2024, 1, 31), cast(Any, [123]))


def test_dotted_symbol_is_accepted() -> None:
    jobs = plan_jobs(date(2024, 1, 2), date(2024, 1, 31), ["BRK.B"])
    assert [job["symbol"] for job in jobs] == ["BRK.B"]


def test_plan_task_fails_fast_on_bad_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    params = {"start": "2024-01-01", "end": "2024-01-31", "symbols": ["BAD;"]}
    monkeypatch.setattr(backfill_chains, "get_current_context", lambda: {"params": params})
    task = backfill_chains.backfill_chains().get_task("plan")

    with pytest.raises(AirflowFailException, match="^ValueError: malformed symbols"):
        cast(Any, task).python_callable()
