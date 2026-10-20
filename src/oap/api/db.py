"""Short-lived, read-only access to the gold schema of the DuckDB file.

DuckDB lets one process write or many processes read, never both. Any connection this
service keeps open blocks the dbt writer, so ``GoldReader`` opens the file, runs its queries
and closes it in the same call, and the store serves from memory afterwards.

Every query uses ``?`` parameters; no value is formatted into SQL. The only text spliced into
SQL is the spread column list, which is a constant of ``oap.analytics.scoring``.

Units: those of the gold tables: strikes, prices and closes in dollars per share,
``dte_days`` in calendar days, implied volatility as a decimal.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import duckdb
import pandas as pd

from oap.analytics.scoring import SPREAD_COLUMNS
from oap.api.errors import DatabaseBusy, DatabaseMissing, GoldMissing

Signature = tuple[int, int, int]
"""``(mtime_ns, size, wal size or -1)`` of the database file."""

Query = tuple[str, Sequence[object]]
"""A SQL text with its ``?`` parameters."""

UNDERLYINGS_SQL: Final = (
    "select d.symbol, d.sector, min(q.trade_date) as first_session, "
    "max(q.trade_date) as last_session, count(distinct q.trade_date) as n_sessions "
    "from gold.dim_underlying d join gold.fct_option_quote q on q.underlying = d.symbol "
    "group by d.symbol, d.sector order by d.symbol"
)
QUOTES_SQL: Final = (
    "select underlying, trade_date, expiration, cast(strike as double) as strike, "
    "option_right, cast(bid as double) as bid, cast(ask as double) as ask, "
    "cast(mid as double) as mid, cast(source_iv as double) as source_iv, "
    "cast(source_delta as double) as source_delta, cast(moneyness as double) as moneyness, "
    "cast(underlying_close as double) as underlying_close, dte_days "
    "from gold.fct_option_quote where underlying = ? "
    "order by trade_date, expiration, strike, option_right"
)
SESSION_QUOTES_SQL: Final = (
    "select underlying, trade_date, expiration, cast(strike as double) as strike, "
    "option_right, cast(bid as double) as bid, cast(ask as double) as ask, "
    "cast(mid as double) as mid, cast(source_iv as double) as source_iv, "
    "cast(source_delta as double) as source_delta, cast(moneyness as double) as moneyness, "
    "cast(underlying_close as double) as underlying_close, dte_days "
    "from gold.fct_option_quote where trade_date = ? "
    "order by underlying, trade_date, expiration, strike, option_right"
)
"""Every underlying's quotes of one session, with the columns and order of ``QUOTES_SQL``."""
OUTCOMES_SQL: Final = (
    "select expiration, settlement_date, cast(settlement_close as double) as settlement_close "
    "from gold.fct_expiration_outcome where underlying = ?"
)
SPREADS_SQL: Final = "select " + ", ".join(SPREAD_COLUMNS) + " from gold.spread_scores"
MAPS_SQL: Final = (
    "select map_id, fold, train_cutoff, train_max_expiration, knot_index, predicted, "
    "calibrated, n_samples, is_identity from gold.calibration_map"
)
METRICS_SQL: Final = (
    "select segment_type, segment, variant, metric, value, ci_low, ci_high, n_predictions, "
    "n_snapshots, n_clusters from gold.calibration_metrics where segment_type = ?"
)
LATEST_SESSION_SQL: Final = "select max(trade_date) as latest_session from gold.fct_option_quote"


def db_signature(path: Path) -> Signature:
    """Return the cheap fingerprint of the database file, without opening it.

    Args:
        path: The DuckDB file.

    Returns:
        ``(mtime_ns, size in bytes, WAL size in bytes or -1 without a WAL)``. It changes
        whenever a writer commits or checkpoints.

    Raises:
        DatabaseMissing: If the file does not exist.
    """
    try:
        stat = os.stat(path)
    except FileNotFoundError as exc:
        raise DatabaseMissing(f"{path} does not exist") from exc
    try:
        wal = os.stat(path.with_name(path.name + ".wal")).st_size
    except FileNotFoundError:
        wal = -1
    return (stat.st_mtime_ns, stat.st_size, wal)


def to_ns(frame: pd.DataFrame) -> pd.DataFrame:
    """Give every ``datetime64`` column nanosecond resolution.

    DuckDB returns microseconds; one resolution keeps comparisons and merges simple, as in
    ``oap.analytics.io``.

    Args:
        frame: Frame to normalise.

    Returns:
        The same frame with ``datetime64[ns]`` columns.
    """
    for name in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[name]):
            frame[name] = frame[name].astype("datetime64[ns]")
    return frame


class GoldReader:
    """Run read-only queries against the gold schema, one short connection per call."""

    def __init__(self, path: Path, config: Mapping[str, str]) -> None:
        """Store where to read and how to connect.

        Args:
            path: The DuckDB file.
            config: DuckDB configuration, such as threads and memory limit.
        """
        self._path = path
        self._config: dict[str, str | bool | int | float | list[str]] = dict(config)

    def read(self, sql: str, params: Sequence[object] = ()) -> pd.DataFrame:
        """Run one parameterised query.

        Args:
            sql: A ``select`` statement with ``?`` placeholders.
            params: Values for the placeholders.

        Returns:
            The rows, with dates as ``datetime64[ns]``.

        Raises:
            DatabaseMissing: If the file does not exist.
            DatabaseBusy: If a writer holds the lock.
            GoldMissing: If a table or column is missing.
        """
        return self.read_many([(sql, params)])[0]

    def read_many(self, queries: Sequence[Query]) -> list[pd.DataFrame]:
        """Run several parameterised queries on one connection.

        Args:
            queries: ``(sql, params)`` pairs, run in order.

        Returns:
            One frame per query, with dates as ``datetime64[ns]``.

        Raises:
            DatabaseMissing: If the file does not exist.
            DatabaseBusy: If a writer holds the lock.
            GoldMissing: If a table or column is missing.
        """
        if not self._path.exists():
            raise DatabaseMissing(f"{self._path} does not exist")
        try:
            con = duckdb.connect(str(self._path), read_only=True, config=self._config)
        except duckdb.IOException as exc:
            if "lock" in str(exc).lower():
                raise DatabaseBusy(str(exc)) from exc
            raise
        try:
            return [to_ns(con.execute(sql, list(params)).df()) for sql, params in queries]
        except (duckdb.CatalogException, duckdb.BinderException) as exc:
            raise GoldMissing(str(exc).splitlines()[0]) from exc
        finally:
            con.close()
