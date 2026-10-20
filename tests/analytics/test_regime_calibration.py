import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oap.analytics.backtest import (
    cluster_bootstrap_ci,
    maps_from_frame,
    walk_forward_maps,
)
from oap.analytics.config import DEFAULT_CONFIG, AnalyticsConfig
from oap.analytics.regime_calibration import (
    COMPARISON_COLUMNS,
    PAIRED_COLUMNS,
    POOLED,
    REGIME_LABELS,
    REGIME_MAP_COLUMNS,
    REGIMES,
    UNKNOWN,
    apply_regime_maps,
    attach_regime,
    bin_index,
    cluster_bootstrap_ece_difference,
    compare_metrics,
    decide,
    ece,
    iv_rank_bucket,
    log_loss_terms,
    paired_sample,
    regime_map_id,
    regime_map_summary,
    regime_maps_to_frame,
    regime_of,
    reliability_frame,
    trend_bucket,
    walk_forward_regime_maps,
)
from oap.engine.calibration import expected_calibration_error, log_loss
from tests.analytics.frames import synthetic_predictions

YEARS = [2020, 2021, 2022]


def _features(predictions: pd.DataFrame, labels: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """One feature row per underlying and trade date, with fixed (iv_rank, ret_20) per symbol."""
    keys = predictions[["underlying", "trade_date"]].drop_duplicates()
    rank = keys["underlying"].map(lambda u: labels[u][0])
    ret = keys["underlying"].map(lambda u: labels[u][1])
    return keys.assign(iv_rank_120=rank.astype(float), ret_20=ret.astype(float)).reset_index(
        drop=True
    )


def test_buckets_follow_the_edges() -> None:
    ranks = iv_rank_bucket([0.0, 1 / 3 - 1e-12, 1 / 3, 0.5, 2 / 3 - 1e-12, 2 / 3, 1.0, math.nan])
    assert list(ranks) == ["low", "low", "mid", "mid", "mid", "high", "high", UNKNOWN]
    trends = trend_bucket([-0.1, 0.0, 1e-12, math.nan])
    assert list(trends) == ["down", "down", "up", UNKNOWN]


def test_regime_of_pairs_the_buckets_and_marks_missing_as_unknown() -> None:
    features = pd.DataFrame(
        {
            "iv_rank_120": [0.1, 0.5, 0.9, math.nan, 0.9],
            "ret_20": [0.01, -0.02, 0.0, 0.1, math.nan],
        },
        index=[10, 11, 12, 13, 14],
    )
    labels = regime_of(features)
    assert list(labels.index) == [10, 11, 12, 13, 14]
    assert list(labels) == ["low_up", "mid_down", "high_down", UNKNOWN, UNKNOWN]
    assert set(REGIMES) == {f"{a}_{b}" for a in ("low", "mid", "high") for b in ("down", "up")}


def test_attach_regime_keeps_order_and_fills_unknown() -> None:
    frame = pd.DataFrame(
        {
            "underlying": ["B", "A", "C"],
            "trade_date": pd.to_datetime(["2021-01-05", "2021-01-04", "2021-01-04"]),
            "x": [1, 2, 3],
        },
        index=[7, 8, 9],
    )
    features = pd.DataFrame(
        {
            "underlying": ["A", "B", "B"],
            "trade_date": pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-05"]),
            "iv_rank_120": [0.9, 0.1, 0.5],
            "ret_20": [0.1, -0.1, 0.1],
        }
    )
    out = attach_regime(frame, features)
    assert list(out.index) == [7, 8, 9]
    assert list(out["regime"]) == ["low_down", "high_up", UNKNOWN]
    assert list(out["x"]) == [1, 2, 3]


def test_thin_regimes_and_unknown_fall_back_to_the_pooled_map() -> None:
    predictions = synthetic_predictions(YEARS, 400)
    features = _features(predictions, {"AAA": (0.9, 0.05), "BBB": (0.1, -0.05)})
    config = AnalyticsConfig(min_fit_samples=150)
    maps = walk_forward_regime_maps(predictions, features, config)
    assert set(maps.by_regime) == {regime_map_id(y, r) for y in YEARS for r in REGIME_LABELS}
    for year in YEARS:
        pooled = maps.pooled[f"fold_{year}"].cmap
        for regime in REGIME_LABELS:
            map_id = regime_map_id(year, regime)
            fitted = maps.by_regime[map_id]
            assert fitted.fold == year
            if regime not in ("high_up", "low_down") or maps.n_train[map_id] < 150:
                assert maps.fallback[map_id]
                assert fitted.cmap is pooled
            else:
                assert not maps.fallback[map_id]
                assert fitted.cmap.n_samples == maps.n_train[map_id]
            if fitted.train_max_expiration is not None and fitted.train_cutoff is not None:
                assert fitted.train_max_expiration < fitted.train_cutoff
    assert maps.fallback[regime_map_id(2020, "high_up")]  # nothing expired before 2020
    assert not maps.fallback[regime_map_id(2022, "high_up")]
    assert maps.fallback[regime_map_id(2022, UNKNOWN)]
    counts = predictions.loc[predictions["expiration"] < pd.Timestamp(date(2022, 1, 1))]
    assert maps.n_train[regime_map_id(2022, "high_up")] == int(
        (counts["underlying"] == "AAA").sum()
    )


def test_regime_maps_fit_their_own_rows() -> None:
    predictions = synthetic_predictions(YEARS, 600)
    # AAA's outcomes all occur, BBB's never: the two regime maps must split apart.
    predictions["realised"] = predictions["underlying"] == "AAA"
    features = _features(predictions, {"AAA": (0.9, 0.05), "BBB": (0.1, -0.05)})
    maps = walk_forward_regime_maps(predictions, features)
    high = maps.by_regime[regime_map_id(2022, "high_up")].cmap
    low = maps.by_regime[regime_map_id(2022, "low_down")].cmap
    assert high.apply(0.5) == pytest.approx(1.0)
    assert low.apply(0.5) == pytest.approx(0.0)
    pooled = maps.pooled["fold_2022"].cmap
    assert 0.0 < pooled.apply(0.5) < 1.0


def test_pooled_maps_equal_walk_forward_maps() -> None:
    predictions = synthetic_predictions(YEARS, 300)
    features = _features(predictions, {"AAA": (0.5, 0.05), "BBB": (0.5, 0.05)})
    maps = walk_forward_regime_maps(predictions, features)
    reference = walk_forward_maps(predictions)
    assert set(maps.pooled) == {f"fold_{y}" for y in YEARS}
    for map_id, fitted in maps.pooled.items():
        np.testing.assert_array_equal(fitted.cmap.knots, reference[map_id].cmap.knots)
        np.testing.assert_array_equal(fitted.cmap.values, reference[map_id].cmap.values)


def test_the_map_table_round_trips_with_regime_columns() -> None:
    predictions = synthetic_predictions(YEARS, 300)
    features = _features(predictions, {"AAA": (0.9, 0.05), "BBB": (0.1, -0.05)})
    maps = walk_forward_regime_maps(predictions, features)
    table = regime_maps_to_frame(maps)
    assert list(table.columns) == list(REGIME_MAP_COLUMNS)
    assert set(table.loc[table["map_id"].str.fullmatch(r"fold_\d{4}"), "regime"]) == {POOLED}
    rebuilt = maps_from_frame(table)
    for map_id, cmap in maps.calibration_maps().items():
        np.testing.assert_array_equal(rebuilt[map_id].knots, cmap.knots)
        np.testing.assert_array_equal(rebuilt[map_id].values, cmap.values)
    fallback = table.drop_duplicates("map_id").set_index("map_id")["fallback"]
    assert fallback.to_dict() == {**dict.fromkeys(maps.pooled, False), **maps.fallback}
    summary = regime_map_summary(maps)
    assert len(summary) == len(YEARS) * len(REGIME_LABELS)
    assert summary["fallback"].sum() == sum(maps.fallback.values())


def test_apply_regime_maps_uses_each_rows_map() -> None:
    predictions = synthetic_predictions([2021], 20)
    predictions["regime"] = ["high_up", "low_down"] * 10
    shift_up = maps_from_frame(
        pd.DataFrame(
            {
                "map_id": regime_map_id(2021, "high_up"),
                "knot_index": [0, 1],
                "predicted": [0.0, 1.0],
                "calibrated": [0.5, 1.0],
                "n_samples": 10,
                "is_identity": False,
            }
        )
    )
    flat = maps_from_frame(
        pd.DataFrame(
            {
                "map_id": regime_map_id(2021, "low_down"),
                "knot_index": [0, 1],
                "predicted": [0.0, 1.0],
                "calibrated": [0.2, 0.2],
                "n_samples": 10,
                "is_identity": False,
            }
        )
    )
    out = apply_regime_maps(predictions, {**shift_up, **flat})
    raw = predictions["predicted_raw"].to_numpy()
    expected = np.where(predictions["regime"] == "high_up", 0.5 + 0.5 * raw, 0.2)
    np.testing.assert_allclose(out["predicted_calibrated"], expected)
    assert out["is_out_of_sample"].all()
    assert set(out["map_id"]) == {"fold_2021_high_up", "fold_2021_low_down"}
    with pytest.raises(ValueError, match="missing calibration maps"):
        apply_regime_maps(predictions, shift_up)


def test_paired_sample_equals_pooled_when_every_regime_falls_back() -> None:
    predictions = synthetic_predictions(YEARS, 200)
    features = _features(predictions, {"AAA": (0.9, 0.05), "BBB": (0.1, -0.05)})
    maps = walk_forward_regime_maps(predictions, features, AnalyticsConfig(min_fit_samples=10**6))
    paired = paired_sample(predictions, features, maps)
    assert list(paired.columns) == list(PAIRED_COLUMNS)
    np.testing.assert_array_equal(paired["predicted_pooled"], paired["predicted_regime"])
    assert paired["regime_fallback"].all()
    assert not paired.loc[paired["fold"] == 2020, "is_out_of_sample"].any()
    comparison = compare_metrics(paired)
    assert (comparison["difference"] == 0).all()
    assert (comparison[["ci_low", "ci_high"]] == 0).all().all()
    decision = decide(comparison)
    assert not decision.use_regime
    assert decision.chosen == POOLED


def test_ece_equals_the_engine() -> None:
    rng = np.random.default_rng(3)
    p = rng.uniform(size=500)
    p[:5] = [0.0, 1.0, 0.1, 0.2, 0.9999999]
    y = rng.uniform(size=500) < p
    assert ece(p, y, 10) == pytest.approx(expected_calibration_error(p, y, bins=10), abs=1e-15)
    np.testing.assert_array_equal(bin_index(np.array([0.0, 0.1, 0.95, 1.0]), 10), [0, 1, 9, 9])
    assert log_loss_terms(p, y).mean() == pytest.approx(log_loss(p, y), rel=1e-12)


def _slow_ece_difference(
    first: np.ndarray,
    second: np.ndarray,
    y: np.ndarray,
    clusters: np.ndarray,
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    """Draw clusters as cluster_bootstrap_ci does, rebuild each resample, recompute the ECEs."""
    labels, inverse = np.unique(clusters, return_inverse=True)
    n = labels.shape[0]
    draws = np.random.default_rng(seed).multinomial(n, np.full(n, 1.0 / n), size=resamples)
    diffs = []
    for counts in draws:
        rows = np.concatenate(
            [np.repeat(np.flatnonzero(inverse == c), k) for c, k in enumerate(counts)]
        )
        diffs.append(
            expected_calibration_error(second[rows], y[rows], bins=10)
            - expected_calibration_error(first[rows], y[rows], bins=10)
        )
    low, high = np.quantile(diffs, [0.025, 0.975])
    return float(low), float(high)


@settings(max_examples=25, deadline=None)
@given(n=st.integers(5, 60), n_clusters=st.integers(1, 8), seed=st.integers(0, 10**6))
def test_ece_bootstrap_matches_a_slow_resampling(n: int, n_clusters: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    first = rng.uniform(size=n)
    second = np.clip(first + rng.normal(0, 0.1, size=n), 0, 1)
    y = rng.uniform(size=n) < first
    clusters = rng.integers(0, n_clusters, size=n)
    fast = cluster_bootstrap_ece_difference(
        first, second, y, clusters, bins=10, resamples=30, seed=seed
    )
    slow = _slow_ece_difference(first, second, y, clusters, resamples=30, seed=seed)
    assert fast == pytest.approx(slow, abs=1e-12)


def test_ece_bootstrap_validates_its_inputs() -> None:
    p = np.array([0.1, 0.2])
    y = np.array([True, False])
    with pytest.raises(ValueError, match="equal length"):
        cluster_bootstrap_ece_difference(p, p[:1], y, [1, 2], bins=10, resamples=5, seed=1)
    with pytest.raises(ValueError, match="resamples"):
        cluster_bootstrap_ece_difference(p, p, y, [1, 2], bins=10, resamples=0, seed=1)
    with pytest.raises(ValueError, match="level"):
        cluster_bootstrap_ece_difference(p, p, y, [1, 2], bins=10, resamples=5, seed=1, level=1)


def test_paired_brier_difference_uses_the_existing_bootstrap() -> None:
    predictions = synthetic_predictions(YEARS, 400)
    features = _features(predictions, {"AAA": (0.9, 0.05), "BBB": (0.1, -0.05)})
    maps = walk_forward_regime_maps(predictions, features)
    paired = paired_sample(predictions, features, maps)
    comparison = compare_metrics(paired)
    assert list(comparison.columns) == list(COMPARISON_COLUMNS)
    oos = paired.loc[paired["is_out_of_sample"]]
    y = oos["realised"].to_numpy()
    a = (oos["predicted_pooled"].to_numpy() - y) ** 2
    b = (oos["predicted_regime"].to_numpy() - y) ** 2
    row = comparison.loc[
        (comparison["segment_type"] == "overall") & (comparison["metric"] == "brier_score")
    ].iloc[0]
    assert row["difference"] == pytest.approx(b.mean() - a.mean())
    expected = cluster_bootstrap_ci(
        b - a,
        oos["expiration"].to_numpy(),
        resamples=DEFAULT_CONFIG.bootstrap_resamples,
        seed=DEFAULT_CONFIG.bootstrap_seed,
    )
    assert (row["ci_low"], row["ci_high"]) == pytest.approx(expected)
    segments = comparison[["segment_type", "segment"]].drop_duplicates()
    assert segments.iloc[0].tolist() == ["overall", "all"]
    assert set(segments["segment_type"]) == {"overall", "regime", "dte_bucket", "fold"}
    assert set(comparison["metric"]) == {"brier_score", "log_loss", "expected_calibration_error"}
    bins = reliability_frame(paired)
    assert set(bins["variant"]) == {"raw", "pooled", "regime"}
    assert len(bins) == 3 * DEFAULT_CONFIG.bins


def test_decide_needs_a_negative_difference_with_its_interval_below_zero() -> None:
    def frame(diff: float, low: float, high: float) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "segment_type": "overall",
                    "segment": "all",
                    "metric": "brier_score",
                    "pooled": 0.13,
                    "regime": 0.13 + diff,
                    "difference": diff,
                    "ci_low": low,
                    "ci_high": high,
                    "n_predictions": 10,
                    "n_clusters": 3,
                }
            ]
        )

    assert decide(frame(-0.01, -0.02, -0.001)).use_regime
    assert decide(frame(-0.01, -0.02, -0.001)).chosen == "regime"
    assert not decide(frame(-0.01, -0.02, 0.001)).use_regime
    assert not decide(frame(0.01, 0.001, 0.02)).use_regime
    empty = decide(compare_metrics(pd.DataFrame({c: [] for c in PAIRED_COLUMNS})))
    assert not empty.use_regime
    assert math.isnan(empty.difference)
