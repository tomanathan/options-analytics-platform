from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.analytics.backtest import maps_from_frame, maps_to_frame, walk_forward_maps
from oap.analytics.config import DEFAULT_CONFIG, PRODUCTION_MAP_ID
from oap.analytics.scoring import SPREAD_COLUMNS, score_latest_session, score_session
from oap.analytics.strategy import (
    ELIGIBLE_ALL,
    EQUITY_COLUMNS,
    METRIC_COLUMNS,
    SETTLED_COLUMNS,
    TRADE_COLUMNS,
    backtest_session,
    equity_curve,
    leaking_trades,
    ok_quotes,
    select_session_entries,
    session_map,
    settle_trades,
    strategy_metrics,
    strategy_names,
)
from oap.engine.calibration import CalibrationMap
from tests.analytics.frames import lognormal_quotes, outcomes_frame, synthetic_predictions

RATE = DEFAULT_CONFIG.risk_free_apy
SPY_STRIKES = np.arange(80.0, 121.0, 1.0)
AAPL_STRIKES = np.arange(160.0, 221.0, 2.0)
ENTRY, BY_RETURN, _ = strategy_names(10)


def _tilt() -> CalibrationMap:
    """A fitted-looking map that lowers mid-range probabilities of finishing below a strike."""
    return CalibrationMap(
        np.array([0.0, 0.2, 0.5, 0.8, 1.0]),
        np.array([0.0, 0.1, 0.3, 0.7, 1.0]),
        n_samples=500,
        is_identity=False,
    )


def _session(trade_date: date = date(2024, 1, 5)) -> pd.DataFrame:
    """One session of two underlyings, expiries 28 and 49 days out (49 is in the entry band)."""
    return pd.concat(
        [
            lognormal_quotes(
                "SPY", trade_date, trade_date + timedelta(days=28), 100.0, 0.25, RATE, SPY_STRIKES
            ),
            lognormal_quotes(
                "SPY", trade_date, trade_date + timedelta(days=49), 100.0, 0.25, RATE, SPY_STRIKES
            ),
            lognormal_quotes(
                "AAPL", trade_date, trade_date + timedelta(days=28), 190.0, 0.3, RATE, AAPL_STRIKES
            ),
        ],
        ignore_index=True,
    )


def _ok_snapshots(quotes: pd.DataFrame) -> pd.DataFrame:
    snaps = quotes[["underlying", "trade_date", "expiration"]].drop_duplicates()
    return snaps.assign(status="ok").reset_index(drop=True)


# --- same path as the live ranking -----------------------------------------------------------


def test_selection_equals_the_live_entry_ranking_for_the_same_session_and_map() -> None:
    quotes, cmap = _session(), _tilt()
    live = score_latest_session(quotes, cmap, map_id="fold_2024")
    expected = live.loc[live["rank_entry"].notna() & (live["rank_entry"] <= 10)]
    expected = expected.sort_values("rank_entry").reset_index(drop=True)

    selected = select_session_entries(quotes, cmap, top_n=10, map_id="fold_2024")

    assert 0 < len(selected) <= 10
    pd.testing.assert_frame_equal(selected, expected)
    assert selected["rank_entry"].tolist() == list(range(1, len(selected) + 1))


def test_eligible_only_scoring_reproduces_every_eligible_row_and_rank() -> None:
    quotes, cmap = _session(), _tilt()
    full = score_session(quotes, cmap, map_id="x")
    fast = score_session(quotes, cmap, map_id="x", eligible_only=True)
    expected = full.loc[full["eligible"]].reset_index(drop=True)

    assert len(fast) < len(full)
    pd.testing.assert_frame_equal(fast, expected)


def test_top_n_none_returns_every_eligible_spread() -> None:
    quotes, cmap = _session(), _tilt()
    live = score_latest_session(quotes, cmap, map_id="m")
    everything = select_session_entries(quotes, cmap, top_n=None, map_id="m")
    assert set(everything["spread_key"]) == set(live.loc[live["eligible"], "spread_key"])
    assert everything["eligible"].all()


