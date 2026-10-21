"""A tiny gold schema for the growth lab scripts, built as the rule lab's test fixture is.

Two underlyings, four sessions in 2021-2022 with expiries 14 and 28 days out, Black-Scholes
chains with a vendor IV, settlement closes on both sides of the money, daily returns from
mid-2020, and synthetic calibration predictions with the walk-forward maps fitted on them,
so the refitted pooled maps equal ``gold.calibration_map``. Prices in dollars per share,
volatility as a decimal.
"""

from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from oap.analytics.backtest import maps_to_frame, walk_forward_maps
from tests.analytics.frames import lognormal_quotes, outcomes_frame, synthetic_predictions

SESSIONS = [date(2021, 3, 1), date(2021, 9, 1), date(2022, 3, 1), date(2022, 9, 1)]
UNDERLYINGS = (
    ("SPY", 100.0, np.arange(80.0, 121.0)),
    ("AAPL", 190.0, np.arange(160.0, 221.0, 2.0)),
)
SETTLEMENT_MOVES = (0.93, 1.08)
"""Settlement close over the close, alternating by expiry so some options pay off."""


def write_growth_gold(path: Path) -> Path:
    """Write the tiny gold schema to a new DuckDB file.

    Args:
        path: The DuckDB file to create.

    Returns:
        ``path``.
    """
    quotes = pd.concat(
        [
            lognormal_quotes(underlying, day, day + timedelta(days=dte), close, 0.3, 0.045, strikes)
            for day in SESSIONS
            for underlying, close, strikes in UNDERLYINGS
            for dte in (14, 28)
        ],
        ignore_index=True,
    )
    quotes["source_iv"] = 0.3
    snapshots = quotes[["underlying", "trade_date", "expiration"]].drop_duplicates()
    snapshots = snapshots.assign(status="ok")
    expiries = quotes[["underlying", "expiration", "underlying_close"]].drop_duplicates(
        ["underlying", "expiration"]
    )
    outcomes = outcomes_frame(
        [
            (u, e.date(), e.date(), close * SETTLEMENT_MOVES[i % 2])
            for i, (u, e, close) in enumerate(
                zip(
                    expiries["underlying"],
                    expiries["expiration"],
                    expiries["underlying_close"],
                    strict=True,
                )
            )
        ]
    )
    days = pd.bdate_range("2020-06-01", "2022-10-31")
    daily = pd.concat(
        [
            pd.DataFrame(
                {
                    "underlying": u,
                    "trade_date": days,
                    "close_price": 100.0,
                    "log_return": np.r_[np.nan, np.full(len(days) - 1, step)],
                }
            )
            for u, step in (("SPY", 0.001), ("AAPL", -0.001))
        ],
        ignore_index=True,
    )
    predictions = synthetic_predictions([2020, 2021, 2022], 400)
    maps = maps_to_frame(walk_forward_maps(predictions))
    con = duckdb.connect(str(path))
    con.execute("create schema gold")
    for name, frame in (
        ("fct_option_quote", quotes),
        ("calibration_snapshot", snapshots),
        ("fct_expiration_outcome", outcomes),
        ("calibration_map", maps),
        ("calibration_prediction", predictions),
        ("fct_underlying_daily", daily),
    ):
        con.register("frame", frame)
        con.execute(f"create table gold.{name} as select * from frame")
        con.unregister("frame")
    con.execute(
        "alter table gold.fct_option_quote alter trade_date type date; "
        "alter table gold.fct_option_quote alter expiration type date"
    )
    con.close()
    return path
