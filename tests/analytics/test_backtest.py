from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oap.analytics.backtest import (
    BIN_COLUMNS,
    MAP_COLUMNS,
    METRIC_COLUMNS,
    SAMPLE_COLUMNS,
    FittedMap,
    apply_fold_maps,
    calibration_bins,
    calibration_metrics,
    cluster_bootstrap_ci,
    compact_map,
    maps_from_frame,
    maps_to_frame,
    training_mask,
    walk_forward_maps,
)
from oap.analytics.config import DEFAULT_CONFIG, PRODUCTION_MAP_ID, AnalyticsConfig
from oap.engine._types import BoolArray, FloatArray
from oap.engine.calibration import (
    CalibrationMap,
    brier_score,
    expected_calibration_error,
    fit_isotonic_calibration,
    log_loss,
)
from tests.analytics.frames import synthetic_predictions

YEARS = [2020, 2021, 2022, 2023]


def _unit_floats(n: int) -> st.SearchStrategy[list[float]]:
    return st.lists(st.floats(0.0, 1.0, allow_nan=False), min_size=n, max_size=n, unique=True)


@st.composite
def calibration_maps(draw: st.DrawFn) -> CalibrationMap:
    n = draw(st.integers(2, 40))
    knots = sorted(draw(_unit_floats(n)))
    n_levels = draw(st.integers(1, 6))
    levels = sorted(draw(_unit_floats(n_levels))) if n_levels > 1 else [draw(st.floats(0, 1))]
    picks = sorted(draw(st.integers(0, len(levels) - 1)) for _ in range(n))
    values = [levels[i] for i in picks]
    return CalibrationMap(np.array(knots), np.array(values), n_samples=100, is_identity=False)


@given(calibration_maps())
def test_compact_map_is_exact(cmap: CalibrationMap) -> None:
    compact = compact_map(cmap)
    grid = np.concatenate([np.linspace(0.0, 1.0, 1001), cmap.knots])
    assert np.max(np.abs(compact.apply_array(grid) - cmap.apply_array(grid))) <= 1e-15
    assert compact.knots.shape[0] <= cmap.knots.shape[0]
    assert compact.n_samples == cmap.n_samples
    assert compact.is_identity == cmap.is_identity
    assert compact.knots[0] == cmap.knots[0]
    assert compact.knots[-1] == cmap.knots[-1]
    assert np.all(np.diff(compact.knots) > 0)


def test_compact_map_leaves_identity_unchanged() -> None:
    identity = CalibrationMap.identity(7)
    compact = compact_map(identity)
    assert compact.knots.tolist() == [0.0, 1.0]
    assert compact.values.tolist() == [0.0, 1.0]
    assert compact.is_identity
    assert compact.n_samples == 7


def test_compact_map_shrinks_a_fitted_map_and_keeps_its_values() -> None:
    rng = np.random.default_rng(3)
    p = rng.uniform(size=5000)
    y = rng.uniform(size=5000) < p**2
    fitted = fit_isotonic_calibration(p, y)
    compact = compact_map(fitted)
    assert compact.knots.shape[0] < fitted.knots.shape[0] / 4
    np.testing.assert_array_equal(compact.apply_array(p), fitted.apply_array(p))


def _maps(preds: pd.DataFrame) -> dict[str, FittedMap]:
    return walk_forward_maps(preds)


def _plain(maps: dict[str, FittedMap]) -> dict[str, CalibrationMap]:
    return {k: v.cmap for k, v in maps.items()}


def test_walk_forward_map_ids_and_provenance() -> None:
    preds = synthetic_predictions(YEARS, 300)
    maps = _maps(preds)
    assert list(maps) == ["fold_2020", "fold_2021", "fold_2022", "fold_2023", PRODUCTION_MAP_ID]
    first = maps["fold_2020"]
    assert first.cmap.is_identity
    assert first.cmap.n_samples == 0
    assert first.train_max_expiration is None
    assert first.train_cutoff == date(2020, 1, 1)
    assert maps[PRODUCTION_MAP_ID].cmap.n_samples == len(preds)
    assert maps[PRODUCTION_MAP_ID].fold is None
    assert maps[PRODUCTION_MAP_ID].train_cutoff is None
    for year in (2021, 2022, 2023):
        fitted = maps[f"fold_{year}"]
        assert fitted.fold == year
        assert fitted.train_max_expiration is not None
        assert fitted.train_max_expiration < date(year, 1, 1)
        expected = int(training_mask(preds, year).sum())
        assert fitted.cmap.n_samples == expected
        assert not fitted.cmap.is_identity


