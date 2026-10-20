import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from oap.analytics.sample import usable_mask
from oap.analytics.views import PRESETS
from oap.api.errors import NotFound, Unprocessable
from oap.api.landscape import ChosenMap, ExpiryCurves, expiry_curves, session_bundle
from oap.api.structures import (
    GRID_POINTS,
    StructureBook,
    StructuresQuery,
    build_book,
    chain_sides,
    choose_expiration,
    outcome_map,
    resolve_view,
    structures_response,
)
from oap.engine.calibration import CalibrationMap
from oap.engine.positions import EVERYTHING, StructureKind, score_structures
from tests.analytics.frames import outcomes_frame
from tests.api.gold import (
    FAR_EXPIRY,
    LATEST,
    NEAR_EXPIRY,
    SHORT_EXPIRY,
    THIN_EXPIRY,
    GoldFixture,
    build_quotes,
)


def _chosen(gold: GoldFixture) -> ChosenMap:
    return ChosenMap("production", gold.production, None, False)


def _session(symbol: str = "SPY", session: date = LATEST) -> pd.DataFrame:
    quotes = build_quotes()
    rows = (quotes["underlying"] == symbol) & (quotes["trade_date"] == pd.Timestamp(session))
    return quotes.loc[rows].reset_index(drop=True)


def _chain(expiration: date, symbol: str = "SPY") -> pd.DataFrame:
    quotes = _session(symbol)
    return quotes.loc[quotes["expiration"] == pd.Timestamp(expiration)].reset_index(drop=True)


def _curves(gold: GoldFixture, expiration: date = FAR_EXPIRY, symbol: str = "SPY") -> ExpiryCurves:
    found, reason = expiry_curves(_chain(expiration, symbol), LATEST, expiration, _chosen(gold))
    assert found is not None, reason
    return found


def _book(gold: GoldFixture, fill: str = "natural", symbol: str = "SPY") -> StructureBook:
    chain = _chain(FAR_EXPIRY, symbol)
    dte = int(chain["dte_days"].iloc[0])
    return build_book(symbol, LATEST, dte, chain, _curves(gold, symbol=symbol), fill)  # type: ignore[arg-type]


def test_expiry_curves_are_the_landscape_curves(gold: GoldFixture) -> None:
    bundle = session_bundle("SPY", LATEST, _session(), outcomes_frame([]), _chosen(gold))
    found = _curves(gold)
    landscape = bundle.curves[FAR_EXPIRY]
    assert np.array_equal(found.cdf.strikes, landscape.cdf.strikes)
    assert np.array_equal(found.cal.cdf, landscape.cal.cdf)
    assert found.curve == landscape.curve


def test_chain_sides_keep_usable_quotes_sorted() -> None:
    chain = _chain(FAR_EXPIRY)
    chain.loc[0, "bid"] = 0.0
    shuffled = chain.sample(frac=1.0, random_state=7)
    calls, puts = chain_sides(shuffled)
    assert np.all(np.diff(calls.strikes) > 0)
    assert np.all(np.diff(puts.strikes) > 0)
    assert np.all(calls.bids > 0) and np.all(puts.bids > 0)
    usable = usable_mask(chain["bid"], chain["ask"])
    n_calls = int((usable & (chain["option_right"] == "C")).sum())
    n_puts = int((usable & (chain["option_right"] == "P")).sum())
    assert (calls.strikes.shape[0], puts.strikes.shape[0]) == (n_calls, n_puts)
    assert chain.loc[0, "strike"] not in (
        calls.strikes if chain.loc[0, "option_right"] == "C" else puts.strikes
    )


def test_build_book(gold: GoldFixture) -> None:
    book = _book(gold)
    assert book.expiration == FAR_EXPIRY
    assert book.dist.sigma_lo == pytest.approx(0.30)
    assert book.dist.sigma_hi == pytest.approx(0.30)
    assert book.dist.base is book.curves.cal
    assert book.market.base is book.curves.cdf
    kinds = {p.kind for p in book.positions}
    assert {
        StructureKind.LONG_CALL,
        StructureKind.BULL_PUT_SPREAD,
        StructureKind.IRON_CONDOR,
    } <= kinds
    lo, hi = book.curves.cdf.strikes[0], book.curves.cdf.strikes[-1]
    assert all(lo <= k <= hi for p in book.positions for k in p.kinks)


def test_build_book_without_implied_vol(gold: GoldFixture) -> None:
    chain = _chain(FAR_EXPIRY)
    chain["source_iv"] = np.nan
    with pytest.raises(Unprocessable) as caught:
        build_book("SPY", LATEST, 44, chain, _curves(gold), "natural")
    assert caught.value.code == "no_implied_vol"


