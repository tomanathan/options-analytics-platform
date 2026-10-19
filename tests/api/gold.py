"""A small gold schema, in a DuckDB file, built from the engine and analytics test frames.

Two symbols (SPY and XLF), three sessions each and four expirations: one with 2 to 4 days to
expiry, two normal, one with only three usable puts. The first expiration has settled. The
calibration maps are the production map (fitted on synthetic predictions), ``fold_2024`` and
``fold_2020`` (identity). The spread scores are what ``score_latest_session`` returns for the
latest session, with one annualised return forced to infinity.

Units: strikes and prices in dollars per share, volatility as a decimal, time in years.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from oap.analytics.backtest import FittedMap, maps_to_frame
from oap.analytics.config import DEFAULT_CONFIG, PRODUCTION_MAP_ID, fold_map_id
from oap.analytics.io import OUTPUT_SCHEMAS, to_output
from oap.analytics.scoring import score_latest_session
from oap.engine.black_scholes import delta
from oap.engine.calibration import CalibrationMap, fit_isotonic_calibration
from tests.analytics.frames import lognormal_quotes, synthetic_predictions

SESSIONS = (date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6))
LATEST = SESSIONS[-1]
SHORT_EXPIRY = date(2024, 3, 8)
NEAR_EXPIRY = date(2024, 3, 28)
FAR_EXPIRY = date(2024, 4, 19)
THIN_EXPIRY = date(2024, 6, 21)
SETTLED_CLOSE = {"SPY": 497.0, "XLF": 41.2}
CLOSES = {
    "SPY": {SESSIONS[0]: 500.0, SESSIONS[1]: 503.0, SESSIONS[2]: 498.0},
    "XLF": {SESSIONS[0]: 40.0, SESSIONS[1]: 40.5, SESSIONS[2]: 41.0},
}
VOL = 0.30
RATE = DEFAULT_CONFIG.risk_free_apy
PRODUCTION_TRAIN_MAX = date(2024, 3, 6)


@dataclass(frozen=True)
class GoldFixture:
    """A built database and the frames it was built from.

    Attributes:
        path: The DuckDB file.
        quotes: Every quote row, as stored (strike as double).
        production: The production calibration map.
        scores: The stored spread scores.
        inf_key: Key of the spread whose ``annualised_roc`` is infinite.
    """

    path: Path
    quotes: pd.DataFrame
    production: CalibrationMap
    scores: pd.DataFrame
    inf_key: str


def strikes_for(close: float) -> np.ndarray:
    """Return a strike grid from 70% to 130% of the close in steps of 2% of the close.

    Args:
        close: Underlying close in dollars.

    Returns:
        Strikes rounded to the cent.
    """
    return np.round(close * np.arange(0.70, 1.3001, 0.02), 2)


def build_quotes() -> pd.DataFrame:
    """Build every quote row with the gold columns the API reads.

    Returns:
        Quote rows with mid, source IV, source delta, moneyness and dte.
    """
    parts: list[pd.DataFrame] = []
    for symbol, by_session in CLOSES.items():
        for session, close in by_session.items():
            for expiration in (SHORT_EXPIRY, NEAR_EXPIRY, FAR_EXPIRY, THIN_EXPIRY):
                strikes = strikes_for(close)
                if expiration == THIN_EXPIRY:
                    strikes = strikes[np.argsort(np.abs(strikes - close))[:3]]
                chain = lognormal_quotes(symbol, session, expiration, close, VOL, RATE, strikes)
                parts.append(chain)
    quotes = pd.concat(parts, ignore_index=True)
    quotes["mid"] = (quotes["bid"] + quotes["ask"]) / 2.0
    quotes["source_iv"] = VOL
    quotes["moneyness"] = quotes["strike"] / quotes["underlying_close"]
    years = quotes["dte_days"].to_numpy(dtype=np.float64) / 365.0
    deltas = np.empty(len(quotes))
    for right in ("C", "P"):
        rows = (quotes["option_right"] == right).to_numpy()
        deltas[rows] = delta(
            quotes.loc[rows, "underlying_close"].to_numpy(),
            quotes.loc[rows, "strike"].to_numpy(),
            years[rows],
            RATE,
            VOL,
            "C" if right == "C" else "P",
        )
    quotes["source_delta"] = deltas
    return quotes


def build_maps() -> tuple[pd.DataFrame, CalibrationMap]:
    """Build the calibration map table.

    Returns:
        The stored table (production, ``fold_2024``, ``fold_2020``) and the production map.
    """
    predictions = synthetic_predictions([2022, 2023], 400)
    production = fit_isotonic_calibration(
        predictions["predicted_raw"].to_numpy(), predictions["realised"].to_numpy()
    )
    maps = {
        PRODUCTION_MAP_ID: FittedMap(
            PRODUCTION_MAP_ID, None, None, PRODUCTION_TRAIN_MAX, production
        ),
        fold_map_id(2024): FittedMap(
            fold_map_id(2024),
            2024,
            date(2024, 1, 1),
            date(2023, 12, 29),
            CalibrationMap.identity(0),
        ),
        fold_map_id(2020): FittedMap(
            fold_map_id(2020), 2020, date(2020, 1, 1), None, CalibrationMap.identity(0)
        ),
    }
    return maps_to_frame(maps), production


def build_metrics() -> pd.DataFrame:
    """Build the overall calibration metrics, named as in the gold table.

    Returns:
        Rows for brier_score, log_loss and expected_calibration_error in the raw and
        calibrated variants, and the delta variant for the Brier score only, as the real
        table has them.
    """
    values = {
        "brier_score": (0.1267, 0.1293, True),
        "log_loss": (0.40, 0.41, False),
        "expected_calibration_error": (0.0352, 0.0167, False),
    }
    rows = []
    for metric, (raw, calibrated, has_delta) in values.items():
        variants = [("raw", raw), ("calibrated", calibrated)]
        if has_delta:
            variants.append(("delta", calibrated - raw))
        for variant, value in variants:
            rows.append(
                {
                    "segment_type": "overall",
                    "segment": "all",
                    "variant": variant,
                    "metric": metric,
                    "value": value,
                    "ci_low": value - 0.01,
                    "ci_high": value + 0.01,
                    "n_predictions": 1000,
                    "n_snapshots": 120,
                    "n_clusters": 40,
                }
            )
    # A row of another segment type that the API must not return.
    rows.append({**rows[0], "segment_type": "underlying", "segment": "SPY"})
    return to_output(pd.DataFrame(rows), OUTPUT_SCHEMAS["calibration_metrics"])


def build_gold(path: Path) -> GoldFixture:
    """Write the gold schema to a DuckDB file.

    Args:
        path: File to create.

    Returns:
        The fixture, with the frames the file was built from.
    """
    quotes = build_quotes()
    maps, production = build_maps()
    latest = quotes.loc[quotes["trade_date"] == pd.Timestamp(LATEST)]
    scores = to_output(score_latest_session(latest, production), OUTPUT_SCHEMAS["spread_scores"])
    inf_row = int(scores.index[scores["eligible"].astype(bool)][0])
    inf_key = str(scores.loc[inf_row, "spread_key"])
    scores.loc[inf_row, "annualised_roc"] = float("inf")
    outcomes = pd.DataFrame(
        {
            "underlying": list(SETTLED_CLOSE),
            "expiration": pd.Timestamp(SHORT_EXPIRY),
            "settlement_date": pd.Timestamp(SHORT_EXPIRY),
            "settlement_close": list(SETTLED_CLOSE.values()),
        }
    )
    dim = pd.DataFrame({"symbol": ["SPY", "XLF"], "sector": ["Index", "Financials"]})
    con = duckdb.connect(str(path))
    try:
        con.execute("create schema gold")
        for name, frame in (
            ("q", quotes),
            ("o", outcomes),
            ("d", dim),
            ("m", maps),
            ("k", build_metrics()),
            ("s", scores),
        ):
            con.register(name, frame)
        con.execute(
            "create table gold.fct_option_quote as select underlying, "
            "cast(trade_date as date) as trade_date, cast(expiration as date) as expiration, "
            "cast(strike as decimal(10,3)) as strike, option_right, bid, ask, mid, source_iv, "
            "source_delta, moneyness, underlying_close, dte_days from q"
        )
        con.execute(
            "create table gold.fct_expiration_outcome as select underlying, "
            "cast(expiration as date) as expiration, cast(settlement_date as date) as "
            "settlement_date, cast(settlement_close as decimal(12,4)) as settlement_close from o"
        )
        con.execute("create table gold.dim_underlying as select * from d")
        con.execute(
            "create table gold.calibration_map as select map_id, fold, "
            "cast(train_cutoff as date) as train_cutoff, "
            "cast(train_max_expiration as date) as train_max_expiration, knot_index, predicted, "
            "calibrated, n_samples, is_identity from m"
        )
        con.execute("create table gold.calibration_metrics as select * from k")
        con.execute(
            "create table gold.spread_scores as select * replace "
            "(cast(trade_date as date) as trade_date, cast(expiration as date) as expiration) "
            "from s"
        )
    finally:
        con.close()
    return GoldFixture(
        path=path, quotes=quotes, production=production, scores=scores, inf_key=inf_key
    )