def test_thin_training_data_gives_identity_with_its_sample_count() -> None:
    preds = synthetic_predictions([2020, 2021], 20)
    maps = _maps(preds)
    assert maps["fold_2021"].cmap.is_identity
    assert 0 < maps["fold_2021"].cmap.n_samples < DEFAULT_CONFIG.min_fit_samples


def test_empty_predictions_give_only_a_production_identity() -> None:
    maps = _maps(synthetic_predictions(YEARS, 10).iloc[0:0])
    assert list(maps) == [PRODUCTION_MAP_ID]
    assert maps[PRODUCTION_MAP_ID].cmap.is_identity


def test_training_mask_is_expirations_before_january_first() -> None:
    preds = synthetic_predictions([2020, 2021], 200)
    mask = training_mask(preds, 2021)
    assert (preds.loc[mask, "expiration"] < pd.Timestamp("2021-01-01")).all()
    assert (preds.loc[~mask, "expiration"] >= pd.Timestamp("2021-01-01")).all()


def test_spy_fit_never_sees_the_future() -> None:
    preds = synthetic_predictions(YEARS, 300)
    preds["predicted_raw"] = np.linspace(0.01, 0.99, len(preds))  # unique, identifies rows
    calls: list[tuple[FloatArray, BoolArray]] = []

    def spy(p: FloatArray, y: BoolArray) -> CalibrationMap:
        calls.append((p.copy(), y.copy()))
        return CalibrationMap.identity(int(p.shape[0]))

    walk_forward_maps(preds, fit=spy)
    # fold 2020 has no training rows, so fit is not called for it; then 2021-2023, then all.
    assert len(calls) == 4
    for (p, y), year in zip(calls[:3], (2021, 2022, 2023), strict=True):
        train = preds.loc[preds["expiration"] < pd.Timestamp(date(year, 1, 1))]
        assert sorted(p.tolist()) == sorted(train["predicted_raw"].tolist())
        assert y.dtype == np.bool_
        fold_rows = set(preds.loc[preds["fold"] == year, "predicted_raw"])
        assert not fold_rows & set(p.tolist())
    assert calls[3][0].shape[0] == len(preds)


def _poisoned() -> pd.DataFrame:
    preds = synthetic_predictions([2020, 2021, 2022, 2023, 2024], 300)
    early = preds["fold"] < 2023
    preds.loc[early, "realised"] = False
    preds.loc[preds["fold"] == 2023, "predicted_raw"] = 0.95
    preds.loc[preds["fold"] == 2023, "realised"] = True
    return preds


def test_poisoned_fold_is_calibrated_only_from_earlier_outcomes() -> None:
    preds = _poisoned()
    maps = _maps(preds)
    sample = apply_fold_maps(preds, _plain(maps))
    in_2023 = sample.loc[sample["fold"] == 2023]
    assert (in_2023["predicted_raw"] == 0.95).all()
    # Every earlier outcome was a no, so the map for 2023 says 0; leaking would say 1.
    assert (in_2023["predicted_calibrated"] == 0.0).all()
    # The same facts are learned for the next fold and by the production map.
    assert maps["fold_2024"].cmap.apply(0.95) > 0.9
    assert maps[PRODUCTION_MAP_ID].cmap.apply(0.95) > 0.9


