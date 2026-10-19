import inspect
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pandas as pd
import pyarrow as pa
import pytest
from airflow.exceptions import AirflowFailException, AirflowSkipException
from pandera.errors import SchemaErrors
from pandera.pandas import Check, Column, DataFrameSchema
from tenacity import wait_none

from dags.common import (
    BRONZE_WRITERS_POOL,
    DEFAULT_ARGS,
    fail_fast,
    is_deterministic,
    log_failure,
    read_watchlist,
    staging_dir,
)
from oap.ingest.alpaca import AlpacaClient, AlpacaError
from oap.ingest.dolthub import DoltHubClient, DoltHubError
from oap.quality.bronze_suite import BronzeQualityError


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
    assert "exception=RuntimeError: boom" in message


def test_log_failure_tolerates_a_context_without_task_instance(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="dags.common"):
        log_failure(cast(Any, {}))

    assert "dag_id=None" in caplog.records[0].getMessage()


class _LeakyError(Exception):
    def __repr__(self) -> str:
        return "LeakyError(headers={'APCA-API-SECRET-KEY': 'not-a-real-secret'})"


def test_log_failure_never_logs_the_exception_repr(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="dags.common"):
        log_failure(cast(Any, {"exception": _LeakyError("request failed")}))

    message = caplog.records[0].getMessage()
    assert "exception=_LeakyError: request failed" in message
    assert "not-a-real-secret" not in message


def test_default_args_wire_the_callback() -> None:
    assert DEFAULT_ARGS["on_failure_callback"] is log_failure


def test_read_watchlist_returns_the_seed_symbols_in_order() -> None:
    symbols = read_watchlist()
    assert len(symbols) == 11
    assert symbols[:3] == ["SPY", "DIA", "XLF"]


def test_read_watchlist_cleans_symbols(tmp_path: Path) -> None:
    seed = tmp_path / "watchlist.csv"
    seed.write_text("symbol,sector\n spy ,x\nQQQ,y\n,z\nSPY,x\n")
    assert read_watchlist(seed) == ["SPY", "QQQ"]


def test_staging_dir_sanitizes_run_ids() -> None:
    path = staging_dir("test", "manual__2026-10-05T22:00:00+00:00")
    assert path.is_dir()
    assert path.name == "manual__2026-10-05T22_00_00_00_00"


def _schema_errors() -> SchemaErrors:
    schema = DataFrameSchema({"x": Column(int, Check.ge(0))})
    with pytest.raises(SchemaErrors) as caught:
        schema.validate(pd.DataFrame({"x": [-1]}), lazy=True)
    return caught.value


def _missing_credentials() -> AlpacaError:
    with pytest.raises(AlpacaError) as caught:
        AlpacaClient.from_env({})
    return caught.value


def _raiser(exc: BaseException) -> Any:
    @fail_fast
    def task() -> None:
        raise exc

    return task


DETERMINISTIC = {
    "ValueError": lambda: ValueError("bad"),
    "ArrowInvalid": lambda: pa.ArrowInvalid("bad"),
    "BronzeQualityError": lambda: BronzeQualityError(["row_count:SPY"]),
    "SchemaErrors": _schema_errors,
    "AlpacaError": _missing_credentials,
}


@pytest.mark.parametrize("make", DETERMINISTIC.values(), ids=DETERMINISTIC.keys())
def test_fail_fast_converts_deterministic_errors(make: Any) -> None:
    original = make()

    with pytest.raises(AirflowFailException, match=f"^{type(original).__name__}:") as caught:
        _raiser(original)()

    assert caught.value.__cause__ is original


@pytest.mark.parametrize(
    "original",
    [httpx.ConnectError("x"), RuntimeError("x")],
    ids=["ConnectError", "RuntimeError"],
)
def test_fail_fast_keeps_retryable_errors(original: Exception) -> None:
    with pytest.raises(type(original)) as caught:
        _raiser(original)()

    assert caught.value is original


