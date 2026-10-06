"""Ingestion of options chains and underlying prices into the bronze layer.

This package is the I/O boundary of oap. It reads from market data vendors and writes
Apache Iceberg tables on S3 (the bronze layer). Nothing outside ``ingest`` talks to a
vendor API, and nothing inside it transforms data beyond what is needed to land it
faithfully: prices stay in dollars as quoted, timestamps stay in UTC.

Writes must be idempotent per snapshot date: loading a date again replaces that date's data
instead of duplicating it, and earlier Iceberg snapshots remain readable through time
travel, so no load is ever lost.
"""
