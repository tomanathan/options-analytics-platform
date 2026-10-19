from datetime import date
from pathlib import Path

import pytest
from pyiceberg.table import Table

from oap.ingest.iceberg_writer import write_partition
from oap.ingest.local_catalog import LocalCatalog
from oap.ingest.price_schema import PRICE_SCHEMA
from oap.ingest.schema import BRONZE_FRAME, frame_from_records
from oap.ingest.tables import UNDERLYING_PRICE
from scripts import make_synthetic_bronze as synthetic


def _catalog(out: Path) -> LocalCatalog:
    root = out.absolute()
    return LocalCatalog(
        "oap", uri=f"sqlite:///{root}/catalog.db", warehouse=(root / "warehouse").as_uri()
    )


def _count(out: Path, name: str) -> int:
    table: Table = _catalog(out).load_table(("bronze", name))
    return int(table.scan().to_arrow().num_rows)


def test_there_are_thirteen_sessions_and_the_last_two_overlap_alpaca() -> None:
    assert len(synthetic.SESSIONS) == 13
    assert synthetic.DOLTHUB_SESSIONS[-1] == date(2024, 1, 18)
    alpaca = synthetic.ALPACA_SESSIONS
    assert alpaca == (date(2024, 1, 18), date(2024, 1, 19))


def test_chain_records_total_1260_dolthub_and_120_alpaca_rows() -> None:
    dolthub = sum(len(synthetic.chain_records(d, "dolthub")) for d in synthetic.DOLTHUB_SESSIONS)
    alpaca = sum(
        len(synthetic.chain_records(d, "alpaca_indicative")) for d in synthetic.ALPACA_SESSIONS
    )
    assert (dolthub, alpaca) == (1260, 120)


@pytest.mark.parametrize(
    ("source", "sessions"),
    [("dolthub", synthetic.DOLTHUB_SESSIONS), ("alpaca_indicative", synthetic.ALPACA_SESSIONS)],
)
def test_every_chain_slice_passes_the_bronze_contract(
    source: str, sessions: tuple[date, ...]
) -> None:
    for session in sessions:
        frame = frame_from_records(synthetic.chain_records(session, source))
        BRONZE_FRAME.validate(frame)


def test_dolthub_rows_have_no_last_volume_or_underlying_price() -> None:
    for record in synthetic.chain_records(date(2024, 1, 2), "dolthub"):
        assert record["last"] is None
        assert record["volume"] is None
        assert record["underlying_price"] is None


def test_alpaca_rows_carry_the_underlying_close() -> None:
    for record in synthetic.chain_records(date(2024, 1, 19), "alpaca_indicative"):
        assert record["underlying_price"] == synthetic.close(
            record["underlying"], date(2024, 1, 19)
        )
        assert record["last"] is not None


def test_price_rows_skip_only_the_gap() -> None:
    rows = synthetic.price_rows()
    assert len(rows) == 38
    assert not [r for r in rows if (r["underlying"], r["trade_date"]) in synthetic.PRICE_GAPS]
    assert {(r["underlying"], r["trade_date"]) for r in rows} >= {("SPY", date(2024, 1, 19))}


def test_price_rows_pass_the_price_contract() -> None:
    frame = frame_from_records(synthetic.price_rows(), PRICE_SCHEMA)
    UNDERLYING_PRICE.frame_schema.validate(frame)


def test_closes_lie_strictly_inside_the_strike_range() -> None:
    lowest = min(synthetic.STRIKE_OFFSETS)
    highest = max(synthetic.STRIKE_OFFSETS)
    for underlying, ref in synthetic.UNDERLYINGS.items():
        for session in synthetic.SESSIONS:
            assert ref + lowest < synthetic.close(underlying, session) < ref + highest


def test_quotes_are_never_crossed_or_negative() -> None:
    for record in synthetic.chain_records(date(2024, 1, 2), "dolthub"):
        assert 0 <= record["bid"] < record["ask"]


def test_main_writes_both_tables_and_a_rerun_gives_the_same_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cat"
    assert synthetic.main(["--out", str(out)]) == 0
    assert (
        "bronze.option_chain: 1380 rows; bronze.underlying_price: 38 rows"
        in capsys.readouterr().out
    )
    assert (_count(out, "option_chain"), _count(out, "underlying_price")) == (1380, 38)
    assert synthetic.main(["--out", str(out)]) == 0
    assert (_count(out, "option_chain"), _count(out, "underlying_price")) == (1380, 38)


def test_it_refuses_a_non_empty_directory_without_a_catalog(tmp_path: Path) -> None:
    out = tmp_path / "precious"
    out.mkdir()
    (out / "notes.txt").write_text("keep")
    with pytest.raises(ValueError, match="refusing"):
        synthetic.write_catalog(out)
    assert (out / "notes.txt").read_text() == "keep"


def test_written_slices_are_replaced_not_appended(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    synthetic.write_catalog(out)
    table = _catalog(out).load_table(("bronze", "underlying_price"))
    frame = frame_from_records(synthetic.price_rows()[:3], PRICE_SCHEMA)
    first_day = synthetic.SESSIONS[0]
    write_partition(
        table, frame, trade_date=first_day, source="dolthub_stocks", spec=UNDERLYING_PRICE
    )
    assert _count(out, "underlying_price") == 38
