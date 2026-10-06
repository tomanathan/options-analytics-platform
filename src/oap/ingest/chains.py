"""Daily options chain snapshot writer.

Phase 1 will implement this module. It will pull the end-of-day options chain for every
symbol on the watchlist from Alpaca and write it to the Iceberg table
``bronze.options_chain`` on S3, partitioned by trade date and underlying symbol. Each row
will carry the contract identifiers (underlying, expiry date, strike in dollars, put or
call), the bid, ask and last prices in dollars, volume, open interest, and the vendor's
quote timestamp in UTC.

Writes will be idempotent by snapshot date: re-running a day replaces that day's
partition for the affected underlyings rather than appending duplicates, so backfills and
retries are safe. The replaced data stays readable through Iceberg time travel on the
table's earlier snapshots.
"""