def test_select_rejects_quotes_of_several_sessions() -> None:
    quotes = pd.concat([_session(date(2024, 1, 5)), _session(date(2024, 1, 8))])
    with pytest.raises(ValueError, match="single trade_date"):
        select_session_entries(quotes, _tilt(), top_n=10, map_id="m")


def test_strategy_names_reject_a_non_positive_top() -> None:
    assert strategy_names(5) == ("entry_top5", "return_top5", ELIGIBLE_ALL)
    with pytest.raises(ValueError):
        strategy_names(0)


# --- one session of the backtest -------------------------------------------------------------


def test_backtest_session_selects_three_strategies_from_one_ranking() -> None:
    quotes = _session()
    maps = {"fold_2024": _tilt(), PRODUCTION_MAP_ID: CalibrationMap.identity(0)}
    trades = backtest_session(quotes, _ok_snapshots(quotes), maps, top_n=10)
    live = score_latest_session(quotes, _tilt(), map_id="fold_2024")

    assert tuple(trades.columns) == TRADE_COLUMNS
    assert (trades["map_id"] == "fold_2024").all()
    by = {name: g for name, g in trades.groupby("strategy")}
    assert set(by[ELIGIBLE_ALL]["spread_key"]) == set(live.loc[live["eligible"], "spread_key"])
    assert by[ENTRY]["rank_entry"].tolist() == list(range(1, len(by[ENTRY]) + 1))
    assert by[BY_RETURN]["rank"].tolist() == list(range(1, 11))
    assert by[BY_RETURN]["spread_key"].tolist() == (
        live.dropna(subset=["rank"]).sort_values("rank")["spread_key"].head(10).tolist()
    )
    assert trades["is_out_of_sample"].all()


def test_backtest_session_skips_snapshots_that_are_not_ok() -> None:
    quotes = _session()
    snaps = _ok_snapshots(quotes)
    snaps.loc[snaps["underlying"] == "AAPL", "status"] = "split_in_window"
    trades = backtest_session(quotes, snaps, {"fold_2024": _tilt()}, top_n=10)
    assert set(trades["underlying"]) == {"SPY"}
    assert len(ok_quotes(quotes, snaps)) == (quotes["underlying"] == "SPY").sum()


def test_backtest_session_without_a_fold_map_selects_nothing() -> None:
    quotes = _session()
    trades = backtest_session(quotes, _ok_snapshots(quotes), {PRODUCTION_MAP_ID: _tilt()}, top_n=10)
    assert trades.empty
    assert tuple(trades.columns) == TRADE_COLUMNS


def test_session_map_never_returns_the_production_map() -> None:
    maps = {"fold_2021": _tilt(), "fold_2020": CalibrationMap.identity(0), "production": _tilt()}
    assert session_map(maps, pd.Timestamp("2021-03-01")) == ("fold_2021", maps["fold_2021"], True)
    chosen = session_map(maps, pd.Timestamp("2020-03-01"))
    assert chosen is not None
    assert chosen[0] == "fold_2020"
    assert chosen[2] is False
    assert session_map(maps, pd.Timestamp("2022-03-01")) is None


# --- out of sample -----------------------------------------------------------------------------


