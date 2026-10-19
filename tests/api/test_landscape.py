from datetime import date

import numpy as np
import pandas as pd
import pytest

from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.sample import STRIKE_DECIMALS, chain_cdf
from oap.api.landscape import (
    HEATMAP_MONEYNESS,
    IDENTITY_MAP_ID,
    ChosenMap,
    MapMeta,
    SessionBundle,
    build_quotes_bundle,
    finite_or_none,
    named_map,
    pick_map,
    session_bundle,
    sessions_summary,
)
from oap.engine.calibration import CalibrationMap, apply_calibration
from oap.engine.conventions import dte_years
from tests.analytics.frames import lognormal_quotes, outcomes_frame
from tests.api.gold import (
    FAR_EXPIRY,
    LATEST,
    NEAR_EXPIRY,
    SESSIONS,
    SHORT_EXPIRY,
    THIN_EXPIRY,
    VOL,
    build_quotes,
    strikes_for,
)

RATE = DEFAULT_CONFIG.risk_free_apy
SESSION = SESSIONS[1]
TILT = CalibrationMap(
    np.array([0.0, 0.2, 0.5, 0.8, 1.0]),
    np.array([0.0, 0.1, 0.3, 0.7, 1.0]),
    n_samples=500,
    is_identity=False,
)
NO_OUTCOMES = outcomes_frame([])


def _session_quotes(symbol: str = "SPY", session: date = SESSION) -> pd.DataFrame:
    quotes = build_quotes()
    rows = quotes["underlying"] == symbol
    rows &= quotes["trade_date"] == pd.Timestamp(session)
    return quotes.loc[rows].reset_index(drop=True)


def _chosen(cmap: CalibrationMap = TILT, *, look_ahead: bool = False) -> ChosenMap:
    return ChosenMap("production", cmap, date(2024, 3, 6), look_ahead)


def _bundle(
    cmap: CalibrationMap = TILT,
    quotes: pd.DataFrame | None = None,
    outcomes: pd.DataFrame = NO_OUTCOMES,
) -> SessionBundle:
    frame = _session_quotes() if quotes is None else quotes
    return session_bundle("SPY", SESSION, frame, outcomes, _chosen(cmap))


def test_curve_is_the_backtests_cdf_at_the_raw_knots() -> None:
    quotes = _session_quotes()
    bundle = _bundle(quotes=quotes)
    chain = quotes.loc[quotes["expiration"] == pd.Timestamp(NEAR_EXPIRY)]
    cdf = chain_cdf(chain, years=dte_years(SESSION, NEAR_EXPIRY), rate=RATE)
    assert cdf is not None
    curve = bundle.curves[NEAR_EXPIRY].curve
    assert curve.knots == cdf.strikes.tolist()
    assert curve.cdf == cdf.cdf.tolist()
    assert curve.raw_cdf == cdf.raw_cdf.tolist()
    assert len(curve.knots) < 100


def test_calibrated_curve_is_apply_calibration_at_the_raw_knots() -> None:
    quotes = _session_quotes()
    bundle = _bundle(quotes=quotes)
    chain = quotes.loc[quotes["expiration"] == pd.Timestamp(NEAR_EXPIRY)]
    cdf = chain_cdf(chain, years=dte_years(SESSION, NEAR_EXPIRY), rate=RATE)
    assert cdf is not None
    expected = apply_calibration(cdf, TILT).prob_below_array(cdf.strikes)
    assert bundle.curves[NEAR_EXPIRY].curve.cdf_calibrated == expected.tolist()
    assert not np.allclose(expected, cdf.cdf)


def test_identity_map_leaves_the_calibrated_curve_equal_to_the_raw_one() -> None:
    curve = _bundle(CalibrationMap.identity()).curves[NEAR_EXPIRY].curve
    assert np.allclose(curve.cdf_calibrated, curve.cdf, atol=1e-12)
    assert np.allclose(curve.density_calibrated, curve.density, atol=1e-12)


def test_densities_are_per_dollar_between_the_knots() -> None:
    curve = _bundle().curves[NEAR_EXPIRY].curve
    knots = np.asarray(curve.knots)
    assert len(curve.density) == len(curve.density_mid) == len(knots) - 1
    assert np.allclose(curve.density_mid, knots[:-1] + np.diff(knots) / 2)
    assert float(np.sum(np.asarray(curve.density) * np.diff(knots))) == pytest.approx(
        curve.cdf[-1] - curve.cdf[0]
    )
    assert min(curve.density_calibrated) >= 0.0


