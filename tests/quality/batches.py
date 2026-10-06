"""Bronze batches for the quality gate, built deterministically from seeded generators.

History covers 20 dates of SPY and QQQ at roughly 100 rows per day, plus a NEW symbol with
only 3 days. The good batch is the next date at the usual volume; the broken batch carries
the five defects listed in ``BROKEN_FAILURES``.
"""

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import pandas as pd

from tests.bronze_factory import bronze_frame

HISTORY_START = date(2024, 1, 2)
HISTORY_DAYS = 20
BATCH_DATE = HISTORY_START + timedelta(days=HISTORY_DAYS)
USUAL_ROWS = 100
BROKEN_SYMBOL = "QQQ"
SHORT_HISTORY_SYMBOL = "NEW"

BROKEN_FAILURES = [
    "key_unique",
    "occ_symbol_not_null",
    "right_in_set",
    "row_count:QQQ",
    "strike_positive",
]


def build_history() -> pd.DataFrame:
    rng = random.Random(20240102)
    days: list[pd.DataFrame] = []
    for offset in range(HISTORY_DAYS):
        day = HISTORY_START + timedelta(days=offset)
        for symbol in ("SPY", "QQQ"):
            rows = USUAL_ROWS + rng.randint(-5, 5)
            days.append(
                bronze_frame(day, underlyings=(symbol,), rows_per_underlying=rows, seed=offset)
            )
        if offset >= HISTORY_DAYS - 3:
            days.append(
                bronze_frame(day, underlyings=(SHORT_HISTORY_SYMBOL,), rows_per_underlying=10)
            )
    return pd.concat(days, ignore_index=True)


def build_good() -> pd.DataFrame:
    return bronze_frame(
        BATCH_DATE, underlyings=("SPY", "QQQ"), rows_per_underlying=USUAL_ROWS, seed=1
    )


def build_broken() -> pd.DataFrame:
    """Five defects: null occ_symbol, negative strike, right X, duplicate key, 10x QQQ rows."""
    spy = bronze_frame(BATCH_DATE, underlyings=("SPY",), rows_per_underlying=USUAL_ROWS, seed=1)
    spy.loc[0, "occ_symbol"] = None
    spy.loc[1, "strike"] = cast(Any, Decimal("-5.00"))
    spy.loc[2, "right"] = "X"
    spy = pd.concat([spy, spy.iloc[[3]]], ignore_index=True)
    qqq = bronze_frame(
        BATCH_DATE, underlyings=(BROKEN_SYMBOL,), rows_per_underlying=10 * USUAL_ROWS, seed=2
    )
    return pd.concat([spy, qqq], ignore_index=True)