def test_apply_fold_maps_columns_flags_and_values() -> None:
    preds = synthetic_predictions(YEARS, 300)
    maps = _plain(_maps(preds))
    sample = apply_fold_maps(preds, maps)
    assert tuple(sample.columns) == SAMPLE_COLUMNS
    assert len(sample) == len(preds)
    first = sample["fold"] == 2020
    np.testing.assert_array_equal(
        sample.loc[first, "predicted_calibrated"], sample.loc[first, "predicted_raw"]
    )
    assert not sample.loc[first, "is_out_of_sample"].any()
    assert sample.loc[sample["fold"] >= 2021, "is_out_of_sample"].all()
    for map_id, rows in sample.groupby("map_id"):
        expected = maps[str(map_id)].apply_array(rows["predicted_raw"].to_numpy())
        np.testing.assert_array_equal(rows["predicted_calibrated"].to_numpy(), expected)
    assert (sample["map_id"] == "fold_" + sample["fold"].astype(str)).all()


def test_first_test_year_moves_the_out_of_sample_boundary() -> None:
    preds = synthetic_predictions(YEARS, 300)
    config = AnalyticsConfig(first_test_year=2023)
    sample = apply_fold_maps(preds, _plain(_maps(preds)), config)
    assert set(sample.loc[sample["is_out_of_sample"], "fold"]) == {2023}


def test_missing_fold_map_raises() -> None:
    preds = synthetic_predictions(YEARS, 100)
    maps = _plain(_maps(preds))
    del maps["fold_2022"]
    with pytest.raises(ValueError, match="fold_2022"):
        apply_fold_maps(preds, maps)


def test_map_frame_round_trip() -> None:
    maps = _maps(synthetic_predictions(YEARS, 300))
    frame = maps_to_frame(maps)
    assert tuple(frame.columns) == MAP_COLUMNS
    assert frame["map_id"].nunique() == len(maps)
    production = frame.loc[frame["map_id"] == PRODUCTION_MAP_ID]
    assert production["fold"].isna().all()
    assert production["train_cutoff"].isna().all()
    assert str(frame["train_cutoff"].dtype).startswith("datetime64")
    back = maps_from_frame(frame.sample(frac=1.0, random_state=1))
    assert set(back) == set(maps)
    for map_id, fitted in maps.items():
        np.testing.assert_array_equal(back[map_id].knots, fitted.cmap.knots)
        np.testing.assert_array_equal(back[map_id].values, fitted.cmap.values)
        assert back[map_id].n_samples == fitted.cmap.n_samples
        assert back[map_id].is_identity == fitted.cmap.is_identity
    fold_2021 = frame.loc[frame["map_id"] == "fold_2021"]
    assert fold_2021["train_cutoff"].iloc[0] == pd.Timestamp("2021-01-01")
    assert fold_2021["train_max_expiration"].iloc[0] < pd.Timestamp("2021-01-01")


def test_empty_maps_give_an_empty_frame() -> None:
    frame = maps_to_frame({})
    assert frame.empty
    assert tuple(frame.columns) == MAP_COLUMNS


def _non_identity_identity_map(n: int) -> CalibrationMap:
    line = np.array([0.0, 1.0])
    return CalibrationMap(line, line.copy(), n_samples=n, is_identity=False)


def _sample(preds: pd.DataFrame) -> pd.DataFrame:
    return apply_fold_maps(preds, _plain(_maps(preds)))


def test_metrics_match_the_engine_functions_per_segment() -> None:
    preds = synthetic_predictions(YEARS, 400)
    sample = _sample(preds)
    metrics = calibration_metrics(sample)
    assert tuple(metrics.columns) == METRIC_COLUMNS
    oos = sample.loc[sample["is_out_of_sample"]]

    def value(seg_type: str, seg: str, variant: str, metric: str) -> float:
        rows = metrics.loc[
            (metrics["segment_type"] == seg_type)
            & (metrics["segment"] == seg)
            & (metrics["variant"] == variant)
            & (metrics["metric"] == metric)
        ]
        assert len(rows) == 1
        return float(rows["value"].iloc[0])

    for seg_type, seg, part in (
        ("overall", "all", oos),
        ("underlying", "AAA", oos.loc[oos["underlying"] == "AAA"]),
        ("fold", "2022", oos.loc[oos["fold"] == 2022]),
        ("dte_bucket", "21-35d", oos),
    ):
        y = part["realised"].to_numpy(dtype=bool)
        for variant, col in (("raw", "predicted_raw"), ("calibrated", "predicted_calibrated")):
            p = part[col].to_numpy()
            assert value(seg_type, seg, variant, "brier_score") == brier_score(p, y)
            assert value(seg_type, seg, variant, "log_loss") == log_loss(p, y)
            assert value(seg_type, seg, variant, "expected_calibration_error") == (
                expected_calibration_error(p, y)
            )
    delta = value("overall", "all", "delta", "brier_score")
    assert delta == pytest.approx(
        value("overall", "all", "calibrated", "brier_score")
        - value("overall", "all", "raw", "brier_score")
    )
    assert delta < 0  # the synthetic raw probabilities are miscalibrated on purpose