def test_heatmap_is_null_outside_the_knots_and_the_cdf_inside() -> None:
    bundle = _bundle()
    curves = bundle.curves[NEAR_EXPIRY]
    row = next(r for r in bundle.heatmap.rows if r.expiration == NEAR_EXPIRY)
    knots = curves.cdf.strikes
    targets = np.round(np.asarray(HEATMAP_MONEYNESS) * curves.close, STRIKE_DECIMALS)
    assert row.target_strikes == targets.tolist()
    inside = (targets >= knots[0]) & (targets <= knots[-1])
    assert inside.any()
    assert row.prob_below == [
        float(p) if ok else None
        for p, ok in zip(curves.cdf.prob_below_array(targets), inside, strict=True)
    ]
    assert row.prob_below_calibrated == [
        float(p) if ok else None
        for p, ok in zip(curves.cal.prob_below_array(targets), inside, strict=True)
    ]
    assert bundle.heatmap.moneyness == list(HEATMAP_MONEYNESS)
    assert bundle.heatmap.backtest_grid == list(DEFAULT_CONFIG.moneyness_grid)


def test_heatmap_has_nulls_when_the_quoted_strikes_are_narrow() -> None:
    quotes = _session_quotes()
    narrow = quotes.loc[
        quotes["moneyness"].between(0.9, 1.1) | (quotes["expiration"] != pd.Timestamp(NEAR_EXPIRY))
    ]
    row = next(r for r in _bundle(quotes=narrow).heatmap.rows if r.expiration == NEAR_EXPIRY)
    assert row.prob_below[0] is None
    assert row.prob_below[-1] is None
    assert any(p is not None for p in row.prob_below)


def test_expiries_without_a_curve_say_why() -> None:
    by_expiry = {e.expiration: e for e in _bundle().distribution.expirations}
    thin = by_expiry[THIN_EXPIRY]
    assert thin.curve is None
    assert thin.unavailable_reason == "too_few_puts"
    assert thin.n_knots == 0
    assert THIN_EXPIRY not in _bundle().curves
    assert all(r.expiration != THIN_EXPIRY for r in _bundle().heatmap.rows)


def test_expired_and_missing_close_expiries_are_reported() -> None:
    quotes = _session_quotes()
    expired_day = lognormal_quotes(
        "SPY", SESSION, date(2024, 3, 6), 503.0, VOL, RATE, strikes_for(503.0)
    )
    expired = pd.concat([quotes, expired_day.assign(dte_days=0)], ignore_index=True)
    reasons = {
        e.expiration: e.unavailable_reason for e in _bundle(quotes=expired).distribution.expirations
    }
    assert reasons[date(2024, 3, 6)] == "expired"
    no_close = quotes.assign(
        underlying_close=np.where(
            quotes["expiration"] == pd.Timestamp(FAR_EXPIRY), np.nan, quotes["underlying_close"]
        )
    )
    reasons = {
        e.expiration: e.unavailable_reason
        for e in _bundle(quotes=no_close).distribution.expirations
    }
    assert reasons[FAR_EXPIRY] == "no_close"


def test_duplicate_strikes_are_an_engine_error() -> None:
    quotes = _session_quotes()
    duplicated = pd.concat([quotes, quotes.loc[quotes["expiration"] == pd.Timestamp(NEAR_EXPIRY)]])
    expiry = {e.expiration: e for e in _bundle(quotes=duplicated).distribution.expirations}[
        NEAR_EXPIRY
    ]
    assert expiry.curve is None
    assert expiry.unavailable_reason is not None
    assert expiry.unavailable_reason.startswith("engine_error: ")


def test_short_dated_expiries_are_shown_and_flagged() -> None:
    by_expiry = {e.expiration: e for e in _bundle().distribution.expirations}
    short = by_expiry[SHORT_EXPIRY]
    assert short.dte_days == 3
    assert short.short_dated is True
    assert short.curve is not None
    assert by_expiry[NEAR_EXPIRY].short_dated is False
    assert by_expiry[NEAR_EXPIRY].dte_days == 23


