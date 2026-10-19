"""Read gold tables into frames and shape output frames for DuckDB.

This is the only module in ``oap.analytics`` that touches a database relation, and it does
so through a duck-typed protocol: anything with ``query(alias, sql)`` and ``df()`` works,
which covers the relations ``dbt.ref(...)`` returns in a dbt Python model on DuckDB and a
plain DuckDB relation in a test. ``duckdb`` is therefore not imported here.

Units are those of the gold tables: strikes, prices and closes are in dollars per share,
``dte_days`` is in calendar days, ``log_return`` is a dimensionless decimal.
"""

import re
from collections.abc import Mapping
from typing import Final, Protocol

import pandas as pd

QUOTE_SELECT: Final = (
    "select underlying, trade_date, expiration, cast(strike as double) as strike, option_right, "
    "cast(bid as double) as bid, cast(ask as double) as ask, "
    "cast(underlying_close as double) as underlying_close, dte_days from quotes"
)
QUOTES_SQL: Final = QUOTE_SELECT + " where underlying = '{underlying}'"
LATEST_QUOTES_SQL: Final = QUOTE_SELECT + " qualify trade_date = max(trade_date) over ()"
"""The quotes of the single latest ``trade_date`` across all underlyings.

One session for every underlying: an underlying with no quotes on that date (a symbol the
vendor skipped, a delisting) is absent from the scores rather than ranked on a stale chain.
"""
OUTCOMES_SQL: Final = (
    "select underlying, expiration, settlement_date, "
    "cast(settlement_close as double) as settlement_close from outcomes"
)
DAILY_SQL: Final = (
    "select underlying, trade_date, log_return from daily where log_return is not null"
)

_SYMBOL: Final = re.compile(r"^[A-Z][A-Z.]{0,9}$")

OUTPUT_SCHEMAS: Final[dict[str, dict[str, str]]] = {
    "calibration_snapshot": {
        "underlying": "VARCHAR",
        "trade_date": "DATE",
        "expiration": "DATE",
        "dte_days": "BIGINT",
        "underlying_close": "DOUBLE",
        "n_usable_puts": "BIGINT",
        "n_usable_calls": "BIGINT",
        "settlement_date": "DATE",
        "settlement_close": "DOUBLE",
        "status": "VARCHAR",
    },
    "calibration_prediction": {
        "underlying": "VARCHAR",
        "trade_date": "DATE",
        "expiration": "DATE",
        "settlement_date": "DATE",
        "dte_days": "BIGINT",
        "dte_years": "DOUBLE",
        "dte_bucket": "VARCHAR",
        "fold": "BIGINT",
        "moneyness": "DOUBLE",
        "target_strike": "DOUBLE",
        "underlying_close": "DOUBLE",
        "settlement_close": "DOUBLE",
        "predicted_raw": "DOUBLE",
        "realised": "BOOLEAN",
        "n_knots": "BIGINT",
        "forward": "DOUBLE",
        "cdf_flags": "VARCHAR",
    },
    "calibration_map": {
        "map_id": "VARCHAR",
        "fold": "NULLABLE_BIGINT",
        "train_cutoff": "DATE",
        "train_max_expiration": "DATE",
        "knot_index": "BIGINT",
        "predicted": "DOUBLE",
        "calibrated": "DOUBLE",
        "n_samples": "BIGINT",
        "is_identity": "BOOLEAN",
    },
    "calibration_sample": {
        "underlying": "VARCHAR",
        "trade_date": "DATE",
        "expiration": "DATE",
        "settlement_date": "DATE",
        "dte_days": "BIGINT",
        "dte_years": "DOUBLE",
        "dte_bucket": "VARCHAR",
        "fold": "BIGINT",
        "moneyness": "DOUBLE",
        "target_strike": "DOUBLE",
        "underlying_close": "DOUBLE",
        "settlement_close": "DOUBLE",
        "predicted_raw": "DOUBLE",
        "realised": "BOOLEAN",
        "n_knots": "BIGINT",
        "forward": "DOUBLE",
        "cdf_flags": "VARCHAR",
        "map_id": "VARCHAR",
        "predicted_calibrated": "DOUBLE",
        "is_out_of_sample": "BOOLEAN",
    },
    "calibration_metrics": {
        "segment_type": "VARCHAR",
        "segment": "VARCHAR",
        "variant": "VARCHAR",
        "metric": "VARCHAR",
        "value": "DOUBLE",
        "ci_low": "DOUBLE",
        "ci_high": "DOUBLE",
        "n_predictions": "BIGINT",
        "n_snapshots": "BIGINT",
        "n_clusters": "BIGINT",
    },
    "calibration_bins": {
        "variant": "VARCHAR",
        "bin_index": "BIGINT",
        "lower": "DOUBLE",
        "upper": "DOUBLE",
        "n": "BIGINT",
        "mean_predicted": "DOUBLE",
        "frequency_realised": "DOUBLE",
    },
    "spread_scores": {
        "spread_key": "VARCHAR",
        "underlying": "VARCHAR",
        "trade_date": "DATE",
        "expiration": "DATE",
        "dte_days": "BIGINT",
        "years": "DOUBLE",
        "underlying_close": "DOUBLE",
        "short_strike": "DOUBLE",
        "long_strike": "DOUBLE",
        "width": "DOUBLE",
        "credit": "DOUBLE",
        "credit_natural": "DOUBLE",
        "max_loss": "DOUBLE",
        "breakeven": "DOUBLE",
        "short_moneyness": "DOUBLE",
        "prob_profit": "DOUBLE",
        "prob_profit_raw": "DOUBLE",
        "prob_max_loss": "DOUBLE",
        "expected_payoff": "DOUBLE",
        "interest": "DOUBLE",
        "expected_roc": "DOUBLE",
        "expected_roc_raw": "DOUBLE",
        "annualised_roc": "DOUBLE",
        "annualised_roc_raw": "DOUBLE",
        "kelly_fraction": "DOUBLE",
        "calibrated": "BOOLEAN",
        "extrapolated": "BOOLEAN",
        "flags": "VARCHAR",
        "eligible": "BOOLEAN",
        "rank": "NULLABLE_BIGINT",
        "map_id": "VARCHAR",
        "cash_apy": "DOUBLE",
        "risk_free_apy": "DOUBLE",
    },
}


