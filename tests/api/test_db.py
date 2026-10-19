import os
from pathlib import Path

import duckdb
import pytest

from oap.analytics.scoring import SPREAD_COLUMNS
from oap.api import db
from oap.api.db import GoldReader, db_signature
from oap.api.errors import DatabaseBusy, DatabaseMissing, GoldMissing
from oap.api.settings import ApiSettings
from tests.api.gold import GoldFixture


def _reader(path: Path) -> GoldReader:
    return GoldReader(path, ApiSettings().duckdb_config)


def test_signature_changes_with_the_file(tmp_path: Path) -> None:
    path = tmp_path / "x.duckdb"
    path.write_bytes(b"abc")
    first = db_signature(path)
    assert first[1] == 3
    assert first[2] == -1
    path.with_name("x.duckdb.wal").write_bytes(b"wal!")
    assert db_signature(path)[2] == 4
    os.utime(path, ns=(0, first[0] + 1_000))
    assert db_signature(path)[0] == first[0] + 1_000


def test_signature_of_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(DatabaseMissing):
        db_signature(tmp_path / "absent.duckdb")


def test_read_binds_parameters_and_normalises_dates(gold: GoldFixture) -> None:
    quotes = _reader(gold.path).read(db.QUOTES_SQL, ["SPY"])
    assert set(quotes["underlying"]) == {"SPY"}
    assert str(quotes["trade_date"].dtype) == "datetime64[ns]"
    assert str(quotes["strike"].dtype) == "float64"
    assert quotes["trade_date"].is_monotonic_increasing


def test_a_hostile_parameter_is_data(gold: GoldFixture) -> None:
    frame = _reader(gold.path).read(db.QUOTES_SQL, ["SPY' OR '1'='1"])
    assert frame.empty


def test_read_many_uses_one_connection(gold: GoldFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = duckdb.connect
    opened: list[int] = []

    def counting(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        opened.append(1)
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(duckdb, "connect", counting)
    frames = _reader(gold.path).read_many([(db.LATEST_SESSION_SQL, []), (db.UNDERLYINGS_SQL, [])])
    assert len(frames) == 2
    assert opened == [1]


def test_the_connection_is_closed_after_a_read(gold: GoldFixture) -> None:
    reader = _reader(gold.path)
    reader.read(db.LATEST_SESSION_SQL)
    writer = duckdb.connect(str(gold.path))
    writer.close()


def test_the_connection_is_closed_after_a_failed_read(gold: GoldFixture) -> None:
    with pytest.raises(GoldMissing):
        _reader(gold.path).read("select * from gold.no_such_table")
    duckdb.connect(str(gold.path)).close()


def test_a_missing_column_is_gold_missing(gold: GoldFixture) -> None:
    with pytest.raises(GoldMissing):
        _reader(gold.path).read("select no_such_column from gold.dim_underlying")


def test_a_missing_file_is_database_missing(tmp_path: Path) -> None:
    with pytest.raises(DatabaseMissing):
        _reader(tmp_path / "absent.duckdb").read("select 1")


def test_a_lock_conflict_is_database_busy(
    gold: GoldFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        raise duckdb.IOException('Could not set lock on file "x": Conflicting LOCK is held')

    monkeypatch.setattr(duckdb, "connect", refuse)
    with pytest.raises(DatabaseBusy):
        _reader(gold.path).read("select 1")


def test_writes_are_refused(gold: GoldFixture) -> None:
    with pytest.raises(duckdb.Error):
        _reader(gold.path).read("create table gold.sneaky as select 1")


def test_the_spread_query_selects_the_scoring_columns_in_order() -> None:
    assert "select " + ", ".join(SPREAD_COLUMNS) + " from gold.spread_scores" == db.SPREADS_SQL


def test_user_values_are_never_formatted_into_sql() -> None:
    for sql in (db.QUOTES_SQL, db.OUTCOMES_SQL, db.METRICS_SQL):
        assert "?" in sql
        assert "{" not in sql
        assert "%s" not in sql