def test_bull_put_spreads_on_mid_fills_match_the_gold_scores(gold: GoldFixture) -> None:
    book = _book(gold, "mid")
    puts = [p for p in book.positions if p.kind == StructureKind.BULL_PUT_SPREAD]
    scores = {
        (s.position.kinks[1], s.position.kinks[0]): s
        for s in score_structures(puts, book.dist, EVERYTHING)
    }
    rows = gold.scores.loc[
        (gold.scores["underlying"] == "SPY")
        & (pd.to_datetime(gold.scores["expiration"]) == pd.Timestamp(FAR_EXPIRY))
    ]
    compared = 0
    for row in rows.to_dict("records"):
        score = scores.get((float(row["short_strike"]), float(row["long_strike"])))
        if score is None:
            continue
        compared += 1
        expected_return = float(row["expected_payoff"]) / float(row["max_loss"])
        assert score.position.max_loss == pytest.approx(float(row["max_loss"]), abs=1e-9)
        assert score.expected_return == pytest.approx(expected_return, abs=1e-9)
        assert score.prob_profit == pytest.approx(float(row["prob_profit"]), abs=1e-9)
        assert score.pnl_std == pytest.approx(float(row["payoff_std"]), abs=1e-9)
        interest = float(row["interest"]) / float(row["max_loss"])
        assert float(row["expected_roc"]) == pytest.approx(
            score.expected_return + interest, abs=1e-9
        )
    assert compared >= 10


def test_choose_expiration(gold: GoldFixture) -> None:
    bundle = session_bundle("SPY", LATEST, _session(), outcomes_frame([]), _chosen(gold))
    distribution = bundle.distribution
    assert choose_expiration(distribution, None) == (FAR_EXPIRY, (FAR_EXPIRY - LATEST).days)
    assert choose_expiration(distribution, NEAR_EXPIRY)[0] == NEAR_EXPIRY
    assert choose_expiration(distribution, SHORT_EXPIRY)[0] == SHORT_EXPIRY
    with pytest.raises(Unprocessable) as caught:
        choose_expiration(distribution, THIN_EXPIRY)
    assert caught.value.code == "no_distribution"
    assert "too_few_puts" in caught.value.detail
    with pytest.raises(NotFound):
        choose_expiration(distribution, date(2024, 5, 17))
    no_curves = distribution.model_copy(
        update={"expirations": [e for e in distribution.expirations if e.curve is None]}
    )
    with pytest.raises(Unprocessable) as empty:
        choose_expiration(no_curves, None)
    assert empty.value.code == "no_distribution"


def test_resolve_view(gold: GoldFixture) -> None:
    book = _book(gold)
    close = book.curves.close
    view, preset = resolve_view(StructuresQuery(preset="flat", lo=2.0), book.dist, close)
    assert preset == "flat"
    assert book.dist.prob_view(view) == pytest.approx(0.5, abs=1e-12)
    custom, none = resolve_view(StructuresQuery(lo=0.95, hi=1.05, outside=True), book.dist, close)
    assert none is None
    assert (custom.lo, custom.hi, custom.outside) == (0.95 * close, 1.05 * close, True)
    with pytest.raises(Unprocessable) as required:
        resolve_view(StructuresQuery(), book.dist, close)
    assert required.value.code == "view_required"
    with pytest.raises(Unprocessable) as invalid:
        resolve_view(StructuresQuery(lo=1.1, hi=1.1), book.dist, close)
    assert invalid.value.code == "view_invalid"


def test_structures_response_is_consistent(gold: GoldFixture) -> None:
    book = _book(gold)
    query = StructuresQuery(preset="up_moderate", limit=10)
    view, preset = resolve_view(query, book.dist, book.curves.close)
    body = structures_response(book, view, preset, query, _chosen(gold))
    assert len(body.grid) == len(body.density) == GRID_POINTS
    assert body.view.prob == pytest.approx(0.30, abs=1e-9)
    order = list(StructureKind)
    kinds = [StructureKind(k.kind) for k in body.kinds]
    assert kinds == sorted(kinds, key=order.index)
    for row in body.kinds:
        assert len(row.curve) == GRID_POINTS
        assert row.prob_profit_given_view is not None and row.prob_profit_given_view >= 0.5
        assert min(row.curve) >= -1.0 - 1e-12
    assert len(body.ranking) == min(10, body.n_qualifying)
    returns = [r.return_if_right for r in body.ranking]
    assert all(r is not None for r in returns)
    assert returns == sorted(returns, reverse=True)  # type: ignore[type-var]
    best = {k.kind: k for k in body.kinds}
    verdict = body.verdict
    assert verdict.best_kind is not None
    assert best[verdict.best_kind].return_if_right == max(
        k.return_if_right for k in body.kinds if k.return_if_right is not None
    )
    if verdict.spread_kind and verdict.single_kind:
        assert verdict.advantage == pytest.approx(
            best[verdict.spread_kind].return_if_right - best[verdict.single_kind].return_if_right  # type: ignore[operator]
        )
    segments = body.dominance
    assert segments[0].from_ == body.grid[0] and segments[-1].to == body.grid[-1]
    for left, right in zip(segments[:-1], segments[1:], strict=True):
        assert left.to == right.from_
    dumped = body.model_dump(mode="json", by_alias=True)
    assert set(dumped["dominance"][0]) == {"from", "to", "kind"}
    assert body.tails.mass_lo == pytest.approx(book.dist.tail_mass()[0])


