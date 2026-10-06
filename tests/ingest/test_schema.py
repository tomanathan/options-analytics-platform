import string
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

import pandas as pd
import pandera.errors
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.ingest.schema import (
    BRONZE_FRAME,
    BRONZE_SCHEMA,
    SOURCES,
    empty_frame,
    frame_from_records,
    occ_symbol,
    parse_occ_symbol,
    split_crossed_quotes,
    to_arrow,
    utc_instant,
)
from tests.bronze_factory import bronze_frame

TRADE_DATE = date(2024, 1, 2)

roots = st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=6)
expirations = st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31))
rights = st.sampled_from(["C", "P"])
strikes = st.decimals(min_value=Decimal("0.5"), max_value=Decimal("5000"), places=2)


def test_sources_are_the_two_feeds() -> None:
    assert frozenset({"dolthub", "alpaca_indicative"}) == SOURCES


def test_bronze_schema_columns_in_order() -> None:
    assert BRONZE_SCHEMA.names == [
        "trade_date",
        "underlying",
        "occ_symbol",
        "expiration",
        "strike",
        "right",
        "bid",
        "ask",
        "last",
        "volume",
        "open_interest",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "underlying_price",
        "source",
        "ingested_at",
    ]


def test_bronze_schema_nullability() -> None:
    required = {field.name for field in BRONZE_SCHEMA if not field.nullable}
    assert required == {
        "trade_date",
        "underlying",
        "occ_symbol",
        "expiration",
        "strike",
        "right",
        "source",
        "ingested_at",
    }


@given(underlying=roots, expiration=expirations, right=rights, strike=strikes)
def test_occ_symbol_round_trips(
    underlying: str, expiration: date, right: str, strike: Decimal
) -> None:
    symbol = occ_symbol(underlying, expiration, right, strike)

    assert " " not in symbol
    assert len(symbol) == len(underlying) + 15
    assert parse_occ_symbol(symbol) == (underlying, expiration, right, strike)


def test_occ_symbol_known_vector() -> None:
    assert occ_symbol("SPY", date(2024, 1, 19), "C", Decimal("470")) == "SPY240119C00470000"


def test_parse_occ_symbol_known_vector() -> None:
    assert parse_occ_symbol("SPY240119C00470000") == ("SPY", date(2024, 1, 19), "C", Decimal("470"))


def test_parse_occ_symbol_accepts_space_padded_form() -> None:
    assert parse_occ_symbol("SPY   240119P00470500") == (
        "SPY",
        date(2024, 1, 19),
        "P",
        Decimal("470.5"),
    )


@pytest.mark.parametrize(
    "symbol",
    [
        "",
        "240119C00470000",
        "SPY240119X00470000",
        "SPY241319C00470000",
        "SPY240119C0047000",
        "SPY240119C004700000",
        "TOOLONG240119C00470000",
        "spy240119C00470000",
    ],
)
def test_parse_occ_symbol_rejects_malformed(symbol: str) -> None:
    with pytest.raises(ValueError):
        parse_occ_symbol(symbol)


@pytest.mark.parametrize(
    ("underlying", "right", "strike"),
    [
        ("SPY", "X", Decimal("470")),
        ("SPY", "C", Decimal("0")),
        ("SPY", "C", Decimal("-1")),
        ("SPY", "C", Decimal("0.0005")),
        ("SPY", "C", Decimal("100000")),
        ("", "C", Decimal("470")),
        ("TOOLONG", "C", Decimal("470")),
        ("spy", "C", Decimal("470")),
    ],
)
def test_occ_symbol_rejects_unrepresentable_terms(
    underlying: str, right: str, strike: Decimal
) -> None:
    with pytest.raises(ValueError):
        occ_symbol(underlying, date(2024, 1, 19), right, strike)


def test_empty_frame_validates() -> None:
    frame = empty_frame()

    assert len(frame) == 0
    assert list(frame.columns) == BRONZE_SCHEMA.names
    BRONZE_FRAME.validate(frame)


def test_empty_frame_dtypes_are_arrow_backed() -> None:
    frame = empty_frame()

    for field in BRONZE_SCHEMA:
        assert frame[field.name].dtype == pd.ArrowDtype(field.type), field.name


def test_to_arrow_schema_equals_bronze_schema() -> None:
    frame = bronze_frame(TRADE_DATE, rows_per_underlying=6)

    table = to_arrow(frame)

    assert table.schema.equals(BRONZE_SCHEMA)
    assert table.num_rows == 6


def test_to_arrow_of_empty_frame() -> None:
    table = to_arrow(empty_frame())

    assert table.schema.equals(BRONZE_SCHEMA)
    assert table.num_rows == 0