def _alpaca(status: int) -> AlpacaClient:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={}))
    return AlpacaClient(
        "key",
        "secret",
        httpx.Client(transport=transport),
        retry_wait=wait_none(),
        max_attempts=2,
    )


def test_alpaca_401_is_deterministic_and_exhausted_503_is_not() -> None:
    with pytest.raises(AlpacaError) as unauthorised:
        _alpaca(401).option_snapshots("SPY")
    with pytest.raises(AlpacaError) as unavailable:
        _alpaca(503).option_snapshots("SPY")

    assert is_deterministic(unauthorised.value)
    assert not is_deterministic(unavailable.value)


def _dolthub(response: Callable[[httpx.Request], httpx.Response]) -> DoltHubClient:
    return DoltHubClient(
        httpx.Client(transport=httpx.MockTransport(response)),
        page_pause_s=0,
        retry_wait=wait_none(),
        max_attempts=2,
    )


def _dolthub_failure(response: Callable[[httpx.Request], httpx.Response]) -> DoltHubError:
    with pytest.raises(DoltHubError) as caught:
        _dolthub(response).query("select 1")
    return caught.value


def test_dolthub_403_is_deterministic_and_exhausted_503_is_not() -> None:
    forbidden = _dolthub_failure(lambda request: httpx.Response(403, json={}))
    unavailable = _dolthub_failure(lambda request: httpx.Response(503, json={}))

    assert is_deterministic(forbidden)
    assert not is_deterministic(unavailable)


def test_dolthub_exhausted_429_and_timeouts_are_retryable() -> None:
    throttled = _dolthub_failure(lambda request: httpx.Response(429, json={}))
    timed_out = _dolthub_failure(
        lambda request: httpx.Response(
            200,
            json={
                "query_execution_status": "Error",
                "query_execution_message": "deadline exceeded",
            },
        )
    )

    assert not is_deterministic(throttled)
    assert not is_deterministic(timed_out)


@pytest.mark.parametrize(
    "response",
    [
        lambda request: httpx.Response(404, text="not found"),
        lambda request: httpx.Response(200, text="<html>not json</html>"),
        lambda request: httpx.Response(200, json=["not", "a", "dict"]),
        lambda request: httpx.Response(
            200, json={"query_execution_status": "Error", "query_execution_message": "syntax error"}
        ),
    ],
    ids=["404", "non-json", "unexpected-shape", "sql-error"],
)
def test_other_dolthub_failures_are_deterministic(
    response: Callable[[httpx.Request], httpx.Response],
) -> None:
    assert is_deterministic(_dolthub_failure(response))


def test_fail_fast_converts_a_dolthub_403_and_keeps_an_exhausted_503() -> None:
    forbidden = _dolthub_failure(lambda request: httpx.Response(403, json={}))
    unavailable = _dolthub_failure(lambda request: httpx.Response(503, json={}))

    with pytest.raises(AirflowFailException, match="^DoltHubError:") as caught:
        _raiser(forbidden)()
    assert caught.value.__cause__ is forbidden
    with pytest.raises(DoltHubError) as retryable:
        _raiser(unavailable)()
    assert retryable.value is unavailable


def test_fail_fast_passes_skip_and_return_values_and_preserves_name_doc_signature() -> None:
    @fail_fast
    def skipping(flag: int, *, name: str = "x") -> str:
        """Skip when asked."""
        if flag:
            raise AirflowSkipException("nothing to do")
        return name

    assert skipping(0, name="y") == "y"
    with pytest.raises(AirflowSkipException):
        skipping(1)
    assert skipping.__name__ == "skipping"
    assert skipping.__doc__ == "Skip when asked."
    assert str(inspect.signature(skipping)) == "(flag: int, *, name: str = 'x') -> str"
    assert cast(Any, skipping).oap_fail_fast is True


def test_airflow_failures_are_not_wrapped_again() -> None:
    failure = AirflowFailException("already final")

    with pytest.raises(AirflowFailException) as caught:
        _raiser(failure)()

    assert caught.value is failure


def test_bronze_writers_pool_name() -> None:
    assert BRONZE_WRITERS_POOL == "bronze_writers"
