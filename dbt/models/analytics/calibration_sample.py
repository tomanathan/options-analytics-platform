"""Apply each fold's map to that fold's predictions, giving the backtest sample."""

from typing import Any

import pandas as pd

from oap.analytics.backtest import apply_fold_maps, maps_from_frame
from oap.analytics.io import OUTPUT_SCHEMAS, read_table, to_output


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Return every prediction with its calibrated probability and an out-of-sample flag."""
    dbt.config(materialized="table")
    predictions, maps = (
        read_table(dbt.ref("calibration_prediction")),
        read_table(dbt.ref("calibration_map")),
    )
    return to_output(
        apply_fold_maps(predictions, maps_from_frame(maps)), OUTPUT_SCHEMAS["calibration_sample"]
    )