def test_no_trade_uses_a_map_trained_on_expirations_at_or_after_its_trade_date() -> None:
    fitted = walk_forward_maps(synthetic_predictions([2020, 2021, 2022], 400))
    map_table = maps_to_frame(fitted)
    maps = maps_from_frame(map_table)
    sessions = [date(2020, 6, 1), date(2021, 1, 4), date(2021, 7, 1), date(2022, 1, 3)]
    parts = []
    for day in sessions:
        quotes = _session(day)
        parts.append(backtest_session(quotes, _ok_snapshots(quotes), maps, top_n=10))
    trades = pd.concat(parts, ignore_index=True)

    assert set(trades["trade_date"].dt.year) == {2020, 2021, 2022}
    for _, row in trades.iterrows():
        provenance = fitted[row["map_id"]]
        assert row["map_id"] == f"fold_{row['trade_date'].year}"
        if provenance.train_max_expiration is not None:
            assert provenance.train_max_expiration < row["trade_date"].date()
    assert not trades.loc[trades["trade_date"].dt.year == 2020, "is_out_of_sample"].any()
    assert trades.loc[trades["trade_date"].dt.year >= 2021, "is_out_of_sample"].all()
    assert leaking_trades(trades, map_table).empty


def test_the_leakage_check_flags_the_production_map() -> None:
    fitted = walk_forward_maps(synthetic_predictions([2020, 2021], 400))
    map_table = maps_to_frame(fitted)
    trades = pd.DataFrame(
        {
            "map_id": ["fold_2021", PRODUCTION_MAP_ID, "fold_2099"],
            "trade_date": pd.to_datetime(["2021-03-01", "2021-03-01", "2021-03-01"]),
        }
    )
    leaks = leaking_trades(trades, map_table)
    assert leaks["map_id"].tolist() == [PRODUCTION_MAP_ID, "fold_2099"]


# --- settlement ------------------------------------------------------------------------------


def _trade(**overrides: object) -> dict[str, object]:
    """A trade row with every ``TRADE_COLUMNS`` field; a 100/95 spread by default."""
    row: dict[str, object] = dict.fromkeys(SPREAD_COLUMNS, 0.0)
    row.update(
        {
            "spread_key": "SPY|2024-01-05|2024-02-02|100.000|95.000",
            "underlying": "SPY",
            "trade_date": pd.Timestamp("2024-01-05"),
            "expiration": pd.Timestamp("2024-02-02"),
            "dte_days": 28,
            "short_strike": 100.0,
            "long_strike": 95.0,
            "width": 5.0,
            "credit": 1.2,
            "credit_natural": 1.0,
            "max_loss": 3.8,
            "prob_profit": 0.8,
            "expected_roc": 0.05,
            "eligible": True,
            "map_id": "fold_2024",
            "strategy": ENTRY,
            "is_out_of_sample": True,
        }
    )
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("close", "payoff", "realised", "win", "max_loss_hit"),
    [
        (110.0, 1.0, 0.25, True, False),  # full win: keep the natural credit
        (99.5, 0.5, 0.125, True, False),  # partial: above breakeven at the natural credit
        (97.0, -2.0, -0.5, False, False),  # partial loss
        (95.0, -4.0, -1.0, False, True),  # at the long strike: max loss
        (80.0, -4.0, -1.0, False, True),  # far below: max loss
    ],
)
def test_settlement_uses_the_natural_credit_held_to_expiry(
    close: float, payoff: float, realised: float, win: bool, max_loss_hit: bool
) -> None:
    trades = pd.DataFrame([_trade()])
    outcomes = outcomes_frame([("SPY", date(2024, 2, 2), date(2024, 2, 2), close)])
    settled, dropped = settle_trades(trades, outcomes)
    row = settled.iloc[0]
    assert dropped == 0
    assert tuple(settled.columns) == SETTLED_COLUMNS
    assert row["max_loss_natural"] == pytest.approx(4.0)
    assert row["realised_payoff"] == pytest.approx(payoff)
    assert row["realised_return"] == pytest.approx(realised)
    assert bool(row["win"]) is win
    assert bool(row["max_loss_hit"]) is max_loss_hit
    assert row["settlement_close"] == close


