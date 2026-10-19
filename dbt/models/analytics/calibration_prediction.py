"""Predict P(S_T < K) from each ok snapshot's risk-neutral CDF and attach the outcome."""

from typing import Any

import pandas as pd

from oap.analytics.io import OUTPUT_SCHEMAS, read_quotes, read_table, to_output
from oap.analytics.sample import PREDICTION_COLUMNS, build_predictions, empty_frame


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Return one row per ok snapshot and grid target inside the CDF's strike range."""
    dbt.config(materialized="table")
    quotes, snapshots = dbt.ref("fct_option_quote"), read_table(dbt.ref("calibration_snapshot"))
    symbols = sorted(snapshots["underlying"].unique())
    parts = [
        build_predictions(read_quotes(quotes, s), snapshots[snapshots["underlying"] == s])
        for s in symbols
    ]
    frame = pd.concat(parts, ignore_index=True) if parts else empty_frame(PREDICTION_COLUMNS)
    return to_output(frame, OUTPUT_SCHEMAS["calibration_prediction"])
