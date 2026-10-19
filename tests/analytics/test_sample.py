from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.analytics.config import DEFAULT_CONFIG, AnalyticsConfig
from oap.analytics.sample import (
    PREDICTION_COLUMNS,
    SNAPSHOT_COLUMNS,
    SnapshotStatus,
    build_predictions,
    chain_cdf,
    classify_snapshots,
    split_events,
    usable_mask,
)
from oap.engine.implied_distribution import QualityFlag, usable_quotes
from tests.analytics.frames import daily_frame, lognormal_quotes, outcomes_frame
from tests.engine.chains import lognormal_cdf

TRADE = date(2024, 1, 5)
EXPIRY = date(2024, 2, 2)
SETTLE = date(2024, 2, 2)
RATE = DEFAULT_CONFIG.risk_free_apy
STRIKES = np.arange(70.0, 131.0, 1.0)


def _chain(
    underlying: str = "SPY",
    trade: date = TRADE,
    expiry: date = EXPIRY,
    close: float = 100.0,
    vol: float = 0.25,
) -> pd.DataFrame:
    return lognormal_quotes(underlying, trade, expiry, close, vol, RATE, STRIKES)


def _outcome(underlying: str = "SPY", expiry: date = EXPIRY, close: float = 101.0) -> pd.DataFrame:
    return outcomes_frame([(underlying, expiry, SETTLE, close)])


def _calm(underlying: str = "SPY") -> pd.DataFrame:
    return daily_frame([(underlying, date(2024, 1, 10), 0.01)])


def _status(quotes: pd.DataFrame, outcomes: pd.DataFrame, daily: pd.DataFrame) -> str:
    snaps = classify_snapshots(quotes, outcomes, daily)
    assert len(snaps) == 1
    return str(snaps["status"].iloc[0])


def test_baseline_snapshot_is_ok() -> None:
    snaps = classify_snapshots(_chain(), _outcome(), _calm())
    assert tuple(snaps.columns) == SNAPSHOT_COLUMNS
    row = snaps.iloc[0]
    assert row["status"] == SnapshotStatus.OK
    assert row["dte_days"] == 28
    assert row["settlement_close"] == 101.0
    assert row["n_usable_puts"] > 4
    assert row["n_usable_calls"] > 4


def test_no_outcome_is_unsettled() -> None:
    other = _outcome(expiry=date(2024, 3, 1))
    assert _status(_chain(), other, _calm()) == SnapshotStatus.UNSETTLED


def test_three_usable_puts_plus_zero_bid_put_is_too_few_puts() -> None:
    chain = lognormal_quotes("SPY", TRADE, EXPIRY, 100.0, 0.25, RATE, [95.0, 98.0, 100.0, 102.0])
    chain = chain.loc[chain["option_right"] == "P"].reset_index(drop=True)
    chain.loc[0, "bid"] = 0.0
    assert _status(chain, _outcome(), _calm()) == SnapshotStatus.TOO_FEW_PUTS
    snaps = classify_snapshots(chain, _outcome(), _calm())
    assert snaps["n_usable_puts"].iloc[0] == 3


@pytest.mark.parametrize(
    ("event_day", "expected"),
    [
        (date(2024, 1, 20), SnapshotStatus.SPLIT_IN_WINDOW),
        (SETTLE, SnapshotStatus.SPLIT_IN_WINDOW),
        (TRADE, SnapshotStatus.OK),
        (date(2024, 2, 5), SnapshotStatus.OK),
        (date(2024, 1, 4), SnapshotStatus.OK),
    ],
)
def test_split_window_is_after_trade_date_through_settlement(
    event_day: date, expected: SnapshotStatus
) -> None:
    daily = daily_frame([("SPY", event_day, -1.39), ("SPY", date(2024, 1, 10), 0.01)])
    assert _status(_chain(), _outcome(), daily) == expected


def test_split_of_another_underlying_does_not_matter() -> None:
    daily = daily_frame([("AAPL", date(2024, 1, 20), -1.39)])
    assert _status(_chain(), _outcome(), daily) == SnapshotStatus.OK


def test_split_events_use_the_absolute_threshold() -> None:
    daily = daily_frame(
        [
            ("A", date(2024, 1, 2), 0.39),
            ("A", date(2024, 1, 3), -0.41),
            ("A", date(2024, 1, 4), 0.7),
        ]
    )
    events = split_events(daily, threshold=0.4)
    assert events["trade_date"].tolist() == [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]


def test_reused_ticker_before_valid_from() -> None:
    quotes = _chain("META", date(2022, 6, 1), date(2022, 7, 1))
    outcomes = outcomes_frame([("META", date(2022, 7, 1), date(2022, 7, 1), 160.0)])
    assert _status(quotes, outcomes, _calm("META")) == SnapshotStatus.TICKER_REUSED
    later = _chain("META", date(2022, 6, 9), date(2022, 7, 1))
    assert _status(later, outcomes, _calm("META")) == SnapshotStatus.OK