def test_unsettled_trades_are_dropped_and_counted() -> None:
    trades = pd.DataFrame(
        [
            _trade(),
            _trade(expiration=pd.Timestamp("2024-03-15"), spread_key="b"),
            _trade(underlying="QQQ", spread_key="c"),
        ]
    )
    outcomes = outcomes_frame([("SPY", date(2024, 2, 2), date(2024, 2, 2), 110.0)])
    settled, dropped = settle_trades(trades, outcomes)
    assert dropped == 2
    assert settled["spread_key"].tolist() == ["SPY|2024-01-05|2024-02-02|100.000|95.000"]


@given(
    close=st.floats(0.01, 500.0),
    width=st.floats(0.5, 20.0),
    natural_share=st.floats(0.01, 0.99),
)
def test_realised_return_is_bounded_by_the_max_loss_and_the_credit(
    close: float, width: float, natural_share: float
) -> None:
    natural = natural_share * width
    trades = pd.DataFrame(
        [_trade(long_strike=100.0 - width, width=width, credit=natural, credit_natural=natural)]
    )
    outcomes = outcomes_frame([("SPY", date(2024, 2, 2), date(2024, 2, 2), close)])
    settled, _ = settle_trades(trades, outcomes)
    realised = float(settled["realised_return"].iloc[0])
    assert -1.0 - 1e-12 <= realised <= natural / (width - natural) + 1e-12
    assert bool(settled["win"].iloc[0]) == (float(settled["realised_payoff"].iloc[0]) > 0)


# --- metrics and equity ------------------------------------------------------------------------


def _settled(rows: list[tuple[str, str, str, float, bool]]) -> pd.DataFrame:
    """Settled trades from ``(strategy, trade_date, underlying, realised_return, oos)``.

    Each trade has a maximum loss of $2 per share, so its payoff is twice its return, a
    predicted POP of 0.8, a predicted return of 0.05 and 30 days to expiry.
    """
    frame = pd.DataFrame(
        [
            _trade(
                strategy=strategy,
                trade_date=pd.Timestamp(day),
                expiration=pd.Timestamp(day) + pd.Timedelta(days=30),
                underlying=underlying,
                spread_key=f"{strategy}{i}",
                dte_days=30,
                is_out_of_sample=oos,
            )
            for i, (strategy, day, underlying, _, oos) in enumerate(rows)
        ]
    )
    realised = np.array([r[3] for r in rows])
    frame["settlement_date"] = frame["expiration"]
    frame["settlement_close"] = 100.0
    frame["max_loss_natural"] = 2.0
    frame["realised_payoff"] = 2.0 * realised
    frame["realised_return"] = realised
    frame["win"] = realised > 0
    frame["max_loss_hit"] = realised <= -1.0
    return frame[list(SETTLED_COLUMNS)]


def _metric(
    metrics: pd.DataFrame, strategy: str, segment_type: str, segment: str, name: str
) -> pd.Series:
    row = metrics.loc[
        (metrics["strategy"] == strategy)
        & (metrics["segment_type"] == segment_type)
        & (metrics["segment"] == segment)
        & (metrics["metric"] == name)
    ]
    assert len(row) == 1
    return row.iloc[0]


