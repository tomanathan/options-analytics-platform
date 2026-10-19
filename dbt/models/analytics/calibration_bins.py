"""Reliability table of raw and calibrated probabilities over the out-of-sample rows."""

from typing import Any

import pandas as pd

from oap.analytics.backtest import calibration_bins
from oap.analytics.io import OUTPUT_SCHEMAS, read_table, to_output


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Return ten equal-width probability bins per variant."""
    dbt.config(materialized="table")
    sample = read_table(dbt.ref("calibration_sample"))
    return to_output(calibration_bins(sample), OUTPUT_SCHEMAS["calibration_bins"])
