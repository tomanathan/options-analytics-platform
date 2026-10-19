from typing import Any

import pyarrow as pa
import pytest

from oap.ingest.iceberg_writer import bronze_iceberg_schema, bronze_partition_spec
from oap.ingest.price_schema import PRICE_FRAME, PRICE_KEY_COLUMNS, PRICE_SCHEMA
from oap.ingest.schema import BRONZE_FRAME
from oap.ingest.tables import (
    BRONZE_TABLES,
    OPTION_CHAIN,
    UNDERLYING_PRICE,
    TableSpec,
    spec_for,
)


def test_option_chain_spec_matches_the_legacy_schema() -> None:
    schema = OPTION_CHAIN.iceberg_schema()

    assert schema == bronze_iceberg_schema()
    assert [field.field_id for field in schema.fields] == list(range(1, 21))


def test_underlying_price_iceberg_schema() -> None:
    schema = UNDERLYING_PRICE.iceberg_schema()

    assert [field.name for field in schema.fields] == [
        "trade_date",
        "underlying",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "ingested_at",
    ]
    assert [field.field_id for field in schema.fields] == list(range(1, 10))
    assert {field.name for field in schema.fields if field.required} == {
        "trade_date",
        "underlying",
        "close",
        "source",
        "ingested_at",
    }


@pytest.mark.parametrize("spec", BRONZE_TABLES, ids=lambda spec: spec.name)
def test_partition_spec_binds_trade_date_and_source(spec: TableSpec) -> None:
    partition = spec.partition_spec()
    schema = spec.iceberg_schema()

    day, source = partition.fields
    assert (day.name, day.field_id, str(day.transform)) == ("trade_date_day", 1000, "day")
    assert (source.name, source.field_id, str(source.transform)) == ("source", 1001, "identity")
    assert schema.find_field(day.source_id).name == "trade_date"
    assert schema.find_field(source.source_id).name == "source"


def test_option_chain_partition_spec_matches_the_legacy_function() -> None:
    assert OPTION_CHAIN.partition_spec() == bronze_partition_spec()


def test_spec_for_known_and_unknown_names() -> None:
    assert spec_for("option_chain") is OPTION_CHAIN
    assert spec_for("underlying_price") is UNDERLYING_PRICE
    assert spec_for("oap_bronze.underlying_price") is UNDERLYING_PRICE
    with pytest.raises(ValueError, match="option_chain, underlying_price"):
        spec_for("quotes")


def test_specs_carry_their_own_contracts() -> None:
    assert OPTION_CHAIN.frame_schema is BRONZE_FRAME
    assert UNDERLYING_PRICE.frame_schema is PRICE_FRAME
    assert UNDERLYING_PRICE.arrow_schema is PRICE_SCHEMA
    assert UNDERLYING_PRICE.key_columns == PRICE_KEY_COLUMNS


def test_table_spec_rejects_a_schema_without_source() -> None:
    schema = pa.schema([pa.field("trade_date", pa.date32(), nullable=False)])

    with pytest.raises(ValueError, match="source"):
        TableSpec("bad", schema, PRICE_FRAME, ("trade_date",), frozenset({"x"}))


def test_table_spec_rejects_a_nullable_trade_date() -> None:
    fields: list[pa.Field[Any]] = [
        pa.field("trade_date", pa.date32(), nullable=True),
        pa.field("source", pa.string(), nullable=False),
    ]
    schema = pa.schema(fields)

    with pytest.raises(ValueError, match="trade_date"):
        TableSpec("bad", schema, PRICE_FRAME, ("trade_date", "source"), frozenset({"x"}))


def test_table_spec_rejects_a_key_without_trade_date_and_source() -> None:
    with pytest.raises(ValueError, match="key"):
        TableSpec("bad", PRICE_SCHEMA, PRICE_FRAME, ("underlying",), frozenset({"dolthub_stocks"}))
    with pytest.raises(ValueError, match="not in the schema"):
        TableSpec(
            "bad",
            PRICE_SCHEMA,
            PRICE_FRAME,
            ("trade_date", "source", "nope"),
            frozenset({"dolthub_stocks"}),
        )


def test_field_id_rejects_an_unknown_column() -> None:
    with pytest.raises(ValueError, match="nope"):
        UNDERLYING_PRICE.field_id("nope")


def test_empty_frame_validates_against_its_own_contract() -> None:
    for spec in BRONZE_TABLES:
        frame = spec.empty_frame()
        assert list(frame.columns) == spec.arrow_schema.names
        spec.frame_schema.validate(frame, lazy=True)