def test_to_arrow_drops_the_index() -> None:
    frame = bronze_frame(TRADE_DATE, rows_per_underlying=4)
    frame.index = pd.Index([10, 11, 12, 13])

    assert to_arrow(frame).schema.names == BRONZE_SCHEMA.names


def test_valid_frame_passes() -> None:
    frame = bronze_frame(TRADE_DATE, underlyings=("SPY", "QQQ"), rows_per_underlying=8)

    validated = BRONZE_FRAME.validate(frame)

    assert len(validated) == 16


def test_missing_bid_or_ask_is_not_a_crossed_quote() -> None:
    frame = bronze_frame(TRADE_DATE, rows_per_underlying=2)
    frame.loc[0, "bid"] = 50.0
    frame.loc[0, "ask"] = None
    frame.loc[1, "bid"] = None

    BRONZE_FRAME.validate(frame)


def _set(column: str, value: object) -> Callable[[pd.DataFrame], pd.DataFrame]:
    def mutate(frame: pd.DataFrame) -> pd.DataFrame:
        frame.loc[0, column] = cast(Any, value)
        return frame

    return mutate


def _crossed_quote(frame: pd.DataFrame) -> pd.DataFrame:
    frame.loc[0, "bid"] = 5.0
    frame.loc[0, "ask"] = 4.0
    return frame


def _duplicate_key(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([frame, frame.iloc[[0]]], ignore_index=True)


def _extra_column(frame: pd.DataFrame) -> pd.DataFrame:
    frame["note"] = "x"
    return frame


def _reordered(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[list(reversed(frame.columns))]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_set("right", "X"), id="right-not-C-or-P"),
        pytest.param(_set("strike", Decimal("0")), id="strike-zero"),
        pytest.param(_set("strike", Decimal("-5")), id="strike-negative"),
        pytest.param(_set("expiration", date(2023, 12, 29)), id="expired-before-trade-date"),
        pytest.param(_crossed_quote, id="bid-above-ask"),
        pytest.param(_duplicate_key, id="duplicate-key"),
        pytest.param(_set("source", "yahoo"), id="unknown-source"),
        pytest.param(_set("occ_symbol", None), id="null-occ-symbol"),
        pytest.param(_extra_column, id="extra-column"),
        pytest.param(_reordered, id="columns-out-of-order"),
    ],
)
def test_bronze_frame_rejects(mutate: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    frame = mutate(bronze_frame(TRADE_DATE, rows_per_underlying=4))

    # pandera raises SchemaErrors (plural) for column-structure errors even when not lazy.
    with pytest.raises((pandera.errors.SchemaError, pandera.errors.SchemaErrors)):
        BRONZE_FRAME.validate(frame)
    with pytest.raises(pandera.errors.SchemaErrors):
        BRONZE_FRAME.validate(frame, lazy=True)


def test_utc_instant_converts_to_utc() -> None:
    eastern = datetime(2024, 1, 2, 17, 0, tzinfo=timezone(timedelta(hours=-5)))

    assert utc_instant(eastern) == datetime(2024, 1, 2, 22, 0, tzinfo=UTC)
    assert utc_instant(eastern).tzinfo is UTC


def test_utc_instant_rejects_naive() -> None:
    with pytest.raises(ValueError):
        utc_instant(datetime(2024, 1, 2, 22, 0))


def test_split_crossed_quotes_keeps_locked_and_one_sided_quotes() -> None:
    def record(bid: float | None, ask: float | None) -> dict[str, Any]:
        return {"underlying": "SPY", "trade_date": TRADE_DATE, "bid": bid, "ask": ask}

    records = [record(2.0, 1.0), record(1.0, 1.0), record(None, 1.0), record(3.0, None)]

    kept, dropped = split_crossed_quotes(records)

    assert kept == records[1:]
    assert dropped == {("SPY", TRADE_DATE): 1}


def test_frame_from_records_fills_missing_columns_with_nulls() -> None:
    frame = frame_from_records(
        [
            {
                "trade_date": TRADE_DATE,
                "underlying": "SPY",
                "occ_symbol": "SPY240119C00470000",
                "expiration": date(2024, 1, 19),
                "strike": Decimal("470"),
                "right": "C",
                "source": "dolthub",
                "ingested_at": datetime(2024, 1, 2, 22, 0, tzinfo=UTC),
            }
        ]
    )

    assert list(frame.columns) == BRONZE_SCHEMA.names
    assert frame["bid"].isna().all()
    BRONZE_FRAME.validate(frame)


def test_frame_from_no_records_is_the_empty_frame() -> None:
    assert frame_from_records([]).equals(empty_frame())
