"""The bronze tables as data: one ``TableSpec`` per Iceberg table.

A spec bundles everything the generic writer needs to know about a table: its name, Arrow
schema, pandera schema, natural key and the sources allowed to write to it. Writers, readers
and the merge helper take the spec (or detect it from the table's name with ``spec_for``)
instead of importing one table's constants, so a new bronze table is one more spec here.

Every bronze table is partitioned the same way, ``day(trade_date)`` then ``identity(source)``,
which is why a spec must have a non-null ``trade_date`` date and a non-null ``source``
string, and why one slice is always a ``(trade_date, source)`` pair.

Everything in this module is pure: no I/O, no clocks.
"""

from dataclasses import dataclass

import pandas as pd
import pandera.pandas as pa_schema
import pyarrow as pa
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import DayTransform, IdentityTransform
from pyiceberg.types import (
    DateType,
    DecimalType,
    DoubleType,
    IcebergType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

from oap.ingest.price_schema import (
    PRICE_FRAME,
    PRICE_KEY_COLUMNS,
    PRICE_SCHEMA,
    PRICE_SOURCES,
)
from oap.ingest.schema import BRONZE_FRAME, BRONZE_SCHEMA, KEY_COLUMNS, SOURCES, empty_frame

_ICEBERG_TYPES: dict[pa.DataType, IcebergType] = {
    pa.date32(): DateType(),
    pa.string(): StringType(),
    pa.decimal128(10, 3): DecimalType(10, 3),
    pa.float64(): DoubleType(),
    pa.int64(): LongType(),
    pa.timestamp("us", tz="UTC"): TimestamptzType(),
}


@dataclass(frozen=True)
class TableSpec:
    """Everything the generic bronze writer needs to know about one table.

    Attributes:
        name: Table name inside the namespace, for example ``"option_chain"``.
        arrow_schema: Arrow schema of the stored rows, in column order.
        frame_schema: pandera contract a frame must meet before it is written.
        key_columns: Columns of the natural key; ``trade_date`` and ``source`` are among them.
        sources: Values ``source`` may take in this table.
    """

    name: str
    arrow_schema: pa.Schema
    frame_schema: pa_schema.DataFrameSchema
    key_columns: tuple[str, ...]
    sources: frozenset[str]

    def __post_init__(self) -> None:
        """Check that the table can be partitioned by day and source.

        Raises:
            ValueError: If ``trade_date`` is not a non-null ``date32`` column, ``source`` is
                not a non-null string column, or ``key_columns`` names an unknown column or
                leaves out ``trade_date`` or ``source``.
        """
        names = self.arrow_schema.names
        for column, kind in (("trade_date", pa.date32()), ("source", pa.string())):
            if column not in names:
                raise ValueError(f"table {self.name!r} has no {column!r} column")
            field = self.arrow_schema.field(column)
            if field.type != kind or field.nullable:
                raise ValueError(f"table {self.name!r}: {column} must be a non-null {kind}")
        unknown = [column for column in self.key_columns if column not in names]
        if unknown:
            raise ValueError(f"table {self.name!r}: key columns {unknown} are not in the schema")
        if not {"trade_date", "source"} <= set(self.key_columns):
            raise ValueError(f"table {self.name!r}: the key must include trade_date and source")

    def field_id(self, column: str) -> int:
        """Return the Iceberg field id of a column: its 1-based position in the schema.

        Args:
            column: Column name.

        Returns:
            The field id, 1 for the first column.

        Raises:
            ValueError: If the table has no such column.
        """
        names = self.arrow_schema.names
        if column not in names:
            raise ValueError(f"table {self.name!r} has no column {column!r}")
        return names.index(column) + 1

    def iceberg_schema(self) -> Schema:
        """Return the table's Iceberg schema, field ids 1..n in column order.

        Returns:
            The schema: dates as ``date``, prices as ``double``, counts as ``long``,
            decimals as the matching ``decimal`` and ``ingested_at`` as ``timestamptz``;
            non-nullable Arrow fields are required.
        """
        return Schema(
            *(
                NestedField(
                    field_id=self.field_id(field.name),
                    name=field.name,
                    field_type=_ICEBERG_TYPES[field.type],
                    required=not field.nullable,
                )
                for field in self.arrow_schema
            )
        )

    def partition_spec(self) -> PartitionSpec:
        """Return the partition spec: ``day(trade_date)`` then ``identity(source)``.

        Returns:
            The spec, fields named ``trade_date_day`` (id 1000) and ``source`` (id 1001),
            bound to this table's field ids.
        """
        return PartitionSpec(
            PartitionField(
                source_id=self.field_id("trade_date"),
                field_id=1000,
                transform=DayTransform(),
                name="trade_date_day",
            ),
            PartitionField(
                source_id=self.field_id("source"),
                field_id=1001,
                transform=IdentityTransform(),
                name="source",
            ),
        )

    def empty_frame(self) -> pd.DataFrame:
        """Return a frame with this table's columns and no rows.

        Returns:
            A frame that passes ``frame_schema``.
        """
        return empty_frame(self.arrow_schema)


OPTION_CHAIN = TableSpec("option_chain", BRONZE_SCHEMA, BRONZE_FRAME, KEY_COLUMNS, SOURCES)
"""``bronze.option_chain``: one row per option contract per trade date per source."""

UNDERLYING_PRICE = TableSpec(
    "underlying_price", PRICE_SCHEMA, PRICE_FRAME, PRICE_KEY_COLUMNS, PRICE_SOURCES
)
"""``bronze.underlying_price``: one daily as-traded OHLCV bar per underlying per source."""

BRONZE_TABLES: tuple[TableSpec, ...] = (OPTION_CHAIN, UNDERLYING_PRICE)
"""Every bronze table, in creation order."""


def spec_for(name: str) -> TableSpec:
    """Return the spec of a bronze table from its name or a dotted identifier.

    Args:
        name: A table name such as ``"underlying_price"``, or an identifier whose last
            dot-separated part is one, such as ``"oap_bronze.underlying_price"``.

    Returns:
        The matching spec.

    Raises:
        ValueError: If no bronze table has that name; the message lists the known names.
    """
    table = name.rsplit(".", 1)[-1]
    for spec in BRONZE_TABLES:
        if spec.name == table:
            return spec
    known = ", ".join(spec.name for spec in BRONZE_TABLES)
    raise ValueError(f"no bronze table named {table!r}; known tables: {known}")
