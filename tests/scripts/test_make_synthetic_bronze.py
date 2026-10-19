from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast

import pandas as pd
import pytest
from pyiceberg.table import Table

from oap.ingest.iceberg_writer import content_hash, read_partition, write_partition
from oap.ingest.local_catalog import LocalCatalog
from oap.ingest.price_schema import PRICE_SCHEMA
from oap.ingest.schema import BRONZE_FRAME, frame_from_records
from oap.ingest.tables import OPTION_CHAIN, UNDERLYING_PRICE
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


# --rewrite-slice

SESSION = date(2024, 1, 10)
CHAIN_KEY = ("option_chain", SESSION, "dolthub")
PRICE_KEY = ("underlying_price", SESSION, "dolthub_stocks")
Key = tuple[str, date, str]
Slices = dict[Key, pd.DataFrame]


def _slices(out: Path) -> Slices:
    """Every slice of both tables, keyed by (table, trade_date, source)."""
    catalog = _catalog(out)
    chain = catalog.load_table(("bronze", "option_chain"))
    prices = catalog.load_table(("bronze", "underlying_price"))
    slices: Slices = {}
    for session in synthetic.DOLTHUB_SESSIONS:
        slices["option_chain", session, "dolthub"] = read_partition(
            chain, trade_date=session, source="dolthub"
        )
    for session in synthetic.ALPACA_SESSIONS:
        slices["option_chain", session, "alpaca_indicative"] = read_partition(
            chain, trade_date=session, source="alpaca_indicative"
        )
    for session in synthetic.SESSIONS:
        slices["underlying_price", session, "dolthub_stocks"] = read_partition(
            prices, trade_date=session, source="dolthub_stocks", spec=UNDERLYING_PRICE
        )
    return slices


def _hash(key: Key, frame: pd.DataFrame) -> str:
    spec = UNDERLYING_PRICE if key[0] == "underlying_price" else OPTION_CHAIN
    return content_hash(frame, spec=spec)


def _newest_stamp(frame: pd.DataFrame) -> datetime:
    return cast(datetime, frame["ingested_at"].max())


@pytest.fixture
def rewritten(tmp_path: Path) -> tuple[Path, Slices]:
    out = tmp_path / "cat"
    synthetic.write_catalog(out)
    before = _slices(out)
    assert synthetic.rewrite_slice(out, SESSION) == {"option_chain": 120, "underlying_price": 3}
    return out, before


def test_rewrite_changes_the_content_of_that_days_chain_and_price_slices(
    rewritten: tuple[Path, Slices],
) -> None:
    out, before = rewritten
    after = _slices(out)

    for key in (CHAIN_KEY, PRICE_KEY):
        assert _hash(key, after[key]) != _hash(key, before[key])
        assert len(after[key]) == len(before[key])


def test_rewrite_stamps_the_rewritten_slices_later_than_everything_before(
    rewritten: tuple[Path, Slices],
) -> None:
    out, before = rewritten
    after = _slices(out)
    newest_before = max(_newest_stamp(frame) for frame in before.values())

    for key in (CHAIN_KEY, PRICE_KEY):
        assert set(after[key]["ingested_at"]) == {newest_before + timedelta(hours=1)}


def test_rewrite_leaves_every_other_slice_untouched(rewritten: tuple[Path, Slices]) -> None:
    out, before = rewritten
    after = _slices(out)

    assert set(after) == set(before)
    for key in set(before) - {CHAIN_KEY, PRICE_KEY}:
        assert _hash(key, after[key]) == _hash(key, before[key])
        assert _newest_stamp(after[key]) == _newest_stamp(before[key])


