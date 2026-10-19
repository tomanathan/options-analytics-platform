"""Merge freshly fetched rows into a bronze table's daily slices without losing other rows.

A bronze slice (one ``trade_date`` from one ``source``) holds every underlying of that day,
and ``write_partition`` replaces a whole slice. Writing one underlying's rows on their own
would therefore delete the others' (ADR 0003). ``merge_into_slices`` reads each affected
slice, swaps in the fetched rows for the underlyings they cover, keeps everything else and
overwrites the slice once.

Absence is not deletion: only underlyings present in ``fetched`` on a day are replaced. An
underlying the vendor returned nothing for (a month without data, a partial or empty
response) keeps the rows already loaded, and days with no fetched rows are not touched. A
slice whose content would not change is not written, so a re-run adds no snapshots.

``merge_day`` is pure; ``merge_into_slices`` reads and writes the table.
"""

import logging

import pandas as pd
from pyiceberg.table import Table

from oap.ingest.iceberg_writer import _resolve, content_hash, read_partition, write_partition
from oap.ingest.tables import TableSpec

logger = logging.getLogger(__name__)


def merge_day(existing: pd.DataFrame, fetched_day: pd.DataFrame) -> pd.DataFrame:
    """Combine one day's existing slice with the rows fetched for that day. Pure.

    The underlyings to replace are the ones present in ``fetched_day``; rows of every other
    underlying in ``existing`` are kept as they are.

    Args:
        existing: The slice as it is in the table (may be empty).
        fetched_day: Fetched rows for this day (may be empty, which keeps ``existing``).

    Returns:
        The new content of the slice.
    """
    replaced = list(fetched_day["underlying"].unique())
    parts = [existing[~existing["underlying"].isin(replaced)], fetched_day]
    parts = [part for part in parts if not part.empty]
    return pd.concat(parts, ignore_index=True) if parts else existing.iloc[0:0]


def merge_into_slices(
    table: Table,
    fetched: pd.DataFrame | None,
    *,
    source: str,
    spec: TableSpec | None = None,
) -> dict[str, int]:
    """Write fetched rows into their daily slices of ``source``, replacing only what was fetched.

    For every date present in ``fetched`` the slice is read, the rows of each underlying that
    has fetched rows on that date are replaced by them, every other row is kept, and the slice
    is overwritten with one ``write_partition`` call. Absence is not deletion: an underlying
    with no fetched rows for a date keeps whatever the slice already holds for it, and dates
    with no fetched rows are not touched at all. A slice whose content would not change is
    not written.

    Args:
        table: A bronze table.
        fetched: Fetched rows of any underlyings and dates, all from ``source``, or None when
            nothing was fetched.
        source: Feed of the slices to merge into.
        spec: The table's spec, detected from its name when omitted.

    Returns:
        ``{"days": slices written, "unchanged": slices skipped, "rows": rows written}``.

    Raises:
        ValueError: If ``spec`` is not the table's, or ``source`` is not one of its sources.
    """
    spec = _resolve(table, spec)
    counts = {"days": 0, "unchanged": 0, "rows": 0}
    if fetched is None or fetched.empty:
        return counts
    fetched_days = pd.to_datetime(fetched["trade_date"].astype(str)).dt.date
    for day in sorted(set(fetched_days)):
        existing = read_partition(table, trade_date=day, source=source, spec=spec)
        merged = merge_day(existing, fetched[(fetched_days == day).to_numpy()])
        if content_hash(merged, spec=spec) == content_hash(existing, spec=spec):
            counts["unchanged"] += 1
            continue
        counts["rows"] += write_partition(table, merged, trade_date=day, source=source, spec=spec)
        counts["days"] += 1
    return counts
