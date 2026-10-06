"""Print row counts per (source, trade_date) of the bronze table, and its content hash.

Run inside the Airflow scheduler container with ``make iceberg-count`` (or on the host with
``uv run python scripts/iceberg_count.py``); the catalog comes from the ``OAP_ICEBERG_*``
environment like every ingest task. The hash is ``content_hash`` over the selected rows, so
comparing it before and after re-running a load shows whether the load is idempotent.
``--start``/``--end``/``--source`` narrow the selection; the default is the whole table.
"""

import argparse
import sys
from datetime import date
from typing import cast

from oap.ingest.iceberg_writer import (
    catalog_from_env,
    content_hash,
    read_range,
    table_identifier,
)


def main(argv: list[str] | None = None) -> int:
    """Print the counts and hash; return the process exit code.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        0 on success, 1 when the table does not exist yet.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, help="first trade date (inclusive)")
    parser.add_argument("--end", type=date.fromisoformat, help="last trade date (inclusive)")
    parser.add_argument("--source", help="only this source, e.g. dolthub")
    args = parser.parse_args(argv)

    catalog = catalog_from_env()
    identifier = table_identifier()
    if not catalog.table_exists(identifier):
        print(f"table {'.'.join(identifier)} does not exist yet", file=sys.stderr)
        return 1
    table = catalog.load_table(identifier)

    days: list[date] = [
        day
        for day in table.scan(selected_fields=("trade_date",)).to_arrow()["trade_date"].to_pylist()
        if day is not None
    ]
    if not days:
        print("total 0 rows")
        return 0
    start: date = args.start or min(days)
    end: date = args.end or max(days)
    frame = read_range(table, start=start, end=end, source=args.source)

    counts = frame.groupby(["source", "trade_date"], observed=True).size().sort_index()
    for key, rows in counts.items():
        source, trade_date = cast(tuple[str, date], key)
        print(f"{source}\t{trade_date}\t{rows}")
    print(f"total {len(frame)} rows in {len(counts)} slices, {start} to {end}")
    print(f"content_hash {content_hash(frame)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
