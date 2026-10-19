"""Write a small synthetic Iceberg bronze catalog for the dbt build and its tests.

The catalog is written through the same ``ensure_table`` and ``write_partition`` that Airflow
uses, so ``make dbt-build`` exercises the exact catalog resolution and ``iceberg_scan`` path of
a real run without any vendor data. Usage: ``make_synthetic_bronze.py [--out DIR]``, or
``make_synthetic_bronze.py [--out DIR] --rewrite-slice YYYY-MM-DD [--prices-only]`` to rewrite one
session's chain and price slices (or only the price slice) in the existing catalog, as a vendor
correction landing after a build would.

The data is deterministic. Three underlyings (SPY, AAPL, TSLA) trade 13 NYSE sessions from
2024-01-02 to 2024-01-19. Each session lists five strikes around a reference price, both
rights, for every expiration not yet passed. The expirations include 2024-01-15, the Martin
Luther King holiday, so the last session before an expiration is exercised. DoltHub covers
every session but the last; the Alpaca snapshot covers the last two, so 2024-01-18 has two
sources and the dedup rule has work to do. TSLA has no price on 2024-01-19, which exercises
the chain-price fallback and an expiration that cannot settle.

The expected row counts, asserted by ``dbt/tests/assert_synthetic_row_counts.sql``, are 1380
chain rows (1260 DoltHub, 120 Alpaca) and 38 price rows.

Units: prices and strikes in dollars, volatility as a decimal (0.20 is 20%), time in calendar
days (``dte``) or years.
"""

import argparse
import shutil
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.compute as pc
from pyiceberg.table import Table

from oap.calendar import trading_days
from oap.ingest.iceberg_writer import ensure_table, read_partition, write_partition
from oap.ingest.local_catalog import LocalCatalog
from oap.ingest.price_schema import PRICE_SCHEMA
from oap.ingest.schema import frame_from_records, occ_symbol
from oap.ingest.tables import OPTION_CHAIN, UNDERLYING_PRICE

UNDERLYINGS: dict[str, int] = {"SPY": 470, "AAPL": 185, "TSLA": 240}
"""Underlying to its reference close in dollars."""

STRIKE_OFFSETS: tuple[int, ...] = (-20, -10, 0, 10, 20)
"""Strikes listed around the reference close, in dollars. The same strikes every day."""

EXPIRATIONS: tuple[date, ...] = (
    date(2024, 1, 12),
    date(2024, 1, 15),  # Martin Luther King Day: settles on the last session before it.
    date(2024, 1, 19),
    date(2024, 2, 16),
)
"""Expiration dates of the listed contracts."""

SESSIONS: tuple[date, ...] = tuple(trading_days(date(2024, 1, 2), date(2024, 1, 19)))
"""The 13 NYSE sessions of the synthetic history."""

DOLTHUB_SESSIONS: tuple[date, ...] = SESSIONS[:-1]
"""Sessions the DoltHub chain covers: all but the last."""

ALPACA_SESSIONS: tuple[date, ...] = SESSIONS[-2:]
"""Sessions the Alpaca snapshot covers; the first of them overlaps DoltHub."""

PRICE_GAPS: frozenset[tuple[str, date]] = frozenset({("TSLA", date(2024, 1, 19))})
"""(underlying, session) pairs with no price row."""

INGESTED_AT = datetime(2024, 1, 20, tzinfo=UTC)
"""UTC instant every synthetic slice claims to have been written."""

PRICE_SOURCE = "dolthub_stocks"

DEFAULT_OUT = ".dbt-local/synthetic-iceberg"

_RECORD = dict[str, Any]


def close(underlying: str, session: date) -> float:
    """Return the underlying's close on a session.

    Args:
        underlying: A key of ``UNDERLYINGS``.
        session: One of ``SESSIONS``.

    Returns:
        Close in dollars: the reference price drifting up 0.2% per session, to cents.
    """
    return round(UNDERLYINGS[underlying] * (1 + 0.002 * SESSIONS.index(session)), 2)


def _contract_record(
    session: date, underlying: str, expiration: date, strike: int, right: str, source: str
) -> _RECORD:
    """Return one bronze row for a contract on a session.

    The mid is intrinsic value plus 0.50 plus 0.02 per calendar day to expiration, in dollars;
    the quote is 0.05 either side. Alpaca rows carry a last price, volume and the underlying
    price; DoltHub rows carry open interest instead, as the vendors do.
    """
    spot = close(underlying, session)
    intrinsic = max(spot - strike, 0.0) if right == "C" else max(strike - spot, 0.0)
    dte_days = (expiration - session).days
    mid = round(intrinsic + 0.5 + 0.02 * dte_days, 2)
    alpaca = source == "alpaca_indicative"
    return {
        "trade_date": session,
        "underlying": underlying,
        "occ_symbol": occ_symbol(underlying, expiration, right, Decimal(strike)),
        "expiration": expiration,
        "strike": Decimal(strike),
        "right": right,
        "bid": round(mid - 0.05, 2),
        "ask": round(mid + 0.05, 2),
        "last": mid if alpaca else None,
        "volume": 100 if alpaca else None,
        "open_interest": None if alpaca else 1000,
        "iv": 0.2,
        "delta": 0.5 if right == "C" else -0.5,
        "gamma": 0.01,
        "theta": -0.05,
        "vega": 0.1,
        "rho": 0.01,
        "underlying_price": spot if alpaca else None,
        "source": source,
        "ingested_at": INGESTED_AT,
    }