def test_metrics_row_inventory_counts_and_intervals() -> None:
    sample = _sample(synthetic_predictions(YEARS, 400))
    metrics = calibration_metrics(sample)
    oos = sample.loc[sample["is_out_of_sample"]]
    segments = 1 + oos["underlying"].nunique() + oos["dte_bucket"].nunique() + oos["fold"].nunique()
    assert len(metrics) == segments * 6 + 1
    assert set(metrics["segment_type"]) == {"overall", "underlying", "dte_bucket", "fold"}
    assert set(metrics["variant"]) == {"raw", "calibrated", "delta"}
    assert set(metrics["metric"]) == {"brier_score", "log_loss", "expected_calibration_error"}
    overall = metrics.loc[metrics["segment_type"] == "overall"]
    assert overall["n_predictions"].eq(len(oos)).all()
    assert overall["n_clusters"].eq(oos["expiration"].nunique()).all()
    assert overall["n_snapshots"].iloc[0] <= len(oos)
    with_ci = metrics.loc[metrics["ci_low"].notna()]
    assert set(zip(with_ci["variant"], with_ci["metric"], strict=True)) == {
        ("raw", "brier_score"),
        ("calibrated", "brier_score"),
        ("delta", "brier_score"),
    }
    assert (with_ci["segment_type"] == "overall").all()
    assert (with_ci["ci_low"] <= with_ci["value"]).all()
    assert (with_ci["value"] <= with_ci["ci_high"]).all()


def test_metrics_use_only_out_of_sample_rows() -> None:
    sample = _sample(synthetic_predictions(YEARS, 400))
    baseline = calibration_metrics(sample)
    burn_in = sample["fold"] == 2020
    tampered = sample.copy()
    tampered.loc[burn_in, "realised"] = ~tampered.loc[burn_in, "realised"]
    tampered.loc[burn_in, "predicted_raw"] = 0.5
    pd.testing.assert_frame_equal(calibration_metrics(tampered), baseline)
    assert "2020" not in set(baseline.loc[baseline["segment_type"] == "fold", "segment"])


def test_metrics_are_seed_deterministic_and_seed_sensitive() -> None:
    sample = _sample(synthetic_predictions(YEARS, 400))
    a = calibration_metrics(sample)
    b = calibration_metrics(sample)
    pd.testing.assert_frame_equal(a, b)
    other = calibration_metrics(sample, AnalyticsConfig(bootstrap_seed=1))
    assert not a["ci_low"].equals(other["ci_low"])
    pd.testing.assert_series_equal(a["value"], other["value"])


def test_identity_maps_give_zero_delta_and_a_degenerate_interval() -> None:
    preds = synthetic_predictions(YEARS, 200)
    maps = {f"fold_{y}": _non_identity_identity_map(100) for y in YEARS}
    sample = apply_fold_maps(preds, maps)
    metrics = calibration_metrics(sample)
    delta = metrics.loc[metrics["variant"] == "delta"]
    assert len(delta) == 1
    assert delta["value"].iloc[0] == 0.0
    assert delta["ci_low"].iloc[0] == 0.0
    assert delta["ci_high"].iloc[0] == 0.0