def test_a_nan_forward_becomes_none() -> None:
    assert finite_or_none(float("nan")) is None
    assert finite_or_none(float("inf")) is None
    assert finite_or_none(pd.NA) is None
    assert finite_or_none(np.float64(1.5)) == 1.5
    puts_only = _session_quotes()
    puts_only = puts_only.loc[puts_only["option_right"] == "P"]
    bundle = _bundle(quotes=puts_only)
    expiry = {e.expiration: e for e in bundle.distribution.expirations}[NEAR_EXPIRY]
    assert expiry.forward is None
    assert expiry.flags == ["forward_unknown", "no_calls"]
    assert expiry.curve is not None
    row = next(r for r in bundle.heatmap.rows if r.expiration == NEAR_EXPIRY)
    assert row.forward_moneyness is None
    assert np.isnan(bundle.curves[NEAR_EXPIRY].forward)


def test_settled_expiries_carry_the_probability_of_the_realised_close() -> None:
    outcomes = outcomes_frame([("SPY", SHORT_EXPIRY, SHORT_EXPIRY, 497.0)])
    bundle = _bundle(outcomes=outcomes)
    by_expiry = {e.expiration: e for e in bundle.distribution.expirations}
    settled = by_expiry[SHORT_EXPIRY]
    curves = bundle.curves[SHORT_EXPIRY]
    assert settled.settlement_date == SHORT_EXPIRY
    assert settled.settlement_close == 497.0
    assert settled.prob_below_settlement == pytest.approx(curves.cdf.prob_below(497.0))
    assert settled.prob_below_settlement_calibrated == pytest.approx(curves.cal.prob_below(497.0))
    open_expiry = by_expiry[NEAR_EXPIRY]
    assert open_expiry.settlement_date is None
    assert open_expiry.prob_below_settlement is None


@pytest.mark.parametrize("side", ["below", "above"])
def test_settlement_outside_the_quoted_strikes_has_no_probability(side: str) -> None:
    knots = _bundle().curves[SHORT_EXPIRY].cdf.strikes
    close = float(knots[0]) - 5.0 if side == "below" else float(knots[-1]) + 5.0
    outcomes = outcomes_frame([("SPY", SHORT_EXPIRY, SHORT_EXPIRY, close)])
    bundle = _bundle(outcomes=outcomes)
    settled = next(e for e in bundle.distribution.expirations if e.expiration == SHORT_EXPIRY)
    assert settled.settlement_close == close
    assert settled.prob_below_settlement is None
    assert settled.prob_below_settlement_calibrated is None


def test_settlement_at_the_edge_knots_keeps_the_probability() -> None:
    knots = _bundle().curves[SHORT_EXPIRY].cdf.strikes
    for close in (float(knots[0]), float(knots[-1])):
        outcomes = outcomes_frame([("SPY", SHORT_EXPIRY, SHORT_EXPIRY, close)])
        bundle = _bundle(outcomes=outcomes)
        settled = next(e for e in bundle.distribution.expirations if e.expiration == SHORT_EXPIRY)
        assert settled.prob_below_settlement is not None
        assert settled.prob_below_settlement_calibrated is not None


def test_distribution_reports_the_map() -> None:
    bundle = session_bundle(
        "SPY", SESSION, _session_quotes(), NO_OUTCOMES, _chosen(look_ahead=True)
    )
    dist = bundle.distribution
    assert dist.map_id == "production"
    assert dist.map_is_identity is False
    assert dist.look_ahead is True
    assert dist.risk_free_apy == RATE
    assert dist.map_train_max_expiration == date(2024, 3, 6)
    assert bundle.heatmap.map_id == "production"


def test_chain_groups_orders_and_marks_usable_quotes() -> None:
    chain = _bundle().chain
    assert [e.expiration for e in chain.expirations] == [
        SHORT_EXPIRY,
        NEAR_EXPIRY,
        FAR_EXPIRY,
        THIN_EXPIRY,
    ]
    assert chain.underlying_close == 503.0
    for expiry in chain.expirations:
        keys = [(q.strike, q.option_right) for q in expiry.quotes]
        assert keys == sorted(keys)
    near = next(e for e in chain.expirations if e.expiration == NEAR_EXPIRY)
    assert any(q.usable for q in near.quotes)
    deep_otm = [
        q
        for q in near.quotes
        if q.option_right == "P" and q.moneyness is not None and q.moneyness < 0.75
    ]
    assert deep_otm
    assert all(not q.usable for q in deep_otm)
    assert all(q.iv == VOL for q in near.quotes if q.iv is not None)


