import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.analytics.config import RANK_BYS
from oap.analytics.ranking import (
    POP_SHRINK,
    RANK_WORDS,
    annualise,
    band_mask,
    floats,
    natural_odds,
    rank_score,
    shrunk_pop,
)


def _spreads() -> pd.DataFrame:
    """Two spreads: 5 wide with a 1.00 natural credit, and 2 wide with a 0.50 natural credit."""
    return pd.DataFrame(
        {
            "credit_natural": [1.0, 0.5],
            "width": [5.0, 2.0],
            "prob_profit": [0.8, 0.7],
            "pop_implied": [0.76, 0.70],
            "years": [49 / 365, 28 / 365],
            "edge_natural": [0.2, -0.05],
            "kelly_fraction": [0.2, 0.0],
            "annualised_roc": [0.5, math.inf],
            "reward_to_risk": [0.1, math.nan],
        }
    )


def test_every_ranking_has_words() -> None:
    assert set(RANK_WORDS) == set(RANK_BYS)


def test_natural_odds_and_shrunk_pop_on_hand_values() -> None:
    frame = _spreads()
    np.testing.assert_allclose(natural_odds(frame), [0.25, 1 / 3])
    np.testing.assert_allclose(
        shrunk_pop(np.array([0.8, 0.7]), np.array([0.76, 0.70])), [0.78, 0.70]
    )
    assert POP_SHRINK == 0.5


def test_the_shrunk_pop_return_is_the_annualised_two_outcome_natural_return() -> None:
    frame = _spreads()
    q = np.array([0.78, 0.70])
    b = np.array([0.25, 1 / 3])
    years = frame["years"].to_numpy()
    expected = (1 + q * b - (1 - q)) ** (1 / years) - 1
    np.testing.assert_allclose(rank_score(frame, "pop_shrunk_return"), expected)
    np.testing.assert_allclose(
        rank_score(frame, "return_natural"), annualise(np.array([0.05, -0.05 / 1.5]), years)
    )
    assert rank_score(frame, "return_mid").tolist()[0] == 0.5
    assert math.isinf(rank_score(frame, "return_mid")[1])
    assert math.isnan(rank_score(frame, "reward_to_risk")[1])


@given(
    r=st.floats(-0.9, 1.0),
    years=st.floats(7 / 365, 2.0),
)
def test_annualise_compounds_back_to_the_holding_period_return(r: float, years: float) -> None:
    yearly = annualise(np.array([r]), np.array([years]))[0]
    if math.isfinite(yearly) and 1 + yearly > 1e-3:  # far from the floor of -1
        assert (1 + yearly) ** years - 1 == pytest.approx(r, rel=1e-6, abs=1e-9)


def test_annualise_floors_a_total_loss_at_minus_one() -> None:
    assert annualise(np.array([-1.0, -3.0]), np.array([0.2, 0.2])).tolist() == [-1.0, -1.0]


def test_band_mask_is_half_open_and_none_keeps_everything() -> None:
    values = np.array([44.0, 45.0, 69.0, 70.0, math.nan])
    assert band_mask(values, (45, 70)).tolist() == [False, True, True, False, False]
    assert band_mask(values, None).tolist() == [True] * 5


def test_floats_turns_nulls_into_nan() -> None:
    frame = pd.DataFrame({"rank": pd.array([1, None], dtype="Int64")})
    got = floats(frame, "rank")
    assert got[0] == 1.0
    assert math.isnan(got[1])