def test_rewrite_raises_one_quote_and_one_close_and_keeps_them_valid(
    rewritten: tuple[Path, Slices],
) -> None:
    out, before = rewritten
    after = _slices(out)

    old_chain = before[CHAIN_KEY].set_index("occ_symbol")
    new_chain = after[CHAIN_KEY].set_index("occ_symbol").loc[old_chain.index]
    moved = (new_chain["bid"].astype(float) != old_chain["bid"].astype(float)) | (
        new_chain["ask"].astype(float) != old_chain["ask"].astype(float)
    )
    assert int(moved.sum()) == 1
    assert (new_chain["bid"].astype(float) < new_chain["ask"].astype(float)).all()
    old_price = before[PRICE_KEY].set_index("underlying")
    new_price = after[PRICE_KEY].set_index("underlying").loc[old_price.index]
    assert int((new_price["close"].astype(float) != old_price["close"].astype(float)).sum()) == 1
    closes = new_price["close"].astype(float).tolist()
    highs = new_price["high"].astype(float).tolist()
    for underlying, close, high in zip(new_price.index, closes, highs, strict=True):
        ref = synthetic.UNDERLYINGS[str(underlying)]
        assert ref + min(synthetic.STRIKE_OFFSETS) < close < ref + max(synthetic.STRIKE_OFFSETS)
        assert close <= high
    UNDERLYING_PRICE.frame_schema.validate(after[PRICE_KEY])


def test_rewrite_covers_both_chain_sources_of_an_overlap_session(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    synthetic.write_catalog(out)
    before = _slices(out)

    synthetic.rewrite_slice(out, date(2024, 1, 18))

    after = _slices(out)
    for source in ("dolthub", "alpaca_indicative"):
        key = ("option_chain", date(2024, 1, 18), source)
        assert _hash(key, after[key]) != _hash(key, before[key])
        assert len(after[key]) == len(before[key]) == 60


def test_a_prices_only_rewrite_leaves_the_chain_alone(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    synthetic.write_catalog(out)
    before = _slices(out)

    rows = synthetic.rewrite_slice(out, SESSION, prices_only=True)

    after = _slices(out)
    assert rows == {"option_chain": 0, "underlying_price": 3}
    assert _hash(PRICE_KEY, after[PRICE_KEY]) != _hash(PRICE_KEY, before[PRICE_KEY])
    assert _newest_stamp(after[PRICE_KEY]) > _newest_stamp(before[PRICE_KEY])
    assert _hash(CHAIN_KEY, after[CHAIN_KEY]) == _hash(CHAIN_KEY, before[CHAIN_KEY])
    assert _newest_stamp(after[CHAIN_KEY]) == _newest_stamp(before[CHAIN_KEY])


def test_main_rejects_prices_only_without_a_rewrite(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        synthetic.main(["--out", str(tmp_path / "cat"), "--prices-only"])


def test_a_second_rewrite_is_stamped_later_again(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    synthetic.write_catalog(out)
    synthetic.rewrite_slice(out, SESSION)
    first = _newest_stamp(_slices(out)[CHAIN_KEY])

    synthetic.rewrite_slice(out, SESSION)

    assert _newest_stamp(_slices(out)[CHAIN_KEY]) == first + timedelta(hours=1)


def test_rewrite_rejects_a_date_that_is_not_a_synthetic_session(tmp_path: Path) -> None:
    out = tmp_path / "cat"
    synthetic.write_catalog(out)

    with pytest.raises(ValueError, match="not one of the synthetic sessions"):
        synthetic.rewrite_slice(out, date(2024, 1, 13))


def test_rewrite_needs_an_existing_catalog(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="holds no catalog.db"):
        synthetic.rewrite_slice(tmp_path / "missing", SESSION)


def test_main_rewrites_a_slice_without_replacing_the_catalog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cat"
    synthetic.main(["--out", str(out)])
    capsys.readouterr()

    assert synthetic.main(["--out", str(out), "--rewrite-slice", "2024-01-10"]) == 0

    assert "rewrote 2024-01-10: bronze.option_chain 120 rows" in capsys.readouterr().out
    assert (_count(out, "option_chain"), _count(out, "underlying_price")) == (1380, 38)