def test_metrics_on_a_hand_made_trade_set() -> None:
    trades = _settled(
        [
            (ENTRY, "2021-01-04", "SPY", 0.25, True),
            (ENTRY, "2021-01-04", "AAPL", -1.0, True),
            (ENTRY, "2021-01-05", "SPY", 0.25, True),
            (ENTRY, "2022-01-03", "SPY", 0.5, True),
            (ENTRY, "2020-06-01", "SPY", -1.0, False),  # burn-in: ignored
        ]
    )
    metrics = strategy_metrics(trades)

    assert tuple(metrics.columns) == METRIC_COLUMNS
    overall = {
        name: _metric(metrics, ENTRY, "overall", "all", name)["value"]
        for name in metrics["metric"].unique()
    }
    assert overall["win_rate"] == pytest.approx(0.75)
    assert overall["mean_predicted_pop"] == pytest.approx(0.8)
    assert overall["pop_gap_realised"] == pytest.approx(-0.05)
    assert overall["mean_realised_return"] == pytest.approx(0.0)
    assert overall["median_realised_return"] == pytest.approx(0.25)
    assert overall["worst_trade_return"] == pytest.approx(-1.0)
    assert overall["total_return"] == pytest.approx(0.0)
    assert overall["max_loss_rate"] == pytest.approx(0.25)
    assert overall["avg_dte_days"] == pytest.approx(30.0)
    # $1 per trade by session: -0.75, -0.5, 0.0, so the curve never regains its 0 start.
    assert overall["max_drawdown"] == pytest.approx(0.75)
    # $1 per session: mean -0.375, then 0.25, 0.5 gives -0.375, -0.125, 0.375.
    assert overall["max_drawdown_session"] == pytest.approx(0.375)
    assert overall["sharpe_per_trade"] == pytest.approx(0.0)
    low, high = overall["win_rate_ci_low"], overall["win_rate_ci_high"]
    assert 0.0 <= low <= 0.75 <= high <= 1.0
    counts = _metric(metrics, ENTRY, "overall", "all", "win_rate")
    assert (counts["n_trades"], counts["n_sessions"]) == (4, 3)
    assert _metric(metrics, ENTRY, "year", "2021", "win_rate")["value"] == pytest.approx(2 / 3)
    assert _metric(metrics, ENTRY, "underlying", "AAPL", "max_loss_rate")["value"] == 1.0
    assert _metric(metrics, ENTRY, "dte_bucket", "21-35d", "win_rate")["n_trades"] == 4
    assert "2020" not in set(metrics["segment"])


def test_metrics_order_the_strategies_and_skip_in_sample_rows() -> None:
    trades = _settled(
        [
            (ELIGIBLE_ALL, "2021-01-04", "SPY", 0.1, True),
            (BY_RETURN, "2021-01-04", "SPY", 0.1, True),
            (ENTRY, "2021-01-04", "SPY", 0.1, True),
            ("other", "2021-01-04", "SPY", 0.1, False),
        ]
    )
    metrics = strategy_metrics(trades)
    assert list(dict.fromkeys(metrics["strategy"])) == [ENTRY, BY_RETURN, ELIGIBLE_ALL]
    assert np.isnan(_metric(metrics, ENTRY, "overall", "all", "sharpe_per_trade")["value"])


def test_metrics_are_empty_without_out_of_sample_trades() -> None:
    trades = _settled([(ENTRY, "2020-06-01", "SPY", 0.1, False)])
    metrics = strategy_metrics(trades)
    assert metrics.empty
    assert tuple(metrics.columns) == METRIC_COLUMNS


def test_equity_curve_is_the_cumulative_sum_of_session_returns() -> None:
    trades = _settled(
        [
            (ENTRY, "2021-01-05", "SPY", 0.25, True),
            (ENTRY, "2021-01-04", "SPY", 0.25, True),
            (ENTRY, "2021-01-04", "AAPL", -1.0, True),
            (ENTRY, "2021-01-06", "SPY", 0.5, True),
            (ELIGIBLE_ALL, "2021-01-04", "SPY", 0.2, True),
        ]
    )
    curve = equity_curve(trades)
    entry = curve.loc[curve["strategy"] == ENTRY]

    assert tuple(curve.columns) == EQUITY_COLUMNS
    assert entry["trade_date"].is_monotonic_increasing
    np.testing.assert_allclose(entry["cumulative_return"], [-0.75, -0.5, 0.0])
    np.testing.assert_allclose(entry["drawdown"], [0.75, 0.5, 0.0])
    per_session = equity_curve(trades, basis="session")
    np.testing.assert_allclose(
        per_session.loc[per_session["strategy"] == ENTRY, "cumulative_return"],
        [-0.375, -0.125, 0.375],
    )
    assert (curve["drawdown"] >= 0).all()
