"""Project-wide defaults shared by every oap DAG.

Every DAG passes ``DEFAULT_ARGS`` as its ``default_args`` so that retries, the task SLA
and failure logging are consistent. ``tests/dags/test_dag_import.py`` checks every loaded DAG
for them; ``tests/dags/test_common.py`` checks the callback itself. The callback only logs;
routing that log line to a pager or chat channel is a later phase.

The module also holds the small helpers the ingest DAGs share: the watchlist seed, the bronze
table handle and a local staging directory. Heavy imports (pyiceberg, pandas) stay inside the
helpers so that parsing a DAG file never pays for them.
"""

import csv
import functools
import logging
import re
import tempfile
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from airflow.exceptions import AirflowException, AirflowFailException
from airflow.utils.context import Context

if TYPE_CHECKING:
    from pyiceberg.table import Table

    from oap.ingest.tables import TableSpec

logger = logging.getLogger(__name__)


def log_failure(context: Context) -> None:
    """Log the identity of a failed task instance and the exception that failed it.

    Args:
        context: The Airflow task context passed to ``on_failure_callback``.
    """
    task_instance = context.get("task_instance")
    exception = context.get("exception")
    # Type name and message only: the repr of some exceptions (an HTTP error carrying request
    # headers, for example) can include credentials.
    logger.error(
        "Task failed: dag_id=%s task_id=%s logical_date=%s exception=%s: %s",
        task_instance.dag_id if task_instance else None,
        task_instance.task_id if task_instance else None,
        context.get("logical_date"),
        type(exception).__name__ if exception is not None else None,
        exception,
    )


DEFAULT_ARGS: dict[str, Any] = {
    "owner": "oap",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "sla": timedelta(hours=1),
    "email_on_failure": False,
    "on_failure_callback": log_failure,
}


BRONZE_WRITERS_POOL = "bronze_writers"
"""A one-slot Airflow pool, created by ``airflow-init``; every bronze table commit runs in it.

The local catalog is a single SQLite file, so two tasks committing to the bronze table at the
same time (a backfill month and the daily snapshot, say) would fight over its write lock.
"""


def is_deterministic(exc: BaseException) -> bool:
    """Say whether retrying a task that raised ``exc`` cannot change the outcome.

    Deterministic: bad or missing Alpaca credentials, an HTTP 4xx other than 429, a non-JSON
    body, an unexpected response shape, a SQL error, the wrong session, a schema or quality
    failure, and any ``ValueError`` (``pyarrow.ArrowInvalid`` is one). Retryable: transport
    errors, and an ``AlpacaError`` or ``DoltHubError`` raised after the client's own retries
    ran out (429, 5xx, timeouts), which carries that module's ``_RetryableError`` as
    ``__cause__``.

    Args:
        exc: The exception a task raised.

    Returns:
        True when the task should fail at once instead of using its retries.
    """
    import pandera.errors
    import pyarrow as pa

    from oap.ingest.alpaca import AlpacaError
    from oap.ingest.alpaca import _RetryableError as AlpacaRetryable
    from oap.ingest.dolthub import DoltHubError
    from oap.ingest.dolthub import _RetryableError as DoltHubRetryable
    from oap.quality.bronze_suite import BronzeQualityError

    if isinstance(exc, AlpacaError):
        return not isinstance(exc.__cause__, AlpacaRetryable)
    if isinstance(exc, DoltHubError):
        return not isinstance(exc.__cause__, DoltHubRetryable)
    return isinstance(
        exc, ValueError | pa.ArrowInvalid | pandera.errors.SchemaErrors | BronzeQualityError
    )


def fail_fast[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Turn deterministic errors into ``AirflowFailException`` so the task is not retried.

    Put it under ``@task``. Retries (``DEFAULT_ARGS`` allows two, five minutes apart) exist
    for flaky networks; a malformed symbol or a failed quality gate fails identically every
    time and would only delay the red run by ten minutes. Airflow's own exceptions (skip,
    fail) and retryable errors pass through unchanged.

    Args:
        func: The task body.

    Returns:
        A wrapper with the same name, docstring and signature.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except AirflowException:
            raise
        except Exception as exc:
            if is_deterministic(exc):
                raise AirflowFailException(f"{type(exc).__name__}: {exc}") from exc
            raise

    cast(Any, wrapper).oap_fail_fast = True
    return wrapper


WATCHLIST_PATH = Path(__file__).resolve().parents[1] / "dbt" / "seeds" / "watchlist.csv"
"""The dbt watchlist seed; ``/opt/airflow/dbt/seeds/watchlist.csv`` in the Airflow containers."""


def normalize_symbols(symbols: Sequence[str]) -> list[str]:
    """Upper-case and trim tickers, dropping blanks and repeats but keeping first-seen order.

    Args:
        symbols: Tickers as typed by a user or read from the seed.

    Returns:
        The cleaned tickers.
    """
    cleaned = (symbol.strip().upper() for symbol in symbols)
    return list(dict.fromkeys(symbol for symbol in cleaned if symbol))


def read_watchlist(path: Path = WATCHLIST_PATH) -> list[str]:
    """Return the tickers of the watchlist seed, in file order.

    Args:
        path: CSV with a ``symbol`` column.

    Returns:
        Cleaned tickers (see ``normalize_symbols``).
    """
    with path.open(newline="") as handle:
        return normalize_symbols([row["symbol"] for row in csv.DictReader(handle)])


def bronze_table(spec: "TableSpec | None" = None) -> "Table":
    """Load a bronze table (the option chain by default) from the catalog the environment selects.

    Creates the namespace and table on first use, so a fresh local stack needs no setup.

    Args:
        spec: Which bronze table; ``OPTION_CHAIN`` when omitted.

    Returns:
        The table.
    """
    from oap.ingest.iceberg_writer import catalog_from_env, ensure_table, table_identifier
    from oap.ingest.tables import OPTION_CHAIN

    spec = OPTION_CHAIN if spec is None else spec
    return ensure_table(catalog_from_env(), table_identifier(spec=spec), spec=spec)


def staging_dir(*parts: str) -> Path:
    """Return (and create) a directory under the worker's temp dir for files passed between tasks.

    DataFrames never travel through XCom; a task writes a parquet file here and passes the
    path. This needs the producing and consuming tasks to share a filesystem, which holds for
    the LocalExecutor stack. Path parts are reduced to ``[A-Za-z0-9._-]`` so a run id such as
    ``manual__2026-10-05T22:00:00+00:00`` is a safe directory name.

    Args:
        parts: Sub-directories below ``<tmp>/oap``.

    Returns:
        The existing directory.
    """
    safe = [re.sub(r"[^A-Za-z0-9._-]", "_", part) for part in parts]
    path = Path(tempfile.gettempdir(), "oap", *safe)
    path.mkdir(parents=True, exist_ok=True)
    return path