def test_no_out_of_sample_rows_give_empty_tables() -> None:
    preds = synthetic_predictions([2020], 100)
    sample = _sample(preds)
    assert not sample["is_out_of_sample"].any()
    metrics = calibration_metrics(sample)
    bins = calibration_bins(sample)
    assert metrics.empty
    assert tuple(metrics.columns) == METRIC_COLUMNS
    assert bins.empty
    assert tuple(bins.columns) == BIN_COLUMNS


def test_bins_cover_every_out_of_sample_row() -> None:
    sample = _sample(synthetic_predictions(YEARS, 400))
    bins = calibration_bins(sample)
    n_oos = int(sample["is_out_of_sample"].sum())
    assert tuple(bins.columns) == BIN_COLUMNS
    assert set(bins["variant"]) == {"raw", "calibrated"}
    for _, part in bins.groupby("variant"):
        assert len(part) == DEFAULT_CONFIG.bins
        assert part["n"].sum() == n_oos
        assert part["bin_index"].tolist() == list(range(DEFAULT_CONFIG.bins))
        filled = part.loc[part["n"] > 0]
        assert filled["mean_predicted"].between(filled["lower"], filled["upper"]).all()
        assert filled["frequency_realised"].between(0.0, 1.0).all()


def test_empty_bins_have_null_means() -> None:
    preds = synthetic_predictions(YEARS, 200)
    sample = _sample(preds)
    sample["predicted_raw"] = 0.05
    bins = calibration_bins(sample)
    raw = bins.loc[bins["variant"] == "raw"]
    assert raw.loc[raw["n"] == 0, "mean_predicted"].isna().all()
    assert raw["n"].iloc[0] == int(sample["is_out_of_sample"].sum())


def test_cluster_bootstrap_of_constant_values_is_degenerate() -> None:
    low, high = cluster_bootstrap_ci(
        np.full(30, 0.25), np.repeat(np.arange(10), 3), resamples=50, seed=1
    )
    assert low == pytest.approx(0.25)
    assert high == pytest.approx(0.25)


def test_cluster_bootstrap_validation() -> None:
    values = np.arange(6.0)
    clusters = np.repeat([0, 1, 2], 2)
    with pytest.raises(ValueError, match="level"):
        cluster_bootstrap_ci(values, clusters, resamples=10, seed=0, level=1.0)
    with pytest.raises(ValueError, match="level"):
        cluster_bootstrap_ci(values, clusters, resamples=10, seed=0, level=0.0)
    with pytest.raises(ValueError, match="resamples"):
        cluster_bootstrap_ci(values, clusters, resamples=0, seed=0)
    with pytest.raises(ValueError, match="equal length"):
        cluster_bootstrap_ci(values, clusters[:-1], resamples=10, seed=0)
    with pytest.raises(ValueError, match="finite"):
        cluster_bootstrap_ci(np.array([1.0, np.nan]), [0, 1], resamples=10, seed=0)
    with pytest.raises(ValueError, match="non-empty"):
        cluster_bootstrap_ci(np.array([]), [], resamples=10, seed=0)


def test_cluster_bootstrap_is_deterministic_and_resamples_clusters() -> None:
    rng = np.random.default_rng(5)
    clusters = np.repeat(np.arange(40), 5)
    shared = rng.normal(size=40)[clusters]
    values = shared + 0.01 * rng.normal(size=200)
    a = cluster_bootstrap_ci(values, clusters, resamples=300, seed=9)
    assert a == cluster_bootstrap_ci(values, clusters, resamples=300, seed=9)
    assert a[0] < values.mean() < a[1]
    # Treating every row as its own cluster would understate the uncertainty.
    naive = cluster_bootstrap_ci(values, np.arange(200), resamples=300, seed=9)
    assert (a[1] - a[0]) > 1.5 * (naive[1] - naive[0])


def test_cluster_bootstrap_with_one_cluster_returns_its_mean() -> None:
    low, high = cluster_bootstrap_ci(np.array([1.0, 3.0]), [7, 7], resamples=20, seed=0)
    assert (low, high) == (2.0, 2.0)