def chain_records(session: date, source: str) -> list[_RECORD]:
    """Return the chain rows of one session and source.

    Args:
        session: One of ``SESSIONS``.
        source: ``"dolthub"`` or ``"alpaca_indicative"``.

    Returns:
        One row per underlying, expiration not before the session, strike offset and right.
    """
    return [
        _contract_record(session, underlying, expiration, ref + offset, right, source)
        for underlying, ref in UNDERLYINGS.items()
        for expiration in EXPIRATIONS
        if expiration >= session
        for offset in STRIKE_OFFSETS
        for right in ("C", "P")
    ]


def price_rows() -> list[_RECORD]:
    """Return every daily price row: one per session and underlying, except ``PRICE_GAPS``.

    Returns:
        Rows with open equal to the close, high and low one dollar either side, and 1000 shares.
    """
    rows: list[_RECORD] = []
    for session in SESSIONS:
        for underlying in UNDERLYINGS:
            if (underlying, session) in PRICE_GAPS:
                continue
            price = close(underlying, session)
            rows.append(
                {
                    "trade_date": session,
                    "underlying": underlying,
                    "open": price,
                    "high": round(price + 1, 2),
                    "low": round(price - 1, 2),
                    "close": price,
                    "volume": 1000,
                    "source": PRICE_SOURCE,
                    "ingested_at": INGESTED_AT,
                }
            )
    return rows


def write_catalog(out: Path) -> dict[str, int]:
    """Write the synthetic catalog and tables to ``out``, replacing a previous synthetic catalog.

    Args:
        out: Directory that will hold ``catalog.db`` and ``warehouse/``.

    Returns:
        Rows written per table: ``{"option_chain": ..., "underlying_price": ...}``.

    Raises:
        ValueError: If ``out`` is a non-empty directory without a ``catalog.db``, which is not
            a previous synthetic catalog and must not be deleted.
    """
    if out.exists():
        if any(out.iterdir()) and not (out / "catalog.db").exists():
            raise ValueError(f"{out} is not empty and holds no catalog.db; refusing to replace it")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    root = out.absolute()
    catalog = LocalCatalog(
        "oap", uri=f"sqlite:///{root}/catalog.db", warehouse=(root / "warehouse").as_uri()
    )
    chain = ensure_table(catalog, ("bronze", "option_chain"), spec=OPTION_CHAIN)
    chain_rows = 0
    for source, sessions in (("dolthub", DOLTHUB_SESSIONS), ("alpaca_indicative", ALPACA_SESSIONS)):
        for session in sessions:
            frame = frame_from_records(chain_records(session, source))
            chain_rows += write_partition(
                chain, frame, trade_date=session, source=source, spec=OPTION_CHAIN
            )
    prices = ensure_table(catalog, ("bronze", "underlying_price"), spec=UNDERLYING_PRICE)
    by_session: dict[date, list[_RECORD]] = {}
    for row in price_rows():
        by_session.setdefault(row["trade_date"], []).append(row)
    price_count = 0
    for session, rows in by_session.items():
        frame = frame_from_records(rows, PRICE_SCHEMA)
        price_count += write_partition(
            prices, frame, trade_date=session, source=PRICE_SOURCE, spec=UNDERLYING_PRICE
        )
    return {"option_chain": chain_rows, "underlying_price": price_count}


def _open_catalog(out: Path) -> LocalCatalog:
    """Return the catalog of a synthetic catalog directory written by ``write_catalog``."""
    root = out.absolute()
    if not (root / "catalog.db").exists():
        raise ValueError(f"{out} holds no catalog.db; write the synthetic catalog first")
    return LocalCatalog(
        "oap", uri=f"sqlite:///{root}/catalog.db", warehouse=(root / "warehouse").as_uri()
    )


def _newest_stamp(*tables: Table) -> datetime:
    """Return the newest ``ingested_at`` over every row of the given tables."""
    stamps: list[datetime] = [
        pc.max(table.scan(selected_fields=("ingested_at",)).to_arrow()["ingested_at"]).as_py()
        for table in tables
    ]
    return max(stamps)


def _raise_first(frame: pd.DataFrame, column: str, amount: float) -> None:
    """Raise the first row's value of a float column by ``amount`` dollars, in place, to cents."""
    values = frame[column].astype("float64")
    values.iloc[0] = round(values.iloc[0] + amount, 2)
    frame[column] = values.astype(frame[column].dtype)


