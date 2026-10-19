from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from oap.analytics.backtest import (
    BIN_COLUMNS,
    MAP_COLUMNS,
    METRIC_COLUMNS,
    SAMPLE_COLUMNS,
    apply_fold_maps,
    calibration_bins,
    calibration_metrics,
    maps_to_frame,
    walk_forward_maps,
)
from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.io import (
    OUTPUT_SCHEMAS,
    read_daily,
    read_latest_quotes,
    read_outcomes,
    read_quotes,
    read_table,
    to_output,
)
from oap.analytics.sample import (
    PREDICTION_COLUMNS,
    SNAPSHOT_COLUMNS,
    build_predictions,
    classify_snapshots,
)
from oap.analytics.scoring import SPREAD_COLUMNS, latest_session, score_latest_session
from oap.engine.calibration import CalibrationMap
from tests.analytics.frames import (
    daily_frame,
    lognormal_quotes,
    outcomes_frame,
    synthetic_predictions,
)

DUCKDB_TYPE = {
    "DATE": "DATE",
    "DOUBLE": "DOUBLE",
    "BIGINT": "BIGINT",
    "NULLABLE_BIGINT": "BIGINT",
    "BOOLEAN": "BOOLEAN",
    "VARCHAR": "VARCHAR",
}


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(
        "create table fct_option_quote (underlying varchar, trade_date date, expiration date, "
        "strike decimal(10, 3), option_right varchar, bid double, ask double, "
        "underlying_close double, dte_days bigint)"
    )
    expiry = date(2024, 2, 2)
    rows = [
        ("SPY", date(2024, 1, 4), expiry, 99.5, "P", 1.0, 1.2, 100.0, 29),
        ("SPY", date(2024, 1, 5), expiry, 100.0, "P", 1.1, 1.3, 101.0, 28),
        ("SPY", date(2024, 1, 5), expiry, 100.0, "C", 2.1, 2.3, 101.0, 28),
        ("AAPL", date(2024, 1, 4), expiry, 190.0, "P", 3.0, 3.2, 191.0, 29),
        ("BRK.B", date(2024, 1, 5), expiry, 400.0, "P", 5.0, 5.4, 401.0, 28),
    ]
    connection.executemany("insert into fct_option_quote values (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.execute(
        """
        create table fct_expiration_outcome as
        select * from (values
            ('SPY', date '2024-02-02', date '2024-02-02', cast(103.25 as decimal(18, 4)))
        ) as t(underlying, expiration, settlement_date, settlement_close)
        """
    )
    connection.execute(
        """
        create table fct_underlying_daily as
        select * from (values
            ('SPY', date '2024-01-05', 0.01), ('SPY', date '2024-01-04', null)
        ) as t(underlying, trade_date, log_return)
        """
    )
    return connection


def test_read_quotes_reads_decimals_as_floats_and_filters(con: duckdb.DuckDBPyConnection) -> None:
    quotes = read_quotes(con.table("fct_option_quote"), "SPY")
    assert len(quotes) == 3
    assert set(quotes["underlying"]) == {"SPY"}
    assert quotes["strike"].dtype == np.float64
    assert quotes["bid"].dtype == np.float64
    assert quotes["underlying_close"].dtype == np.float64
    assert quotes["trade_date"].dtype == "datetime64[ns]"
    assert quotes["expiration"].dtype == "datetime64[ns]"
    assert sorted(quotes["strike"]) == [99.5, 100.0, 100.0]


def test_symbols_with_dots_are_accepted(con: duckdb.DuckDBPyConnection) -> None:
    assert len(read_quotes(con.table("fct_option_quote"), "BRK.B")) == 1


@pytest.mark.parametrize(
    "symbol", ["SPY' or '1'='1", "spy", "", "SPY;", "1ABC", "A" * 11, "SPY\n", "S PY", "SPY--"]
)
def test_malicious_or_malformed_symbols_are_rejected(
    con: duckdb.DuckDBPyConnection, symbol: str
) -> None:
    with pytest.raises(ValueError, match="invalid underlying"):
        read_quotes(con.table("fct_option_quote"), symbol)


