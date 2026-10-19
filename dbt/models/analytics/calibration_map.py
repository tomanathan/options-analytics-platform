"""Fit the walk-forward isotonic calibration maps: one per fold year, plus the production map."""

from typing import Any

import pandas as pd

from oap.analytics.backtest import maps_to_frame, walk_forward_maps
from oap.analytics.io import OUTPUT_SCHEMAS, read_table, to_output


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Return the knots of every map; a fold map is fitted only on expirations before its year."""
    dbt.config(materialized="table")
    predictions = read_table(dbt.ref("calibration_prediction"))
    return to_output(
        maps_to_frame(walk_forward_maps(predictions)), OUTPUT_SCHEMAS["calibration_map"]
    )