def test_outcome_map(gold: GoldFixture) -> None:
    quotes = build_quotes()
    session = quotes.loc[quotes["trade_date"] == pd.Timestamp(LATEST)].reset_index(drop=True)
    body = outcome_map(LATEST, session, _chosen(gold), target_dte=35, fill="mid", min_pop_given=0.5)
    assert [r.symbol for r in body.rows] == ["SPY", "XLF"]
    assert [p.id for p in body.presets] == [p.id for p in PRESETS]
    for row in body.rows:
        assert row.expiration == FAR_EXPIRY
        assert row.unavailable_reason is None
        assert [c.preset for c in row.cells] == [p.id for p in PRESETS]
        probs = {c.preset: c.prob for c in row.cells}
        assert probs["up"] == pytest.approx(0.25, abs=1e-9)
        assert probs["big_move"] == pytest.approx(0.20, abs=1e-9)
        for cell in row.cells:
            if cell.spread_return_if_right is not None and cell.single_return_if_right is not None:
                assert cell.advantage == pytest.approx(
                    cell.spread_return_if_right - cell.single_return_if_right
                )
            assert (cell.best_kind is None) == (cell.best_legs is None)
    near = outcome_map(LATEST, session, _chosen(gold), target_dte=7, fill="mid", min_pop_given=0.5)
    assert {r.expiration for r in near.rows} == {NEAR_EXPIRY}


def test_outcome_map_lists_a_ticker_without_a_usable_expiration(gold: GoldFixture) -> None:
    quotes = build_quotes()
    session = quotes.loc[quotes["trade_date"] == pd.Timestamp(LATEST)]
    spy_short = session.loc[
        (session["underlying"] != "SPY")
        | (session["expiration"].isin([pd.Timestamp(SHORT_EXPIRY), pd.Timestamp(THIN_EXPIRY)]))
    ].reset_index(drop=True)
    no_iv = spy_short.copy()
    no_iv.loc[no_iv["underlying"] == "XLF", "source_iv"] = np.nan
    body = outcome_map(
        LATEST, no_iv, _chosen(gold), target_dte=35, fill="natural", min_pop_given=0.5
    )
    spy, xlf = body.rows
    assert spy.cells == [] and spy.expiration is None
    assert spy.unavailable_reason is not None and spy.unavailable_reason.startswith(
        "no_distribution"
    )
    assert xlf.cells == [] and xlf.expiration == FAR_EXPIRY
    assert xlf.unavailable_reason is not None and xlf.unavailable_reason.startswith(
        "no_implied_vol"
    )


def test_identity_map_scores_like_the_raw_distribution(gold: GoldFixture) -> None:
    chosen = ChosenMap("identity", CalibrationMap.identity(), None, False)
    chain = _chain(FAR_EXPIRY)
    found, _ = expiry_curves(chain, LATEST, FAR_EXPIRY, chosen)
    assert found is not None
    book = build_book("SPY", LATEST, 44, chain, found, "mid")
    query = StructuresQuery(preset="up")
    view, preset = resolve_view(query, book.dist, found.close)
    body = structures_response(book, view, preset, query, chosen)
    assert body.view.prob == pytest.approx(body.view.prob_market, abs=1e-9)
    assert body.map_is_identity
    assert not math.isnan(body.view.prob)


def test_response_density_is_the_landscape_density_and_integrates_to_about_one(
    gold: GoldFixture,
) -> None:
    book = _book(gold)
    query = StructuresQuery(preset="flat")
    view, preset = resolve_view(query, book.dist, book.curves.close)
    body = structures_response(book, view, preset, query, _chosen(gold))
    grid = np.asarray(body.grid)
    density = np.asarray(body.density)
    assert np.trapezoid(density, grid) == pytest.approx(0.99, abs=0.03)
    knots = np.asarray(book.curves.curve.knots)
    landscape = np.asarray(book.curves.curve.density_calibrated)
    inside = (grid >= knots[0]) & (grid < knots[-1])
    index = np.searchsorted(knots, grid[inside], side="right") - 1
    assert np.allclose(density[inside], landscape[index], rtol=1e-12, atol=1e-15)
    assert density.max() < 10 * np.max(landscape)
