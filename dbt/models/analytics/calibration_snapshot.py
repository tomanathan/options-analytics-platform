"""Classify every chain snapshot (underlying, trade date, expiration) for the calibration sample."""

from typing import Any

import pandas as pd

from oap.analytics.io import OUTPUT_SCHEMAS, read_daily, read_outcomes, read_quotes, to_output
from oap.analytics.sample import SNAPSHOT_COLUMNS, classify_snapshots, empty_frame


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Return one row per snapshot with its usable-quote counts, outcome and exclusion status."""
    dbt.config(materialized="table")
    quotes = dbt.ref("fct_option_quote")
    outcomes, daily = (
        read_outcomes(dbt.ref("fct_expiration_outcome")),
        read_daily(dbt.ref("fct_underlying_daily")),
    )
    symbols = [
        row[0]
        for row in quotes.query("q", "select distinct underlying from q order by 1").fetchall()
    ]
    parts = [classify_snapshots(read_quotes(quotes, symbol), outcomes, daily) for symbol in symbols]
    frame = pd.concat(parts, ignore_index=True) if parts else empty_frame(SNAPSHOT_COLUMNS)
    return to_output(frame, OUTPUT_SCHEMAS["calibration_snapshot"])
