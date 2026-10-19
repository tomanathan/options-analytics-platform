from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from pyiceberg.table import Table

from oap.ingest.iceberg_writer import (
    catalog_from_env,
    content_hash,
    ensure_table,
    read_partition,
    write_partition,
)
from oap.ingest.merge import merge_day, merge_into_slices
from oap.ingest.tables import OPTION_CHAIN, UNDERLYING_PRICE
from tests.bronze_factory import bronze_frame
from tests.ingest.price_factory import price_frame

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
SOURCE = "dolthub_stocks"


@pytest.fixture
def table(tmp_path: Path) -> Table:
    catalog = catalog_from_env(
        {
            "OAP_ICEBERG_CATALOG": "sql",
            "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/catalog.db",
            "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/warehouse",
        }
    )
    return ensure_table(catalog, spec=UNDERLYING_PRICE)


def _seed(table: Table) -> None:
    for day in (D1, D2):
        write_partition(table, price_frame(day, ("SPY", "QQQ")), trade_date=day, source=SOURCE)


def _spy(day: date, seed: int) -> pd.DataFrame:
    return price_frame(day, ("SPY",), seed)


def _by_underlying(table: Table, day: date) -> dict[str, int]:
    frame = read_partition(table, trade_date=day, source=SOURCE)
    return {str(k): int(v) for k, v in frame.groupby("underlying", observed=True).size().items()}


def _hash(frame: pd.DataFrame) -> str:
    return content_hash(frame, spec=UNDERLYING_PRICE)


def test_loading_one_symbol_keeps_the_other_symbols_of_the_slice(table: Table) -> None:
    _seed(table)
    fetched = pd.concat([_spy(D1, seed=1), _spy(D2, seed=1)], ignore_index=True)

    counts = merge_into_slices(table, fetched, source=SOURCE)

    assert counts == {"days": 2, "unchanged": 0, "rows": 4}
    assert _by_underlying(table, D1) == {"QQQ": 1, "SPY": 1}
    stored = read_partition(table, trade_date=D1, source=SOURCE)
    assert _hash(stored[stored["underlying"] == "SPY"]) == _hash(_spy(D1, seed=1))
    qqq = price_frame(D1, ("SPY", "QQQ"))
    assert _hash(stored[stored["underlying"] == "QQQ"]) == _hash(qqq[qqq["underlying"] == "QQQ"])


def test_reloading_the_same_data_commits_nothing(table: Table) -> None:
    _seed(table)
    fetched = pd.concat([_spy(D1, seed=1), _spy(D2, seed=1)], ignore_index=True)
    merge_into_slices(table, fetched, source=SOURCE)
    snapshots = len(table.refresh().metadata.snapshots)

    counts = merge_into_slices(table, fetched, source=SOURCE)

    assert counts == {"days": 0, "unchanged": 2, "rows": 0}
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_an_underlying_absent_from_a_fetch_keeps_its_rows(table: Table) -> None:
    _seed(table)
    before = _hash(read_partition(table, trade_date=D2, source=SOURCE))

    counts = merge_into_slices(table, _spy(D1, seed=1), source=SOURCE)

    assert counts == {"days": 1, "unchanged": 0, "rows": 2}
    assert _by_underlying(table, D1) == {"QQQ": 1, "SPY": 1}
    assert _hash(read_partition(table, trade_date=D2, source=SOURCE)) == before


def test_nothing_fetched_writes_nothing(table: Table) -> None:
    _seed(table)
    snapshots = len(table.refresh().metadata.snapshots)

    assert merge_into_slices(table, None, source=SOURCE) == {"days": 0, "unchanged": 0, "rows": 0}
    assert merge_into_slices(table, _spy(D1, seed=1).iloc[0:0], source=SOURCE) == {
        "days": 0,
        "unchanged": 0,
        "rows": 0,
    }
    assert len(table.refresh().metadata.snapshots) == snapshots


def test_a_first_load_creates_the_slice(table: Table) -> None:
    counts = merge_into_slices(table, _spy(D1, seed=1), source=SOURCE)

    assert counts == {"days": 1, "unchanged": 0, "rows": 1}
    assert _by_underlying(table, D1) == {"SPY": 1}


def test_staged_parquet_round_trips_into_a_valid_price_write(table: Table, tmp_path: Path) -> None:
    # fetch_month stages with to_parquet and write_month reads with dtype_backend="pyarrow".
    path = tmp_path / "2024-01.parquet"
    _spy(D1, seed=3).to_parquet(path, index=False)
    staged = pd.read_parquet(path, dtype_backend="pyarrow")

    assert merge_into_slices(table, staged, source=SOURCE)["rows"] == 1
    stored = read_partition(table, trade_date=D1, source=SOURCE)
    assert _hash(stored) == _hash(_spy(D1, seed=3))


def test_a_spec_that_is_not_the_tables_is_rejected(table: Table) -> None:
    with pytest.raises(ValueError, match="does not belong"):
        merge_into_slices(table, _spy(D1, seed=1), source=SOURCE, spec=OPTION_CHAIN)


def test_an_unknown_source_is_rejected(table: Table) -> None:
    with pytest.raises(ValueError, match="unknown source"):
        merge_into_slices(table, _spy(D1, seed=1), source="dolthub")


def test_merging_option_chain_slices_works_through_the_same_function(tmp_path: Path) -> None:
    catalog = catalog_from_env(
        {
            "OAP_ICEBERG_CATALOG": "sql",
            "OAP_ICEBERG_URI": f"sqlite:///{tmp_path}/other.db",
            "OAP_ICEBERG_WAREHOUSE": f"file://{tmp_path}/other",
        }
    )
    options = ensure_table(catalog)
    write_partition(
        options,
        bronze_frame(D1, underlyings=("SPY", "QQQ"), rows_per_underlying=4),
        trade_date=D1,
        source="dolthub",
    )

    counts = merge_into_slices(
        options,
        bronze_frame(D1, underlyings=("SPY",), rows_per_underlying=6, seed=1),
        source="dolthub",
    )

    assert counts == {"days": 1, "unchanged": 0, "rows": 10}


def test_merge_day_replaces_only_the_fetched_underlyings() -> None:
    existing = price_frame(D1, ("SPY", "QQQ"))
    fetched = _spy(D1, seed=5)

    merged = merge_day(existing, fetched)

    assert sorted(merged["underlying"]) == ["QQQ", "SPY"]
    assert _hash(merged[merged["underlying"] == "SPY"]) == _hash(fetched)


def test_merge_day_with_an_empty_fetch_keeps_the_existing_rows() -> None:
    existing = price_frame(D1, ("SPY", "QQQ"))

    merged = merge_day(existing, existing.iloc[0:0])

    assert _hash(merged) == _hash(existing)


def test_merge_day_of_two_empty_frames_is_empty() -> None:
    empty = UNDERLYING_PRICE.empty_frame()

    assert merge_day(empty, empty).empty