def test_latest_quotes_use_each_underlyings_own_maximum(con: duckdb.DuckDBPyConnection) -> None:
    latest = read_latest_quotes(con.table("fct_option_quote"))
    by_underlying = latest.groupby("underlying")["trade_date"].agg(["min", "max"])
    assert by_underlying.loc["SPY", "min"] == pd.Timestamp("2024-01-05")
    assert by_underlying.loc["AAPL", "max"] == pd.Timestamp("2024-01-04")
    assert len(latest) == 4


def test_outcomes_and_daily(con: duckdb.DuckDBPyConnection) -> None:
    outcomes = read_outcomes(con.table("fct_expiration_outcome"))
    assert outcomes["settlement_close"].dtype == np.float64
    assert outcomes["settlement_close"].iloc[0] == 103.25
    assert outcomes["settlement_date"].dtype == "datetime64[ns]"
    daily = read_daily(con.table("fct_underlying_daily"))
    assert len(daily) == 1
    assert daily["log_return"].iloc[0] == 0.01


def test_read_table_returns_the_whole_relation(con: duckdb.DuckDBPyConnection) -> None:
    assert len(read_table(con.table("fct_option_quote"))) == 5


def test_reads_feed_the_pure_core(con: duckdb.DuckDBPyConnection) -> None:
    quotes = read_quotes(con.table("fct_option_quote"), "SPY")
    snaps = classify_snapshots(
        quotes,
        read_outcomes(con.table("fct_expiration_outcome")),
        read_daily(con.table("fct_underlying_daily")),
    )
    assert snaps["status"].tolist() == ["too_few_puts", "too_few_puts"]


def test_to_output_raises_on_a_missing_column() -> None:
    frame = pd.DataFrame({"a": [1.0]})
    with pytest.raises(ValueError, match="missing.*'b'"):
        to_output(frame, {"a": "DOUBLE", "b": "DOUBLE"})


def test_to_output_raises_on_an_extra_column() -> None:
    frame = pd.DataFrame({"a": [1.0], "extra": [2.0]})
    with pytest.raises(ValueError, match="unexpected.*'extra'"):
        to_output(frame, {"a": "DOUBLE"})


def test_to_output_rejects_unknown_types_and_nulls_in_required_columns() -> None:
    with pytest.raises(ValueError, match="unknown output type"):
        to_output(pd.DataFrame({"a": [1]}), {"a": "DECIMAL"})
    with pytest.raises(ValueError, match="holds nulls"):
        to_output(pd.DataFrame({"a": [1.0, np.nan]}), {"a": "BIGINT"})
    with pytest.raises(ValueError, match="holds nulls"):
        to_output(pd.DataFrame({"a": [True, None]}), {"a": "BOOLEAN"})


def test_to_output_orders_columns_and_resets_the_index() -> None:
    frame = pd.DataFrame({"b": [1, 2], "a": [0.5, 1.5]}, index=[10, 20])
    out = to_output(frame, {"a": "DOUBLE", "b": "BIGINT"})
    assert list(out.columns) == ["a", "b"]
    assert out.index.tolist() == [0, 1]
    assert out["b"].dtype == np.int64


def _example_value(sql_type: str, row: int) -> object:
    nullable = row == 1
    return {
        "DATE": None if nullable else pd.Timestamp("2024-02-02"),
        "DOUBLE": float("nan") if nullable else 1.5,
        "BIGINT": 7,
        "NULLABLE_BIGINT": None if nullable else 3,
        "BOOLEAN": bool(row),
        "VARCHAR": None if nullable else "x",
    }[sql_type]


@pytest.mark.parametrize("table", sorted(OUTPUT_SCHEMAS))
def test_registered_output_has_the_declared_duckdb_types(
    con: duckdb.DuckDBPyConnection, table: str
) -> None:
    schema = OUTPUT_SCHEMAS[table]
    raw = pd.DataFrame({c: [_example_value(t, 0), _example_value(t, 1)] for c, t in schema.items()})
    out = to_output(raw, schema)
    con.register("out_frame", out)
    described = con.execute("describe select * from out_frame").fetchall()
    assert [(name, kind) for name, kind, *_ in described] == [
        (name, DUCKDB_TYPE[sql_type]) for name, sql_type in schema.items()
    ]
    nulls = con.execute("select * from out_frame").df().isna().sum()
    for column, sql_type in schema.items():
        expected = 0 if sql_type in ("BIGINT", "BOOLEAN") else 1
        assert nulls[column] == expected, column


