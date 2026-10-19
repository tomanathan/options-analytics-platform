"""Brier score, log loss and expected calibration error of raw and calibrated probabilities."""

from typing import Any

import pandas as pd

from oap.analytics.backtest import calibration_metrics
from oap.analytics.io import OUTPUT_SCHEMAS, read_table, to_output


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Return the out-of-sample metrics overall and by underlying, DTE bucket and fold."""
    dbt.config(materialized="table")
    sample = read_table(dbt.ref("calibration_sample"))
    return to_output(calibration_metrics(sample), OUTPUT_SCHEMAS["calibration_metrics"])