def test_too_short_dte() -> None:
    quotes = _chain(expiry=date(2024, 1, 10))
    outcomes = outcomes_frame([("SPY", date(2024, 1, 10), date(2024, 1, 10), 100.0)])
    snaps = classify_snapshots(quotes, outcomes, _calm())
    assert snaps["dte_days"].iloc[0] == 5
    assert snaps["status"].iloc[0] == SnapshotStatus.TOO_SHORT


def test_dte_equal_to_minimum_is_kept() -> None:
    quotes = _chain(expiry=date(2024, 1, 12))
    outcomes = outcomes_frame([("SPY", date(2024, 1, 12), date(2024, 1, 12), 100.0)])
    assert _status(quotes, outcomes, _calm()) == SnapshotStatus.OK


def test_null_close_is_no_close() -> None:
    quotes = _chain()
    quotes["underlying_close"] = np.nan
    assert _status(quotes, _outcome(), _calm()) == SnapshotStatus.NO_CLOSE


def test_precedence_follows_the_documented_order() -> None:
    short = _chain("META", date(2022, 6, 1), date(2022, 6, 3))
    outcomes = outcomes_frame([("META", date(2022, 6, 3), date(2022, 6, 3), 160.0)])
    assert _status(short, outcomes, _calm("META")) == SnapshotStatus.TICKER_REUSED

    no_close = _chain(expiry=date(2024, 1, 10))
    no_close["underlying_close"] = np.nan
    assert _status(no_close, outcomes_frame([]), _calm()) == SnapshotStatus.TOO_SHORT

    few = _chain().loc[lambda f: f["strike"].isin([90.0, 91.0, 92.0])].copy()
    few["underlying_close"] = np.nan
    assert _status(few, _outcome(), _calm()) == SnapshotStatus.NO_CLOSE

    assert _status(few.assign(underlying_close=100.0), outcomes_frame([]), _calm()) == (
        SnapshotStatus.TOO_FEW_PUTS
    )

    split = daily_frame([("SPY", date(2024, 1, 20), -1.39)])
    assert _status(_chain(), outcomes_frame([]), split) == SnapshotStatus.UNSETTLED


def test_one_row_per_snapshot_sorted_by_key() -> None:
    quotes = pd.concat(
        [_chain("SPY"), _chain("AAPL"), _chain("SPY", date(2024, 1, 8))], ignore_index=True
    )
    outcomes = pd.concat([_outcome("SPY"), _outcome("AAPL")], ignore_index=True)
    snaps = classify_snapshots(quotes, outcomes, _calm())
    assert snaps[["underlying", "trade_date"]].astype(str).values.tolist() == [
        ["AAPL", "2024-01-05"],
        ["SPY", "2024-01-05"],
        ["SPY", "2024-01-08"],
    ]


def test_empty_quotes_give_empty_snapshots() -> None:
    empty = _chain().iloc[0:0]
    snaps = classify_snapshots(empty, _outcome(), _calm())
    assert snaps.empty
    assert tuple(snaps.columns) == SNAPSHOT_COLUMNS


def test_missing_column_raises() -> None:
    with pytest.raises(ValueError, match="quotes is missing"):
        classify_snapshots(_chain().drop(columns=["bid"]), _outcome(), _calm())


