from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pyiceberg.table import Table

from oap.ingest.iceberg_writer import (
    catalog_from_env,
    content_hash,
    ensure_table,
    read_partition,
    write_partition,
)
from scripts import iceberg_count
from tests.bronze_factory import INGESTED_AT, bronze_frame

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)


@pytest.fixture
def catalog_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAP_ICEBERG_CATALOG", "sql")
    monkeypatch.setenv("OAP_ICEBERG_URI", f"sqlite:///{tmp_path}/catalog.db")
    monkeypatch.setenv("OAP_ICEBERG_WAREHOUSE", f"file://{tmp_path}/warehouse")


@pytest.fixture
def empty_table(catalog_env: None) -> Table:
    return ensure_table(catalog_from_env())


def _write(table: Table, day: date, *, seed: int = 0, ingested_at: datetime | None = None) -> None:
    frame = bronze_frame(
        day,
        underlyings=("SPY", "QQQ"),
        rows_per_underlying=4,
        seed=seed,
        ingested_at=ingested_at or INGESTED_AT,
    )
    write_partition(table, frame, trade_date=day, source="dolthub")


@pytest.fixture
def table(empty_table: Table) -> Table:
    _write(empty_table, D1)
    _write(empty_table, D2)
    return empty_table


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    assert iceberg_count.main(list(args)) == 0
    return capsys.readouterr().out


def _digest(out: str) -> str:
    (line,) = (line for line in out.splitlines() if line.startswith("content_digest "))
    return line.split()[1]


def _slice_hash(out: str, day: date) -> str:
    (line,) = (line for line in out.splitlines() if line.startswith(f"dolthub\t{day}\t"))
    return line.split("\t")[3]


def test_counts_per_slice_and_underlying(table: Table, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys)

    assert "dolthub\t2024-01-02\t8" in out
    assert "dolthub\t2024-01-03\t8" in out
    assert "underlying\tdolthub\tSPY\t2 days\t8 rows\t2024-01-02..2024-01-03" in out
    assert "total 16 rows in 2 slices, 2024-01-02 to 2024-01-03" in out
    assert "content_digest" not in out


def test_default_run_reads_no_full_rows(
    table: Table, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the default run must only scan the three count columns")

    monkeypatch.setattr(iceberg_count, "read_partition", forbidden)

    assert iceberg_count.main([]) == 0


def test_hash_ignores_ingested_at(table: Table, capsys: pytest.CaptureFixture[str]) -> None:
    first = _run(capsys, "--hash")
    _write(table, D1, ingested_at=datetime(2024, 1, 5, 22, 0, tzinfo=UTC))
    second = _run(capsys, "--hash")

    assert _digest(first) == _digest(second)
    expected = content_hash(read_partition(table, trade_date=D1, source="dolthub"))
    assert _slice_hash(second, D1) == expected


def test_hash_changes_when_a_slice_changes(
    table: Table, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _run(capsys, "--hash")
    _write(table, D2, seed=1)
    after = _run(capsys, "--hash")

    assert _digest(before) != _digest(after)
    assert _slice_hash(before, D1) == _slice_hash(after, D1)
    assert _slice_hash(before, D2) != _slice_hash(after, D2)


def test_start_filter_narrows(table: Table, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "--start", "2024-01-03")

    assert "dolthub\t2024-01-03\t8" in out
    assert "2024-01-02\t" not in out
    assert "total 8 rows in 1 slices, 2024-01-03 to 2024-01-03" in out


def test_end_and_source_filters_narrow(table: Table, capsys: pytest.CaptureFixture[str]) -> None:
    assert "total 8 rows in 1 slices, 2024-01-02" in _run(capsys, "--end", "2024-01-02")
    assert _run(capsys, "--source", "alpaca_indicative").strip() == "total 0 rows"


def test_summary_omits_slice_lines(table: Table, capsys: pytest.CaptureFixture[str]) -> None:
    out = _run(capsys, "--summary")

    assert "dolthub\t2024-01-02\t8" not in out
    assert "underlying\tdolthub\tQQQ" in out
    assert "total 16 rows in 2 slices" in out


def test_missing_table_returns_1(catalog_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    catalog_from_env()

    assert iceberg_count.main([]) == 1
    assert "does not exist yet" in capsys.readouterr().err


def test_empty_table_prints_total_0(empty_table: Table, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(capsys).strip() == "total 0 rows"


def test_combined_digest_is_order_independent() -> None:
    a = {("dolthub", D1): "aa", ("dolthub", D2): "bb", ("alpaca_indicative", D2): "cc"}
    b = dict(reversed(list(a.items())))

    assert iceberg_count.combined_digest(a) == iceberg_count.combined_digest(b)
    assert iceberg_count.combined_digest(a) != iceberg_count.combined_digest(
        {**a, ("dolthub", D1): "zz"}
    )