class Relation(Protocol):
    """The part of a DuckDB relation that this module uses."""

    def query(self, alias: str, sql: str, /) -> "Relation":
        """Run SQL that refers to this relation by ``alias``.

        Args:
            alias: Name under which the relation is visible to ``sql``.
            sql: A ``select`` statement.

        Returns:
            The result relation.
        """
        ...

    def df(self) -> pd.DataFrame:
        """Materialise the relation.

        Returns:
            The rows as a pandas frame.
        """
        ...


def _to_ns(frame: pd.DataFrame) -> pd.DataFrame:
    """Give every ``datetime64`` column nanosecond resolution.

    DuckDB returns microseconds; one resolution keeps comparisons and merges simple.

    Args:
        frame: Frame to normalise.

    Returns:
        The same frame with ``datetime64[ns]`` columns.
    """
    for name in frame.columns:
        if pd.api.types.is_datetime64_any_dtype(frame[name]):
            frame[name] = frame[name].astype("datetime64[ns]")
    return frame


def read_table(rel: Relation) -> pd.DataFrame:
    """Read a whole relation.

    Args:
        rel: Relation, such as ``dbt.ref("calibration_map")``.

    Returns:
        The rows, with dates as ``datetime64[ns]``.
    """
    return _to_ns(rel.df())


def read_quotes(rel: Relation, underlying: str) -> pd.DataFrame:
    """Read the quotes of one underlying from ``gold.fct_option_quote``.

    Args:
        rel: The ``fct_option_quote`` relation.
        underlying: Ticker symbol, such as ``"SPY"``; must match ``^[A-Z][A-Z.]{0,9}$``
            because it is interpolated into SQL.

    Returns:
        Quote rows with strike, bid, ask and close as doubles in dollars per share.

    Raises:
        ValueError: If the symbol does not match the pattern.
    """
    if not _SYMBOL.fullmatch(underlying):
        raise ValueError(f"invalid underlying symbol: {underlying!r}")
    return read_table(rel.query("quotes", QUOTES_SQL.format(underlying=underlying)))


