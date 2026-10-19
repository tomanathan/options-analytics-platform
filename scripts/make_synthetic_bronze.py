"""Write a small synthetic Iceberg bronze catalog for the dbt build and its tests.

The catalog is written through the same ``ensure_table`` and ``write_partition`` that Airflow
uses, so ``make dbt-build`` exercises the exact catalog resolution and ``iceberg_scan`` path of
a real run without any vendor data. Usage: ``make_synthetic_bronze.py [--out DIR]``.

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
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from oap.calendar import trading_days
from oap.ingest.iceberg_writer import ensure_table, write_partition
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


def main(argv: Sequence[str] | None = None) -> int:
    """Write the synthetic catalog and print the row counts.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        Process exit code, 0 on success.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT), help="catalog directory")
    args = parser.parse_args(argv)
    counts = write_catalog(args.out)
    print(
        f"bronze.option_chain: {counts['option_chain']} rows; "
        f"bronze.underlying_price: {counts['underlying_price']} rows -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
