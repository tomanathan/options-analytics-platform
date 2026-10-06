import logging
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from dags.common import DEFAULT_ARGS, log_failure, read_watchlist, staging_dir


def test_log_failure_names_the_task_and_exception(caplog: pytest.LogCaptureFixture) -> None:
    context = {
        "task_instance": SimpleNamespace(dag_id="smoke", task_id="import_oap"),
        "logical_date": datetime(2026, 1, 1, tzinfo=UTC),
        "exception": RuntimeError("boom"),
    }
    with caplog.at_level(logging.ERROR, logger="dags.common"):
        log_failure(cast(Any, context))

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "dag_id=smoke" in message
    assert "task_id=import_oap" in message
    assert "RuntimeError('boom')" in message


def test_log_failure_tolerates_a_context_without_task_instance(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="dags.common"):
        log_failure(cast(Any, {}))

    assert "dag_id=None" in caplog.records[0].getMessage()


def test_default_args_wire_the_callback() -> None:
    assert DEFAULT_ARGS["on_failure_callback"] is log_failure


def test_read_watchlist_returns_the_seed_symbols_in_order() -> None:
    symbols = read_watchlist()
    assert len(symbols) == 11
    assert symbols[:3] == ["SPY", "QQQ", "IWM"]


def test_read_watchlist_cleans_symbols(tmp_path: Path) -> None:
    seed = tmp_path / "watchlist.csv"
    seed.write_text("symbol,sector\n spy ,x\nQQQ,y\n,z\nSPY,x\n")
    assert read_watchlist(seed) == ["SPY", "QQQ"]


def test_staging_dir_sanitizes_run_ids() -> None:
    path = staging_dir("test", "manual__2026-10-05T22:00:00+00:00")
    assert path.is_dir()
    assert path.name == "manual__2026-10-05T22_00_00_00_00"