def read_latest_quotes(rel: Relation) -> pd.DataFrame:
    """Read the latest session from ``gold.fct_option_quote``.

    The session is the one global maximum ``trade_date`` over all underlyings, so spreads
    of different underlyings are ranked on the same day and a stale underlying is left out.

    Args:
        rel: The ``fct_option_quote`` relation.

    Returns:
        Quote rows on the maximum ``trade_date`` of the whole relation; empty when the
        relation is empty.
    """
    return read_table(rel.query("quotes", LATEST_QUOTES_SQL))


def read_outcomes(rel: Relation) -> pd.DataFrame:
    """Read settlement closes from ``gold.fct_expiration_outcome``.

    Args:
        rel: The ``fct_expiration_outcome`` relation.

    Returns:
        One row per ``(underlying, expiration)`` with ``settlement_close`` in dollars.
    """
    return read_table(rel.query("outcomes", OUTCOMES_SQL))


def read_daily(rel: Relation) -> pd.DataFrame:
    """Read daily log returns from ``gold.fct_underlying_daily``.

    Args:
        rel: The ``fct_underlying_daily`` relation.

    Returns:
        Rows with ``underlying``, ``trade_date`` and a non-null ``log_return``.
    """
    return read_table(rel.query("daily", DAILY_SQL))


def _cast(series: pd.Series, sql_type: str, name: str) -> pd.Series:
    """Cast one column to the pandas dtype that DuckDB registers as ``sql_type``.

    Args:
        series: Column values.
        sql_type: ``DATE``, ``DOUBLE``, ``BIGINT``, ``NULLABLE_BIGINT``, ``BOOLEAN`` or
            ``VARCHAR``.
        name: Column name for error messages.

    Returns:
        The cast column. ``DATE`` columns with at least one value hold ``datetime.date``
        objects; a column with no values has no way to say DATE to DuckDB without
        pyarrow, so it becomes ``datetime64[ns]`` (a timestamp, comparable with dates).

    Raises:
        ValueError: If the type is unknown or a non-nullable column holds nulls.
    """
    if sql_type == "DATE":
        stamps = pd.to_datetime(series)
        if not stamps.notna().any():
            return stamps.astype("datetime64[ns]")
        dates = [None if pd.isna(v) else v.date() for v in stamps]
        return pd.Series(dates, index=series.index, dtype=object)
    if sql_type == "DOUBLE":
        return pd.to_numeric(series).astype("float64")
    if sql_type == "NULLABLE_BIGINT":
        return pd.to_numeric(series).astype("Int64")
    if sql_type in ("BIGINT", "BOOLEAN"):
        if series.isna().any():
            raise ValueError(f"column {name} is {sql_type} but holds nulls")
        return series.astype("int64" if sql_type == "BIGINT" else "bool")
    if sql_type == "VARCHAR":
        return series.astype("string")
    raise ValueError(f"unknown output type {sql_type!r} for column {name}")


def to_output(frame: pd.DataFrame, columns: Mapping[str, str]) -> pd.DataFrame:
    """Order and cast a frame to a declared output schema.

    Args:
        frame: Frame to shape.
        columns: Column name to type, such as ``OUTPUT_SCHEMAS["calibration_map"]``.
            Types are ``DATE``, ``DOUBLE``, ``BIGINT``, ``NULLABLE_BIGINT``, ``BOOLEAN``
            and ``VARCHAR``.

    Returns:
        A new frame with exactly ``columns``, in order, that DuckDB registers with the
        declared types (``NULLABLE_BIGINT`` is a BIGINT that may hold nulls; NaN doubles
        become NULL).

    Raises:
        ValueError: If a column is missing or extra, a type is unknown, or a
            non-nullable column holds nulls.
    """
    missing = [c for c in columns if c not in frame.columns]
    extra = [c for c in frame.columns if c not in columns]
    if missing or extra:
        raise ValueError(f"output columns differ: missing {missing}, unexpected {extra}")
    cast = {
        name: _cast(frame[name].reset_index(drop=True), sql_type, name)
        for name, sql_type in columns.items()
    }
    return pd.DataFrame(cast)