def _restamp(frame: pd.DataFrame, stamp: datetime) -> pd.DataFrame:
    """Return ``frame`` with every ``ingested_at`` set to ``stamp``."""
    restamped = frame.copy()
    restamped["ingested_at"] = pd.Series(
        [stamp] * len(restamped), index=restamped.index, dtype=frame["ingested_at"].dtype
    )
    return restamped


def rewrite_slice(out: Path, session: date, *, prices_only: bool = False) -> dict[str, int]:
    """Rewrite one session's chain and price slices in an existing synthetic catalog.

    This is what a vendor correction looks like to bronze: the same slice, written again with
    changed values and a later ``ingested_at``. It goes through the real writer
    (``write_partition``), so the Iceberg snapshot and ``iceberg_scan`` path are the
    production ones. A dbt build after it must bring the incremental gold fact up to date;
    ``assert_fct_option_quote_matches_silver`` fails the build if it does not.

    For every chain source that covers ``session`` (``dolthub`` and, for the last two sessions,
    ``alpaca_indicative``) the first contract by OCC symbol gets its bid and ask raised by 0.01
    dollars (the quote stays uncrossed). The price slice gets the close of its first underlying
    raised by 0.50 dollars, which keeps it inside that day's high and low and inside the strike
    range. Every rewritten row is stamped one hour after the newest row in either table.

    With ``prices_only`` the chain is left alone: that is a price that arrives or is corrected
    after the chain of its date was loaded, which only the price table's ``ingested_at`` can
    reveal to the incremental watermark.

    Args:
        out: Directory of a catalog written by ``write_catalog``.
        session: One of ``SESSIONS``.
        prices_only: Rewrite only the price slice.

    Returns:
        Rows rewritten per table: ``{"option_chain": ..., "underlying_price": ...}``.

    Raises:
        ValueError: If ``session`` is not a synthetic session, ``out`` holds no catalog, or a
            slice to rewrite is empty.
    """
    if session not in SESSIONS:
        raise ValueError(f"{session} is not one of the synthetic sessions")
    catalog = _open_catalog(out)
    chain = ensure_table(catalog, ("bronze", "option_chain"), spec=OPTION_CHAIN)
    prices = ensure_table(catalog, ("bronze", "underlying_price"), spec=UNDERLYING_PRICE)
    stamp = _newest_stamp(chain, prices) + timedelta(hours=1)
    chain_rows = 0
    for source, sessions in (("dolthub", DOLTHUB_SESSIONS), ("alpaca_indicative", ALPACA_SESSIONS)):
        if prices_only or session not in sessions:
            continue
        frame = read_partition(chain, trade_date=session, source=source, spec=OPTION_CHAIN)
        frame = frame.sort_values("occ_symbol", ignore_index=True)
        if frame.empty:
            raise ValueError(f"the ({session}, {source}) chain slice is empty")
        for column in ("bid", "ask"):
            _raise_first(frame, column, 0.01)
        chain_rows += write_partition(
            chain,
            _restamp(frame, stamp),
            trade_date=session,
            source=source,
            spec=OPTION_CHAIN,
        )
    day = read_partition(prices, trade_date=session, source=PRICE_SOURCE, spec=UNDERLYING_PRICE)
    day = day.sort_values("underlying", ignore_index=True)
    if day.empty:
        raise ValueError(f"the ({session}, {PRICE_SOURCE}) price slice is empty")
    _raise_first(day, "close", 0.5)
    price_rows = write_partition(
        prices,
        _restamp(day, stamp),
        trade_date=session,
        source=PRICE_SOURCE,
        spec=UNDERLYING_PRICE,
    )
    return {"option_chain": chain_rows, "underlying_price": price_rows}


def main(argv: Sequence[str] | None = None) -> int:
    """Write the synthetic catalog, or rewrite one of its slices, and print the row counts.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        Process exit code, 0 on success.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT), help="catalog directory")
    parser.add_argument(
        "--rewrite-slice",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="rewrite that session's chain and price slices in the existing catalog instead of "
        "writing a new one",
    )
    parser.add_argument(
        "--prices-only",
        action="store_true",
        help="with --rewrite-slice: rewrite only the price slice, leaving the chain as it was",
    )
    args = parser.parse_args(argv)
    if args.prices_only and args.rewrite_slice is None:
        parser.error("--prices-only needs --rewrite-slice")
    if args.rewrite_slice is not None:
        rewritten = rewrite_slice(args.out, args.rewrite_slice, prices_only=args.prices_only)
        print(
            f"rewrote {args.rewrite_slice}: bronze.option_chain {rewritten['option_chain']} rows; "
            f"bronze.underlying_price {rewritten['underlying_price']} rows -> {args.out}"
        )
        return 0
    counts = write_catalog(args.out)
    print(
        f"bronze.option_chain: {counts['option_chain']} rows; "
        f"bronze.underlying_price: {counts['underlying_price']} rows -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