def test_nan_doubles_become_null_and_dates_stay_dates(con: duckdb.DuckDBPyConnection) -> None:
    out = to_output(
        pd.DataFrame({"d": [pd.Timestamp("2024-02-02"), pd.NaT], "x": [np.nan, 2.0]}),
        {"d": "DATE", "x": "DOUBLE"},
    )
    con.register("out_frame", out)
    assert con.execute("select d, x from out_frame").fetchall() == [
        (date(2024, 2, 2), None),
        (None, 2.0),
    ]


def test_empty_frames_keep_their_declared_types_except_dates(
    con: duckdb.DuckDBPyConnection,
) -> None:
    schema = OUTPUT_SCHEMAS["calibration_snapshot"]
    out = to_output(pd.DataFrame({c: pd.Series(dtype="object") for c in schema}), schema)
    con.register("out_frame", out)
    kinds = {n: k for n, k, *_ in con.execute("describe select * from out_frame").fetchall()}
    for column, sql_type in schema.items():
        expected = "TIMESTAMP_NS" if sql_type == "DATE" else DUCKDB_TYPE[sql_type]
        assert kinds[column] == expected, column


def test_schemas_list_exactly_the_documented_columns_in_order() -> None:
    assert list(OUTPUT_SCHEMAS["calibration_snapshot"]) == list(SNAPSHOT_COLUMNS)
    assert list(OUTPUT_SCHEMAS["calibration_prediction"]) == list(PREDICTION_COLUMNS)
    assert list(OUTPUT_SCHEMAS["calibration_map"]) == list(MAP_COLUMNS)
    assert list(OUTPUT_SCHEMAS["calibration_sample"]) == list(SAMPLE_COLUMNS)
    assert list(OUTPUT_SCHEMAS["calibration_metrics"]) == list(METRIC_COLUMNS)
    assert list(OUTPUT_SCHEMAS["calibration_bins"]) == list(BIN_COLUMNS)
    assert list(OUTPUT_SCHEMAS["spread_scores"]) == list(SPREAD_COLUMNS)


def test_real_outputs_pass_through_to_output(con: duckdb.DuckDBPyConnection) -> None:
    rate = DEFAULT_CONFIG.risk_free_apy
    strikes = np.arange(80.0, 121.0, 1.0)
    quotes = lognormal_quotes("SPY", date(2024, 1, 5), date(2024, 2, 2), 100.0, 0.25, rate, strikes)
    outcomes = outcomes_frame([("SPY", date(2024, 2, 2), date(2024, 2, 2), 99.0)])
    daily = daily_frame([("SPY", date(2024, 1, 10), 0.01)])
    snapshots = classify_snapshots(quotes, outcomes, daily)
    predictions = build_predictions(quotes, snapshots)
    preds = synthetic_predictions([2020, 2021, 2022, 2023], 300)
    maps = walk_forward_maps(preds)
    sample = apply_fold_maps(preds, {k: v.cmap for k, v in maps.items()})
    tables = {
        "calibration_snapshot": snapshots,
        "calibration_prediction": predictions,
        "calibration_map": maps_to_frame(maps),
        "calibration_sample": sample,
        "calibration_metrics": calibration_metrics(sample),
        "calibration_bins": calibration_bins(sample),
        "spread_scores": score_latest_session(
            latest_session(quotes, min_dte_days=7), CalibrationMap.identity(0)
        ),
    }
    assert set(tables) == set(OUTPUT_SCHEMAS)
    for name, frame in tables.items():
        assert not frame.empty, name
        out = to_output(frame, OUTPUT_SCHEMAS[name])
        con.register(f"{name}_out", out)
        assert con.execute(f"select count(*) from {name}_out").fetchone() == (len(frame),)