def test_atm_iv_is_the_nearest_otm_put_in_the_shortest_expiry_of_at_least_seven_days() -> None:
    rows = []
    for expiration, dte, strike, iv, right in (
        (date(2024, 3, 8), 3, 99.0, 0.50, "P"),
        (date(2024, 3, 22), 17, 97.0, 0.30, "P"),
        (date(2024, 3, 22), 17, 99.0, 0.25, "P"),
        (date(2024, 3, 22), 17, 99.5, 0.0, "P"),
        (date(2024, 3, 22), 17, 101.0, 0.20, "P"),
        (date(2024, 3, 22), 17, 99.0, 0.10, "C"),
        (date(2024, 4, 19), 45, 99.0, 0.40, "P"),
    ):
        rows.append(
            {
                "trade_date": pd.Timestamp(SESSION),
                "expiration": pd.Timestamp(expiration),
                "strike": strike,
                "option_right": right,
                "moneyness": strike / 100.0,
                "source_iv": iv,
                "dte_days": dte,
                "underlying_close": 100.0,
            }
        )
    (summary,) = sessions_summary(pd.DataFrame(rows))
    assert summary.atm_iv == 0.25
    assert summary.n_expirations == 3
    assert summary.n_quotes == 7
    assert summary.underlying_close == 100.0


def test_atm_iv_is_none_without_an_eligible_put() -> None:
    quotes = _session_quotes()
    calls = quotes.loc[quotes["option_right"] == "C"]
    (summary,) = sessions_summary(calls)
    assert summary.atm_iv is None


def test_quotes_bundle_slices_sessions() -> None:
    quotes = build_quotes()
    spy = quotes.loc[quotes["underlying"] == "SPY"].sample(frac=1.0, random_state=1)
    bundle = build_quotes_bundle(spy, NO_OUTCOMES)
    assert [s.session for s in bundle.sessions] == list(SESSIONS)
    for session in SESSIONS:
        rows = bundle.session_quotes(session)
        assert rows is not None
        assert set(rows["trade_date"]) == {pd.Timestamp(session)}
    assert bundle.session_quotes(date(2023, 1, 1)) is None


def _maps() -> tuple[dict[str, CalibrationMap], dict[str, MapMeta]]:
    maps = {
        "production": TILT,
        "fold_2024": CalibrationMap.identity(0),
        "fold_2020": CalibrationMap.identity(0),
    }
    meta = {
        "production": MapMeta(None, None, date(2024, 3, 5), 500),
        "fold_2024": MapMeta(2024, date(2024, 1, 1), date(2023, 12, 29), 0),
        "fold_2020": MapMeta(2020, date(2020, 1, 1), None, 0),
    }
    return maps, meta


def test_pick_map_auto_uses_production_for_the_latest_session_only() -> None:
    maps, meta = _maps()
    latest = pick_map("auto", LATEST, LATEST, maps, meta)
    assert latest.map_id == "production"
    assert latest.look_ahead is False
    earlier = pick_map("auto", SESSIONS[0], LATEST, maps, meta)
    assert earlier.map_id == "fold_2024"
    assert earlier.look_ahead is False
    assert earlier.cmap.is_identity


def test_pick_map_production_on_history_is_look_ahead() -> None:
    maps, meta = _maps()
    chosen = pick_map("production", SESSIONS[0], LATEST, maps, meta)
    assert chosen.map_id == "production"
    assert chosen.look_ahead is True
    assert chosen.train_max_expiration == date(2024, 3, 5)


def test_pick_map_walk_forward_falls_back_to_the_identity() -> None:
    maps, meta = _maps()
    chosen = pick_map("walk_forward", date(2031, 1, 2), LATEST, maps, meta)
    assert chosen.map_id == IDENTITY_MAP_ID
    assert chosen.cmap.is_identity
    assert chosen.look_ahead is False
    missing = pick_map("production", LATEST, LATEST, {}, {})
    assert missing.map_id == IDENTITY_MAP_ID


def test_named_map_returns_none_for_an_unknown_id() -> None:
    maps, meta = _maps()
    assert named_map("fold_1999", LATEST, maps, meta) is None
    found = named_map("production", SESSIONS[0], maps, meta)
    assert found is not None
    assert found.look_ahead is True
