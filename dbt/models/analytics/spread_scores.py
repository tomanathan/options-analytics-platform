"""Score every put credit spread of the latest session in gold under the production map."""

from typing import Any

import pandas as pd

from oap.analytics.backtest import maps_from_frame
from oap.analytics.config import PRODUCTION_MAP_ID
from oap.analytics.io import OUTPUT_SCHEMAS, read_latest_quotes, read_table, to_output
from oap.analytics.scoring import score_latest_session


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Return one row per candidate spread with raw and calibrated scores and a rank."""
    dbt.config(materialized="table")
    quotes, maps = (
        read_latest_quotes(dbt.ref("fct_option_quote")),
        read_table(dbt.ref("calibration_map")),
    )
    scores = score_latest_session(quotes, maps_from_frame(maps)[PRODUCTION_MAP_ID])
    return to_output(scores, OUTPUT_SCHEMAS["spread_scores"])
