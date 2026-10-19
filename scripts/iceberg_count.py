"""Print bronze row counts per slice and per underlying, optionally with content hashes.

Run it inside the Airflow scheduler container with ``make iceberg-count``. The table metadata
stores the container's absolute file paths (``/opt/airflow/.iceberg-local/...``), so the
local catalog written by the stack cannot be read from the host. The catalog comes from the
``OAP_ICEBERG_*`` environment like every ingest task.

The default run streams three columns (``trade_date``, ``source``, ``underlying``) in Arrow
record batches and never builds a DataFrame of the table, so memory stays flat however many
rows the table holds. ``--hash`` additionally reads each slice on its own, one at a time, and
prints ``content_hash`` per slice plus ``content_digest``, a SHA-256 over the sorted
``(source, trade_date, hash)`` lines. Comparing the digest before and after re-running a load
shows whether the load is idempotent. ``content_digest`` is not comparable with the
``content_hash`` line this script printed before, which hashed one whole frame.
``--start``/``--end``/``--source`` narrow the selection (default: the whole table) and
``--summary`` skips the per-slice lines.
"""

import argparse
import hashlib
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from typing import cast

import pyarrow as pa
from pyiceberg.expressions import (
    AlwaysTrue,
    And,
    BooleanExpression,
    EqualTo,
    GreaterThanOrEqual,
    LessThanOrEqual,
    Reference,
)
from pyiceberg.expressions.literals import literal

from oap.ingest.iceberg_writer import (
    catalog_from_env,
    content_hash,
    read_partition,
    table_identifier,
)
from oap.ingest.schema import SOURCES

type SliceCounts = Counter[tuple[str, date, str]]


def row_filter(start: date | None, end: date | None, source: str | None) -> BooleanExpression:
    """Build the scan filter from the optional bounds and source.

    Args:
        start: First trade date, inclusive; None for no lower bound.
        end: Last trade date, inclusive; None for no upper bound.
        source: Feed to keep; None for all feeds.

    Returns:
        The conjunction of the given conditions, ``AlwaysTrue`` when none is given.
    """
    result: BooleanExpression = AlwaysTrue()
    conditions: list[BooleanExpression] = []
    if start is not None:
        conditions.append(
            GreaterThanOrEqual(term=Reference("trade_date"), value=literal(start.isoformat()))
        )
    if end is not None:
        conditions.append(
            LessThanOrEqual(term=Reference("trade_date"), value=literal(end.isoformat()))
        )
    if source is not None:
        conditions.append(EqualTo(term=Reference("source"), value=literal(source)))
    for condition in conditions:
        result = condition if isinstance(result, AlwaysTrue) else And(result, condition)
    return result


def count_rows(batches: Iterable[pa.RecordBatch]) -> SliceCounts:
    """Count rows per ``(source, trade_date, underlying)`` over a stream of record batches.

    Args:
        batches: Batches with ``source``, ``trade_date`` and ``underlying`` columns.

    Returns:
        The accumulated counts; only one batch is held at a time.
    """
    counts: SliceCounts = Counter()
    for batch in batches:
        counts.update(
            zip(
                cast(list[str], batch.column("source").to_pylist()),
                cast(list[date], batch.column("trade_date").to_pylist()),
                cast(list[str], batch.column("underlying").to_pylist()),
                strict=True,
            )
        )
    return counts


def slice_totals(counts: SliceCounts) -> dict[tuple[str, date], int]:
    """Sum the per-underlying counts into rows per ``(source, trade_date)`` slice."""
    totals: Counter[tuple[str, date]] = Counter()
    for (source, day, _underlying), rows in counts.items():
        totals[(source, day)] += rows
    return dict(totals)


def underlying_summary(counts: SliceCounts) -> list[tuple[str, str, int, int, date, date]]:
    """Summarise each ``(source, underlying)``: days, rows, first day and last day.

    Args:
        counts: Output of ``count_rows``.

    Returns:
        ``(source, underlying, days, rows, first, last)`` tuples sorted by source, underlying.
    """
    rows: Counter[tuple[str, str]] = Counter()
    days: dict[tuple[str, str], set[date]] = {}
    for (source, day, underlying), n in counts.items():
        rows[(source, underlying)] += n
        days.setdefault((source, underlying), set()).add(day)
    return [
        (source, underlying, len(seen), rows[(source, underlying)], min(seen), max(seen))
        for (source, underlying), seen in sorted(days.items())
    ]


def combined_digest(hashes: Mapping[tuple[str, date], str]) -> str:
    """Combine per-slice content hashes into one digest, independent of insertion order.

    Args:
        hashes: ``content_hash`` of every ``(source, trade_date)`` slice.

    Returns:
        Lower-case hexadecimal SHA-256 over the sorted ``source<TAB>date<TAB>hash`` lines.
    """
    digest = hashlib.sha256()
    for (source, day), value in sorted(hashes.items()):
        digest.update(f"{source}\t{day.isoformat()}\t{value}\n".encode())
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Print the counts (and hashes with ``--hash``); return the process exit code.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        0 on success, 1 when the table does not exist yet.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, help="first trade date (inclusive)")
    parser.add_argument("--end", type=date.fromisoformat, help="last trade date (inclusive)")
    parser.add_argument("--source", choices=sorted(SOURCES), help="only this source")
    parser.add_argument("--summary", action="store_true", help="omit the per-slice lines")
    parser.add_argument(
        "--hash", action="store_true", help="add a content hash per slice and a combined digest"
    )
    args = parser.parse_args(argv)

    catalog = catalog_from_env()
    identifier = table_identifier()
    if not catalog.table_exists(identifier):
        print(f"table {'.'.join(identifier)} does not exist yet", file=sys.stderr)
        return 1
    table = catalog.load_table(identifier)

    scan = table.scan(
        row_filter=row_filter(args.start, args.end, args.source),
        selected_fields=("trade_date", "source", "underlying"),
    )
    counts = count_rows(scan.to_arrow_batch_reader())
    totals = slice_totals(counts)

    hashes: dict[tuple[str, date], str] = {}
    if args.hash:
        for source, day in sorted(totals):
            hashes[(source, day)] = content_hash(
                read_partition(table, trade_date=day, source=source)
            )

    if not args.summary:
        for (source, day), rows in sorted(totals.items()):
            suffix = f"\t{hashes[(source, day)]}" if args.hash else ""
            print(f"{source}\t{day}\t{rows}{suffix}")
    for source, underlying, n_days, n_rows, first, last in underlying_summary(counts):
        print(f"underlying\t{source}\t{underlying}\t{n_days} days\t{n_rows} rows\t{first}..{last}")
    if totals:
        first_day = min(day for _, day in totals)
        last_day = max(day for _, day in totals)
        print(
            f"total {sum(totals.values())} rows in {len(totals)} slices, {first_day} to {last_day}"
        )
    else:
        print("total 0 rows")
    if args.hash:
        print(f"content_digest {combined_digest(hashes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
