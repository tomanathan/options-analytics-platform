from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest
from pyiceberg.table import Table

from dags import iceberg_maintenance
from oap.ingest.iceberg_writer import (
    catalog_from_env,
    content_hash,
    ensure_table,
    partition_file_counts,
    read_partition,
    write_partition,
)
from oap.ingest.schema import to_arrow
from oap.ingest.tables import BRONZE_TABLES, OPTION_CHAIN, UNDERLYING_PRICE, TableSpec
from tests.bronze_factory import bronze_frame
from tests.ingest.price_factory import price_frame

D1 = date(2024, 1, 2)
SOURCES = {"option_chain": "dolthub", "underlying_price": "dolthub_stocks"}


def _frame(spec: TableSpec, underlying: str) -> pd.DataFrame:
    if spec is OPTION_CHAIN:
        return bronze_frame(D1, underlyings=(underlying,), rows_per_underlying=4)
    return price_frame(D1, (underlying,))


@pytest.fixture
def tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Table]:
    catalog = catalog_from_env(
        {
            "OAP_ICEBERG_CATALOG": "sql",
            "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/catalog.db",
            "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/warehouse",
        }
    )
    by_name = {spec.name: ensure_table(catalog, spec=spec) for spec in BRONZE_TABLES}
    monkeypatch.setattr(iceberg_maintenance, "bronze_table", lambda spec=None: by_name[spec.name])
    return by_name


def _callable(task_id: str) -> Any:
    task = iceberg_maintenance.iceberg_maintenance().get_task(task_id)
    return cast(Any, task).python_callable


def _two_file_slice(table: Table, spec: TableSpec) -> None:
    source = SOURCES[spec.name]
    write_partition(table, _frame(spec, "SPY"), trade_date=D1, source=source)
    # A raw append of a disjoint underlying leaves a second data file in the same slice.
    table.append(to_arrow(_frame(spec, "QQQ"), spec.arrow_schema))


@pytest.mark.parametrize("task_id", ["expire_snapshots", "compact"])
def test_both_tasks_use_the_bronze_writers_pool(task_id: str) -> None:
    task = iceberg_maintenance.iceberg_maintenance().get_task(task_id)

    assert task.pool == "bronze_writers"


def test_compact_rewrites_the_multi_file_slices_of_every_table(tables: dict[str, Table]) -> None:
    before = {}
    for spec in BRONZE_TABLES:
        table = tables[spec.name]
        _two_file_slice(table, spec)
        assert set(partition_file_counts(table).values()) == {2}
        before[spec.name] = content_hash(
            read_partition(table, trade_date=D1, source=SOURCES[spec.name], spec=spec), spec=spec
        )

    rewritten = _callable("compact")()

    assert rewritten == {"option_chain": 1, "underlying_price": 1}
    for spec in BRONZE_TABLES:
        table = tables[spec.name].refresh()
        assert set(partition_file_counts(table).values()) == {1}
        after = read_partition(table, trade_date=D1, source=SOURCES[spec.name], spec=spec)
        assert content_hash(after, spec=spec) == before[spec.name]
        assert sorted(after["underlying"].unique()) == ["QQQ", "SPY"]


def test_compact_leaves_single_file_slices_alone(tables: dict[str, Table]) -> None:
    write_partition(
        tables["underlying_price"],
        _frame(UNDERLYING_PRICE, "SPY"),
        trade_date=D1,
        source="dolthub_stocks",
    )
    snapshots = len(tables["underlying_price"].refresh().metadata.snapshots)

    assert _callable("compact")() == {"option_chain": 0, "underlying_price": 0}
    assert len(tables["underlying_price"].refresh().metadata.snapshots) == snapshots


def test_expire_snapshots_on_tables_without_snapshots_does_not_raise(
    tables: dict[str, Table],
) -> None:
    assert _callable("expire_snapshots")() == {"option_chain": 0, "underlying_price": 0}


def test_expire_snapshots_keeps_recent_snapshots_of_every_table(tables: dict[str, Table]) -> None:
    for spec in BRONZE_TABLES:
        write_partition(
            tables[spec.name], _frame(spec, "SPY"), trade_date=D1, source=SOURCES[spec.name]
        )

    remaining = _callable("expire_snapshots")()

    assert remaining == {"option_chain": 1, "underlying_price": 1}