_QUOTE_VALUES = st.one_of(
    st.floats(-5.0, 50.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([float("nan"), float("inf"), float("-inf"), 0.0]),
)


@given(st.lists(st.tuples(_QUOTE_VALUES, _QUOTE_VALUES), min_size=1, max_size=40))
def test_usable_mask_matches_engine_usable_quotes(pairs: list[tuple[float, float]]) -> None:
    bid = pd.Series([p[0] for p in pairs])
    ask = pd.Series([p[1] for p in pairs])
    strikes = np.arange(1.0, len(pairs) + 1.0)
    mask = usable_mask(bid, ask)
    kept, mids = usable_quotes(strikes, bid, ask)
    assert kept.tolist() == strikes[mask.to_numpy()].tolist()
    expected_mids = 0.5 * (bid[mask] + ask[mask])
    np.testing.assert_allclose(mids, expected_mids.to_numpy())


def _predict(
    quotes: pd.DataFrame, outcomes: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    snaps = classify_snapshots(quotes, outcomes, _calm(), config)
    return build_predictions(quotes, snaps, config)


def _at(preds: pd.DataFrame, moneyness: float) -> pd.Series:
    rows = preds.loc[preds["moneyness"] == moneyness]
    assert len(rows) == 1
    return rows.iloc[0]


def test_labels_are_strict_at_the_target() -> None:
    preds = _predict(_chain(), _outcome(close=97.5))
    assert _at(preds, 0.975)["target_strike"] == 97.5
    assert not bool(_at(preds, 0.975)["realised"])
    assert bool(_at(preds, 1.0)["realised"])
    assert bool(_at(preds, 1.025)["realised"])
    assert not bool(_at(preds, 0.95)["realised"])


def test_target_rounding_makes_decimal_products_exact() -> None:
    preds = _predict(_chain(), _outcome(close=102.5))
    row = _at(preds, 1.025)
    assert row["target_strike"] == 102.5
    assert not bool(row["realised"])


def test_no_target_outside_the_cdf_knots() -> None:
    quotes = lognormal_quotes("SPY", TRADE, EXPIRY, 100.0, 0.25, RATE, np.arange(90.0, 111.0, 1.0))
    preds = _predict(quotes, _outcome())
    cdf = chain_cdf(quotes, years=28 / 365, rate=RATE)
    assert cdf is not None
    assert 0 < len(preds) < len(DEFAULT_CONFIG.moneyness_grid)
    assert preds["moneyness"].min() > DEFAULT_CONFIG.moneyness_grid[0]
    assert (preds["target_strike"] >= cdf.strikes[0]).all()
    assert (preds["target_strike"] <= cdf.strikes[-1]).all()
    assert preds["n_knots"].iloc[0] == len(cdf.strikes)


def test_prediction_matches_the_true_lognormal_cdf() -> None:
    vol = 0.25
    preds = _predict(_chain(vol=vol), _outcome())
    years = 28 / 365
    forward = 100.0 * (1.0 + RATE) ** years
    truth = lognormal_cdf(preds["target_strike"].to_numpy(), forward, vol, years)
    assert len(preds) >= 5
    np.testing.assert_allclose(preds["predicted_raw"].to_numpy(), truth, atol=0.015)
    assert preds["forward"].iloc[0] == pytest.approx(forward, rel=1e-3)


def test_fold_years_and_columns() -> None:
    quotes = pd.concat(
        [
            _chain(trade=date(2023, 12, 20), expiry=date(2024, 1, 19)),
            _chain(trade=date(2024, 1, 5)),
        ],
        ignore_index=True,
    )
    outcomes = pd.concat(
        [
            outcomes_frame([("SPY", date(2024, 1, 19), date(2024, 1, 19), 99.0)]),
            _outcome(),
        ],
        ignore_index=True,
    )
    preds = _predict(quotes, outcomes)
    assert tuple(preds.columns) == PREDICTION_COLUMNS
    assert (preds["fold"] == preds["trade_date"].dt.year).all()
    assert set(preds["fold"]) == {2023, 2024}
    np.testing.assert_allclose(preds["dte_years"], preds["dte_days"] / 365)
    assert preds["dte_bucket"].isin(["21-35d", "<=20d"]).all()
    assert (preds["settlement_date"] >= preds["expiration"].min()).all()
    keys = preds[["underlying", "trade_date", "expiration", "moneyness"]]
    assert not keys.duplicated().any()


def test_calls_remove_the_no_calls_flag() -> None:
    with_calls = _chain()
    puts_only = with_calls.loc[with_calls["option_right"] == "P"]
    one_call = pd.concat([puts_only, with_calls.loc[with_calls["option_right"] == "C"].iloc[:1]])
    years = 28 / 365
    full = chain_cdf(with_calls, years=years, rate=RATE)
    bare = chain_cdf(puts_only, years=years, rate=RATE)
    single = chain_cdf(one_call, years=years, rate=RATE)
    assert full is not None and bare is not None and single is not None
    assert QualityFlag.NO_CALLS not in full.flags
    assert QualityFlag.NO_CALLS in bare.flags
    assert QualityFlag.NO_CALLS in single.flags

    preds = _predict(with_calls, _outcome())
    assert "no_calls" not in preds["cdf_flags"].iloc[0].split(",")
    only = _predict(puts_only, _outcome())
    assert "no_calls" in only["cdf_flags"].iloc[0].split(",")
    flags = preds["cdf_flags"].iloc[0].split(",")
    assert flags == sorted(flags)


def test_chain_cdf_needs_four_usable_puts() -> None:
    chain = _chain()
    puts = chain.loc[(chain["option_right"] == "P") & chain["strike"].isin([95.0, 96.0, 97.0])]
    assert chain_cdf(puts, years=28 / 365, rate=RATE) is None


def test_non_ok_snapshots_yield_no_rows() -> None:
    quotes = _chain()
    snaps = classify_snapshots(quotes, outcomes_frame([]), _calm())
    assert snaps["status"].iloc[0] == SnapshotStatus.UNSETTLED
    preds = build_predictions(quotes, snaps)
    assert preds.empty
    assert tuple(preds.columns) == PREDICTION_COLUMNS


def test_only_ok_snapshots_are_predicted() -> None:
    quotes = pd.concat([_chain("SPY"), _chain("AAPL")], ignore_index=True)
    preds = _predict(quotes, _outcome("SPY"))
    assert set(preds["underlying"]) == {"SPY"}
