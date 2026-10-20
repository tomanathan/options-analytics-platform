from datetime import date
from typing import get_args

import numpy as np
import pandas as pd
import pytest

from oap.analytics.views import (
    PRESETS,
    Preset,
    PresetId,
    pick_expiration,
    preset_by_id,
    resolve_preset,
    tail_sigmas,
)
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import RiskNeutralCdf
from oap.engine.positions import TailCompletedCdf

YEARS = 30 / 365


def _dist(m_lo: float = 0.05, m_hi: float = 0.05) -> TailCompletedCdf:
    strikes = np.array([85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0])
    cdf = np.array([m_lo, 0.17, 0.3, 0.5, 0.7, 0.83, 1.0 - m_hi])
    base = RiskNeutralCdf(strikes, cdf, cdf, 100.0, YEARS, 0.0, 7, frozenset())
    return TailCompletedCdf.complete(base, 0.4, 0.3)


def _chain(rows: list[tuple[float, str, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["strike", "option_right", "bid", "ask", "source_iv"])


def test_presets_match_the_spec_table() -> None:
    table = [(p.id, p.lo_q, p.hi_q, p.outside) for p in PRESETS]
    assert table == [
        ("up", 0.75, None, False),
        ("up_moderate", 0.55, 0.85, False),
        ("flat", 0.25, 0.75, False),
        ("down_moderate", 0.15, 0.45, False),
        ("down", None, 0.25, False),
        ("big_move", 0.10, 0.90, True),
    ]
    assert tuple(p.id for p in PRESETS) == get_args(PresetId)
    assert all(p.label for p in PRESETS)


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.id)
def test_resolved_presets_carry_their_quantile_probability(preset: Preset) -> None:
    dist = _dist()
    found = preset_by_id(preset.id)
    assert found == preset
    view = resolve_preset(found, dist)
    inside = (found.hi_q if found.hi_q is not None else 1.0) - (
        found.lo_q if found.lo_q is not None else 0.0
    )
    expected = 1.0 - inside if found.outside else inside
    assert dist.prob_view(view) == pytest.approx(expected, abs=1e-12)
    assert view.outside == found.outside
    assert (view.lo is None) == (found.lo_q is None)
    assert (view.hi is None) == (found.hi_q is None)


def test_a_preset_in_the_tail_uses_the_completed_tail() -> None:
    dist = _dist(0.15, 0.15)
    view = resolve_preset(preset_by_id("big_move"), dist)
    assert view.lo is not None and view.lo < dist.k_lo  # 10th percentile below the first knot
    assert view.hi is not None and view.hi > dist.k_hi


def test_unknown_preset() -> None:
    with pytest.raises(ValueError):
        preset_by_id("sideways")


def test_tail_sigmas_use_the_outermost_usable_quotes() -> None:
    chain = _chain(
        [
            (80.0, "P", 0.0, 0.1, 0.9),  # not usable: zero bid
            (85.0, "P", 0.2, 0.3, 0.45),
            (90.0, "P", 0.5, 0.6, 0.40),
            (100.0, "C", 2.0, 2.2, 0.30),
            (110.0, "C", 0.4, 0.5, 0.28),
            (115.0, "C", 0.1, 0.2, -1.0),  # usable, but no IV
        ]
    )
    assert tail_sigmas(chain) == (0.45, 0.28)


def test_tail_sigmas_fall_back_to_the_nearest_usable_quote_then_the_median() -> None:
    calls_only = _chain(
        [
            (90.0, "C", 10.0, 10.2, 0.35),
            (100.0, "C", 2.0, 2.2, 0.30),
            (110.0, "C", 0.4, 0.5, 0.27),
        ]
    )
    assert tail_sigmas(calls_only) == (0.35, 0.27)
    none_usable = _chain(
        [
            (90.0, "P", 0.0, 0.2, 0.5),
            (100.0, "C", 0.0, 0.2, 0.3),
            (110.0, "C", 0.0, 0.2, 0.2),
        ]
    )
    assert tail_sigmas(none_usable) == (0.3, 0.3)


def test_tail_sigmas_without_any_iv_raise() -> None:
    chain = _chain([(90.0, "P", 0.5, 0.6, 0.0), (100.0, "C", 2.0, 2.1, float("nan"))])
    with pytest.raises(EngineInputError):
        tail_sigmas(chain)


def test_pick_expiration() -> None:
    expirations = [
        (date(2026, 10, 23), 7),
        (date(2026, 11, 13), 28),
        (date(2026, 11, 27), 42),
        (date(2026, 12, 18), 63),
    ]
    assert pick_expiration(expirations, 35, 7) == date(2026, 11, 13)  # tie goes to the earlier
    assert pick_expiration(expirations, 40, 7) == date(2026, 11, 27)
    assert pick_expiration(expirations, 1, 7) == date(2026, 10, 23)
    assert pick_expiration(expirations, 1, 8) == date(2026, 11, 13)
    assert pick_expiration(expirations, 35, 90) is None
    assert pick_expiration([], 35, 7) is None
