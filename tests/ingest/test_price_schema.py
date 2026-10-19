from collections.abc import Callable
from datetime import date
from typing import Any, cast

import pandas as pd
import pandera.errors
import pytest

from oap.ingest.price_schema import (
    PRICE_FRAME,
    PRICE_KEY_COLUMNS,
    PRICE_SCHEMA,
    PRICE_SOURCES,
)
from tests.ingest.price_factory import price_frame

DAY = date(2024, 1, 5)

Mutation = Callable[[pd.DataFrame], pd.DataFrame]


def _frame() -> pd.DataFrame:
    return price_frame(DAY, ("SPY", "QQQ", "IWM"), seed=1)


def _set(column: str, value: object) -> Mutation:
    def mutate(frame: pd.DataFrame) -> pd.DataFrame:
        frame.loc[0, column] = cast(Any, value)
        return frame

    return mutate


def _bar(high: float, low: float, close: float) -> Mutation:
    def mutate(frame: pd.DataFrame) -> pd.DataFrame:
        frame.loc[0, ["high", "low", "close"]] = [high, low, close]
        return frame

    return mutate


def _duplicate_key(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([frame, frame.iloc[[0]]], ignore_index=True)


def _extra_column(frame: pd.DataFrame) -> pd.DataFrame:
    frame["adj_close"] = 1.0
    return frame


def test_constants_describe_the_price_feed() -> None:
    assert sorted(PRICE_SOURCES) == ["dolthub_stocks"]
    assert PRICE_KEY_COLUMNS == ("underlying", "trade_date", "source")
    assert PRICE_SCHEMA.names == [
        "trade_date",
        "underlying",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "ingested_at",
    ]
    assert {f.name for f in PRICE_SCHEMA if not f.nullable} == {
        "trade_date",
        "underlying",
        "close",
        "source",
        "ingested_at",
    }


def test_a_valid_frame_passes() -> None:
    frame = _frame()

    assert PRICE_FRAME.validate(frame, lazy=True).equals(frame)


def test_the_empty_frame_passes() -> None:
    PRICE_FRAME.validate(price_frame(DAY, ()), lazy=True)


@pytest.mark.parametrize(
    ("mutate", "failing_check"),
    [
        pytest.param(
            _bar(high=10.0, low=11.0, close=10.5), "high must not be below low", id="high-below-low"
        ),
        pytest.param(
            _bar(high=10.0, low=9.0, close=10.5), "close must lie between", id="close-above-high"
        ),
        pytest.param(
            _bar(high=10.0, low=9.0, close=8.5), "close must lie between", id="close-below-low"
        ),
        pytest.param(_set("close", 0.0), "close must be positive", id="close-zero"),
        pytest.param(_set("volume", -1), "volume must not be negative", id="negative-volume"),
        pytest.param(
            _set("source", "yahoo"), "source must be a known price feed", id="unknown-source"
        ),
        pytest.param(_duplicate_key, "unique", id="duplicate-key"),
        pytest.param(_set("close", None), "not_nullable", id="null-close"),
        pytest.param(_extra_column, "column_in_schema", id="extra-column"),
    ],
)
def test_price_frame_rejects(mutate: Mutation, failing_check: str) -> None:
    frame = mutate(_frame())

    with pytest.raises(pandera.errors.SchemaErrors) as raised:
        PRICE_FRAME.validate(frame, lazy=True)
    reported = set(raised.value.failure_cases["check"].astype(str))
    assert any(failing_check in check for check in reported), reported


def test_open_outside_range_is_accepted() -> None:
    # IWM 2021-05-05 as DoltHub holds it: open 224.28 above a high of 224.16.
    frame = price_frame(date(2021, 5, 5), ("IWM",))
    frame.loc[0, ["open", "high", "low", "close"]] = [224.28, 224.16, 221.61, 222.86]

    PRICE_FRAME.validate(frame, lazy=True)


def test_nullable_ohlv_pass() -> None:
    frame = _frame()
    frame.loc[0, ["open", "high", "low", "volume"]] = None
    frame.loc[1, ["high"]] = None
    frame.loc[2, ["low"]] = None

    PRICE_FRAME.validate(frame, lazy=True)
