"""Regime-conditional calibration: one walk-forward map per regime, against the pooled map.

The pooled calibration of ``oap.analytics.backtest`` fits one isotonic map per fold year on
every prediction whose option expired before 1 January of that year. Here the same training
rows are split by the regime of the underlying on the trade date, and a map is fitted per
fold year and regime. The question is whether the regime maps score better out of sample
than the pooled map on exactly the same predictions.

Regime. From the rule lab's features (``oap.analytics.rulelab.regime_features``, imported,
not re-derived), the IV rank ``iv_rank_120`` is bucketed ``low`` (below 1/3), ``mid`` or
``high`` (at least 2/3) and the 20-session log return ``ret_20`` is bucketed ``down`` (at most
0) or ``up`` (above 0). A regime is the pair, such as ``high_down``; six are named. When
either feature is missing the label is ``unknown``. The features use end-of-day data of the
trade date, so the regime is known at the close the predictions are made at.

Maps. ``walk_forward_regime_maps`` fits, for every fold year Y and named regime, an isotonic
map on the rows that ``training_mask(predictions, Y)`` selects and that carry the regime.
A regime with fewer than ``min_fit_samples`` training rows in a fold uses the pooled fold
map instead, and the fallback is recorded; ``unknown`` rows always use the pooled map,
since they are not a regime. Every map is a ``FittedMap`` keyed by ``regime_map_id``, so
``maps_to_frame`` and ``maps_from_frame`` store and rebuild them; ``regime_maps_to_frame``
adds the ``regime``, ``fallback`` and ``n_train`` columns.

Comparison. ``paired_sample`` calibrates every prediction twice, with its pooled fold map
and with its regime map. ``compare_metrics`` scores both on the out-of-sample rows, overall
and per regime, DTE bucket and fold, for the Brier score (squared probability), log loss
(nats) and expected calibration error (probability). Each row carries the paired difference
(regime minus pooled; negative favours the regime maps) and a 95% percentile interval from a
cluster bootstrap over expiration dates: ``cluster_bootstrap_ci`` on the per-row differences
for the Brier score and log loss, and the same resampling of whole clusters with the ECE
recomputed from per-cluster bin sums for the ECE. ``decide`` applies the decision rule: the
regime maps win when the overall Brier difference is negative and its interval lies below 0.

Units: probabilities are decimals in [0, 1]; ``iv_rank_120`` is a share in [0, 1];
``ret_20`` is a log return (a decimal); dates are ``datetime64`` in frames.
"""

import math
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from oap.analytics.backtest import (
    MAP_COLUMNS,
    SAMPLE_COLUMNS,
    FittedMap,
    apply_fold_maps,
    cluster_bootstrap_ci,
    compact_map,
    maps_to_frame,
    training_mask,
    walk_forward_maps,
)
from oap.analytics.config import (
    DEFAULT_CONFIG,
    DTE_BUCKETS,
    AnalyticsConfig,
    fold_map_id,
)
from oap.analytics.sample import PREDICTION_COLUMNS, empty_frame, require_columns
from oap.engine._types import BoolArray, FloatArray
from oap.engine.calibration import (
    LOG_EPS,
    CalibrationMap,
    fit_isotonic_calibration,
    reliability_table,
)

IV_RANK_EDGES: Final[tuple[float, float]] = (1.0 / 3.0, 2.0 / 3.0)
"""``iv_rank_120`` below the first edge is ``low``, at or above the second is ``high``."""
IV_RANK_BUCKETS: Final[tuple[str, ...]] = ("low", "mid", "high")
TREND_BUCKETS: Final[tuple[str, ...]] = ("down", "up")
UNKNOWN: Final = "unknown"
"""Label of a row whose IV rank or 20-session return is missing."""
REGIMES: Final[tuple[str, ...]] = tuple(
    f"{iv}_{trend}" for iv in IV_RANK_BUCKETS for trend in TREND_BUCKETS
)
"""The six named regimes, ``low_down`` to ``high_up``."""
REGIME_LABELS: Final[tuple[str, ...]] = (*REGIMES, UNKNOWN)
POOLED: Final = "pooled"
"""``regime`` value of the pooled fold maps in a regime map table."""
FEATURE_COLUMNS: Final[tuple[str, ...]] = ("underlying", "trade_date", "iv_rank_120", "ret_20")

REGIME_MAP_COLUMNS: Final[tuple[str, ...]] = (*MAP_COLUMNS, "regime", "fallback", "n_train")

PAIRED_COLUMNS: Final[tuple[str, ...]] = (
    "underlying",
    "trade_date",
    "expiration",
    "dte_bucket",
    "fold",
    "regime",
    "realised",
    "predicted_raw",
    "predicted_pooled",
    "predicted_regime",
    "regime_fallback",
    "is_out_of_sample",
)

COMPARISON_COLUMNS: Final[tuple[str, ...]] = (
    "segment_type",
    "segment",
    "metric",
    "pooled",
    "regime",
    "difference",
    "ci_low",
    "ci_high",
    "n_predictions",
    "n_clusters",
)
METRICS: Final[tuple[str, ...]] = ("brier_score", "log_loss", "expected_calibration_error")
SEGMENT_TYPES: Final[tuple[str, ...]] = ("regime", "dte_bucket", "fold")
VARIANTS: Final[tuple[tuple[str, str], ...]] = (
    ("raw", "predicted_raw"),
    ("pooled", "predicted_pooled"),
    ("regime", "predicted_regime"),
)
RELIABILITY_COLUMNS: Final[tuple[str, ...]] = (
    "variant",
    "bin_index",
    "lower",
    "upper",
    "n",
    "mean_predicted",
    "frequency_realised",
)

FitFunction = Callable[[FloatArray, BoolArray], CalibrationMap]
ObjectArray = npt.NDArray[np.object_]


# --- regime labels ---------------------------------------------------------------------------


def iv_rank_bucket(rank: npt.ArrayLike) -> ObjectArray:
    """Bucket IV ranks into ``low``, ``mid`` and ``high``.

    Args:
        rank: ``iv_rank_120`` values, shares in [0, 1]; nan when unknown.

    Returns:
        ``low`` below 1/3, ``high`` at or above 2/3, ``mid`` between, ``unknown`` for nan.
    """
    r = np.asarray(rank, dtype=np.float64)
    low, high = IV_RANK_EDGES
    out = np.where(r < low, "low", np.where(r >= high, "high", "mid")).astype(object)
    out[np.isnan(r)] = UNKNOWN
    return np.asarray(out, dtype=object)


def trend_bucket(ret: npt.ArrayLike) -> ObjectArray:
    """Bucket 20-session log returns into ``down`` and ``up``.

    Args:
        ret: ``ret_20`` values, log returns as decimals; nan when unknown.

    Returns:
        ``down`` at or below 0, ``up`` above 0, ``unknown`` for nan.
    """
    r = np.asarray(ret, dtype=np.float64)
    out = np.where(r > 0.0, "up", "down").astype(object)
    out[np.isnan(r)] = UNKNOWN
    return np.asarray(out, dtype=object)


def regime_of(features: pd.DataFrame) -> pd.Series:
    """Label each row of regime features with its regime.

    Args:
        features: Rows with ``iv_rank_120`` (share in [0, 1]) and ``ret_20`` (decimal log
            return), nan where unknown.

    Returns:
        Labels from ``REGIME_LABELS`` aligned with ``features``: ``<iv>_<trend>`` such as
        ``high_down``, or ``unknown`` when either feature is missing.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(features, ("iv_rank_120", "ret_20"), "features")
    iv = iv_rank_bucket(features["iv_rank_120"].to_numpy(dtype=np.float64, na_value=np.nan))
    trend = trend_bucket(features["ret_20"].to_numpy(dtype=np.float64, na_value=np.nan))
    known = (iv != UNKNOWN) & (trend != UNKNOWN)
    labels = np.where(known, iv + "_" + trend, UNKNOWN)
    return pd.Series(labels.astype(object), index=features.index, name="regime")


def _feature_table(features: pd.DataFrame) -> pd.DataFrame:
    """Return one row per ``(underlying, trade_date)`` with its regime label."""
    require_columns(features, FEATURE_COLUMNS, "features")
    table = features[list(FEATURE_COLUMNS)].copy()
    table["trade_date"] = pd.to_datetime(table["trade_date"]).astype("datetime64[ns]")
    table = table.drop_duplicates(["underlying", "trade_date"])
    table["regime"] = regime_of(table)
    return table[["underlying", "trade_date", "regime"]]


def attach_regime(frame: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Add each row's regime, joined by underlying and trade date.

    Args:
        frame: Rows with ``underlying`` and ``trade_date`` (such as predictions).
        features: Regime features with ``FEATURE_COLUMNS``, one row per underlying and
            session (duplicates keep the first).

    Returns:
        A copy of ``frame`` in its order and index, with a ``regime`` column; ``unknown``
        where no feature row matches.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(frame, ("underlying", "trade_date"), "frame")
    table = _feature_table(features)
    keys = frame[["underlying", "trade_date"]].copy()
    keys["trade_date"] = pd.to_datetime(keys["trade_date"]).astype("datetime64[ns]")
    joined = keys.merge(table, on=["underlying", "trade_date"], how="left", validate="many_to_one")
    out = frame.copy()
    out["regime"] = joined["regime"].fillna(UNKNOWN).to_numpy(dtype=object)
    return out


# --- maps ------------------------------------------------------------------------------------


def regime_map_id(year: int, regime: str) -> str:
    """Return the identifier of the walk-forward map of one fold year and regime.

    Args:
        year: Calendar year the map is applied to.
        regime: A label from ``REGIME_LABELS``.

    Returns:
        Such as ``fold_2023_high_down``.
    """
    return f"{fold_map_id(year)}_{regime}"


@dataclass(frozen=True, eq=False)
class RegimeMaps:
    """Walk-forward calibration maps per fold year and regime, with their pooled fallbacks.

    Attributes:
        pooled: The pooled fold maps keyed by ``fold_<year>`` (no production map).
        by_regime: Keyed by ``regime_map_id(year, regime)`` for every fold year and every
            label in ``REGIME_LABELS``. A fallback entry carries the pooled fold map's
            calibration under the regime's id.
        regime: The regime of each ``by_regime`` id.
        fallback: True for each ``by_regime`` id that uses the pooled fold map.
        n_train: Training rows of the regime in the fold, per ``by_regime`` id.
    """

    pooled: Mapping[str, FittedMap]
    by_regime: Mapping[str, FittedMap]
    regime: Mapping[str, str]
    fallback: Mapping[str, bool]
    n_train: Mapping[str, int]

    def calibration_maps(self) -> dict[str, CalibrationMap]:
        """Return every map, pooled and per regime, keyed by map id."""
        maps = {k: v.cmap for k, v in self.pooled.items()}
        maps.update({k: v.cmap for k, v in self.by_regime.items()})
        return maps


def walk_forward_regime_maps(
    predictions: pd.DataFrame,
    features: pd.DataFrame,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    *,
    fit: FitFunction | None = None,
) -> RegimeMaps:
    """Fit one calibration map per fold year and regime, falling back to the pooled map.

    The map of year Y and regime R is fitted on the rows of ``training_mask(predictions, Y)``
    whose regime is R. With fewer than ``config.min_fit_samples`` such rows, or for
    ``unknown``, it is the pooled fold map of ``walk_forward_maps`` (recorded as a fallback).

    Args:
        predictions: Prediction rows with ``underlying``, ``trade_date``, ``fold``,
            ``expiration``, ``predicted_raw`` (decimals in [0, 1]) and ``realised``.
        features: Regime features with ``FEATURE_COLUMNS``.
        config: Analytics parameters; ``min_fit_samples`` is the fallback threshold.
        fit: Fitting function; defaults to ``compact_map(fit_isotonic_calibration(...))``,
            the fit of the pooled maps.

    Returns:
        The maps.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(
        predictions,
        ("underlying", "trade_date", "fold", "expiration", "predicted_raw", "realised"),
        "predictions",
    )

    def default_fit(predicted: FloatArray, realised: BoolArray) -> CalibrationMap:
        return compact_map(
            fit_isotonic_calibration(predicted, realised, min_samples=config.min_fit_samples)
        )

    fit_fn = default_fit if fit is None else fit
    pooled_all = walk_forward_maps(predictions, config, fit=fit_fn)
    pooled = {k: v for k, v in pooled_all.items() if v.fold is not None}
    labelled = attach_regime(predictions, features)
    by_regime: dict[str, FittedMap] = {}
    regimes: dict[str, str] = {}
    fallback: dict[str, bool] = {}
    n_train: dict[str, int] = {}
    for year in sorted(int(y) for y in predictions["fold"].unique()):
        base = pooled[fold_map_id(year)]
        training = labelled.loc[training_mask(labelled, year)]
        counts = training["regime"].value_counts()
        for regime in REGIME_LABELS:
            map_id = regime_map_id(year, regime)
            n = int(counts.get(regime, 0))
            rows = training.loc[training["regime"] == regime]
            if regime == UNKNOWN or n < config.min_fit_samples:
                fitted = FittedMap(
                    map_id, year, base.train_cutoff, base.train_max_expiration, base.cmap
                )
                fallback[map_id] = True
            else:
                cmap = fit_fn(
                    rows["predicted_raw"].to_numpy(dtype=np.float64),
                    rows["realised"].to_numpy(dtype=np.bool_),
                )
                latest = pd.Timestamp(rows["expiration"].max()).date()
                fitted = FittedMap(map_id, year, date(year, 1, 1), latest, cmap)
                fallback[map_id] = False
            by_regime[map_id] = fitted
            regimes[map_id] = regime
            n_train[map_id] = n
    return RegimeMaps(
        pooled=pooled, by_regime=by_regime, regime=regimes, fallback=fallback, n_train=n_train
    )


def regime_maps_to_frame(maps: RegimeMaps) -> pd.DataFrame:
    """Flatten the pooled and regime maps into one table, one row per knot.

    Args:
        maps: Output of ``walk_forward_regime_maps``.

    Returns:
        ``maps_to_frame`` of every map with ``regime`` (``pooled`` for the pooled fold
        maps), ``fallback`` and ``n_train`` added; ``maps_from_frame`` rebuilds the maps.
    """
    pooled = maps_to_frame(maps.pooled)
    if not pooled.empty:
        pooled["regime"] = POOLED
        pooled["fallback"] = False
        pooled["n_train"] = pooled["n_samples"].astype("int64")
    regime = maps_to_frame(maps.by_regime)
    if not regime.empty:
        ids = regime["map_id"]
        regime["regime"] = ids.map(maps.regime)
        regime["fallback"] = ids.map(maps.fallback).astype(bool)
        regime["n_train"] = ids.map(maps.n_train).astype("int64")
    parts = [p for p in (pooled, regime) if not p.empty]
    if not parts:
        return empty_frame(REGIME_MAP_COLUMNS)
    return pd.concat(parts, ignore_index=True)[list(REGIME_MAP_COLUMNS)]


def regime_map_summary(maps: RegimeMaps) -> pd.DataFrame:
    """Tabulate every fold year and regime: training rows, fallback and map size.

    Args:
        maps: Output of ``walk_forward_regime_maps``.

    Returns:
        One row per regime map id with ``fold``, ``regime``, ``n_train``, ``fallback`` and
        ``n_knots``, by fold then ``REGIME_LABELS`` order.
    """
    rows = [
        {
            "map_id": map_id,
            "fold": fitted.fold,
            "regime": maps.regime[map_id],
            "n_train": maps.n_train[map_id],
            "fallback": maps.fallback[map_id],
            "n_knots": int(fitted.cmap.knots.shape[0]),
        }
        for map_id, fitted in maps.by_regime.items()
    ]
    columns = ["map_id", "fold", "regime", "n_train", "fallback", "n_knots"]
    return pd.DataFrame(rows, columns=columns)


def apply_regime_maps(
    predictions: pd.DataFrame,
    maps: Mapping[str, CalibrationMap],
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """Calibrate every prediction with the map of its fold year and regime.

    Args:
        predictions: Prediction rows with ``PREDICTION_COLUMNS`` and ``regime``.
        maps: Maps keyed by ``regime_map_id``; must hold every fold year and regime present.
        config: Analytics parameters; ``first_test_year`` starts the out-of-sample years.

    Returns:
        The rows with ``SAMPLE_COLUMNS`` and ``regime``, as ``apply_fold_maps`` returns
        them: ``map_id`` is the regime map's id, ``predicted_calibrated`` a decimal in
        [0, 1], and ``is_out_of_sample`` true when the fold is at least
        ``first_test_year`` and the map is not the identity.

    Raises:
        ValueError: If a column or a map is missing.
    """
    require_columns(predictions, (*PREDICTION_COLUMNS, "regime"), "predictions")
    if predictions.empty:
        return empty_frame((*SAMPLE_COLUMNS, "regime"))
    ids = pd.Series(
        [
            regime_map_id(int(y), str(r))
            for y, r in zip(predictions["fold"], predictions["regime"], strict=True)
        ],
        index=predictions.index,
        dtype=object,
    )
    missing = sorted(set(ids.unique()) - set(maps))
    if missing:
        raise ValueError(f"missing calibration maps: {missing}")
    raw = predictions["predicted_raw"].to_numpy(dtype=np.float64)
    folds = predictions["fold"].to_numpy(dtype=np.int64)
    calibrated = np.empty_like(raw)
    out_of_sample = np.zeros(raw.shape[0], dtype=np.bool_)
    for map_id in ids.unique():
        rows = (ids == map_id).to_numpy(dtype=np.bool_)
        cmap = maps[str(map_id)]
        calibrated[rows] = cmap.apply_array(raw[rows])
        out_of_sample[rows] = (folds[rows] >= config.first_test_year) & (not cmap.is_identity)
    out = predictions[list(PREDICTION_COLUMNS)].copy()
    out["map_id"] = ids
    out["predicted_calibrated"] = calibrated
    out["is_out_of_sample"] = out_of_sample
    out["regime"] = predictions["regime"].to_numpy(dtype=object)
    return out.reset_index(drop=True)


def paired_sample(
    predictions: pd.DataFrame,
    features: pd.DataFrame,
    maps: RegimeMaps,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """Calibrate every prediction with its pooled fold map and with its regime map.

    Args:
        predictions: Prediction rows with ``PREDICTION_COLUMNS``.
        features: Regime features with ``FEATURE_COLUMNS``.
        maps: Output of ``walk_forward_regime_maps`` on the same predictions.
        config: Analytics parameters.

    Returns:
        Rows with ``PAIRED_COLUMNS`` in the order of ``predictions``. ``is_out_of_sample``
        follows ``apply_fold_maps`` (fold at least ``first_test_year`` and a pooled map that
        is not the identity); a regime map is never the identity where the pooled one is
        not, because a thin regime falls back to it.

    Raises:
        ValueError: If a column or a map is missing.
    """
    require_columns(predictions, PREDICTION_COLUMNS, "predictions")
    if predictions.empty:
        return empty_frame(PAIRED_COLUMNS)
    labelled = attach_regime(predictions.reset_index(drop=True), features)
    pooled = apply_fold_maps(labelled, {k: v.cmap for k, v in maps.pooled.items()}, config)
    regime = apply_regime_maps(labelled, {k: v.cmap for k, v in maps.by_regime.items()}, config)
    ids = regime["map_id"]
    return pd.DataFrame(
        {
            "underlying": labelled["underlying"],
            "trade_date": labelled["trade_date"],
            "expiration": labelled["expiration"],
            "dte_bucket": labelled["dte_bucket"],
            "fold": labelled["fold"].astype("int64"),
            "regime": labelled["regime"],
            "realised": labelled["realised"].astype(bool),
            "predicted_raw": labelled["predicted_raw"].astype("float64"),
            "predicted_pooled": pooled["predicted_calibrated"].to_numpy(dtype=np.float64),
            "predicted_regime": regime["predicted_calibrated"].to_numpy(dtype=np.float64),
            "regime_fallback": ids.map(maps.fallback).astype(bool).to_numpy(),
            "is_out_of_sample": pooled["is_out_of_sample"].to_numpy(dtype=np.bool_),
        }
    )[list(PAIRED_COLUMNS)]


# --- comparison ------------------------------------------------------------------------------


def brier_terms(predicted: FloatArray, realised: BoolArray) -> FloatArray:
    """Return each row's squared error ``(p - y) ** 2``, in squared probability."""
    return np.asarray((predicted - realised) ** 2, dtype=np.float64)


def log_loss_terms(predicted: FloatArray, realised: BoolArray) -> FloatArray:
    """Return each row's log loss in nats, with the engine's clipping to ``[eps, 1 - eps]``."""
    p = np.clip(predicted, LOG_EPS, 1.0 - LOG_EPS)
    return np.asarray(-np.where(realised, np.log(p), np.log1p(-p)), dtype=np.float64)


def bin_index(predicted: FloatArray, bins: int) -> npt.NDArray[np.int64]:
    """Return the equal-width bin of each probability, as ``reliability_table`` assigns it."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.minimum(np.searchsorted(edges, predicted, side="right") - 1, bins - 1)
    return np.asarray(index, dtype=np.int64)


def ece(predicted: FloatArray, realised: BoolArray, bins: int) -> float:
    """Return the expected calibration error, ``sum_b |sum p_b - sum y_b| / N``.

    This equals ``oap.engine.calibration.expected_calibration_error``.

    Args:
        predicted: Probabilities as decimals in [0, 1].
        realised: Outcomes.
        bins: Number of equal-width bins.

    Returns:
        The ECE as a probability.
    """
    index = bin_index(predicted, bins)
    sum_p = np.bincount(index, weights=predicted, minlength=bins)
    sum_y = np.bincount(index, weights=realised.astype(np.float64), minlength=bins)
    return float(np.abs(sum_p - sum_y).sum() / predicted.shape[0])


def _cluster_draws(
    clusters: npt.ArrayLike, *, resamples: int, seed: int
) -> tuple[npt.NDArray[np.int64], int, npt.NDArray[np.int64]]:
    """Draw whole clusters with replacement exactly as ``cluster_bootstrap_ci`` does.

    Returns:
        The cluster code of each row, the number of clusters and the ``(resamples,
        n_clusters)`` draw counts.
    """
    _, inverse = np.unique(np.asarray(clusters), return_inverse=True)
    inverse = np.asarray(inverse.reshape(-1), dtype=np.int64)
    n_clusters = int(inverse.max()) + 1
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(n_clusters, np.full(n_clusters, 1.0 / n_clusters), size=resamples)
    return inverse, n_clusters, np.asarray(draws, dtype=np.int64)


def cluster_bootstrap_ece_difference(
    first: FloatArray,
    second: FloatArray,
    realised: BoolArray,
    clusters: npt.ArrayLike,
    *,
    bins: int,
    resamples: int,
    seed: int,
    level: float = 0.95,
) -> tuple[float, float]:
    """Return a percentile interval for ``ECE(second) - ECE(first)``, resampling clusters.

    The clusters are drawn as in ``cluster_bootstrap_ci`` (same seed, same draws). Per
    cluster and bin the counts and the sums of predictions and outcomes are kept, so each
    resample's ECE is ``sum_b |sum p_b - sum y_b| / N`` over the drawn clusters.

    Args:
        first: Probabilities of the first variant, decimals in [0, 1].
        second: Probabilities of the second variant, same rows.
        realised: Outcomes of the rows.
        clusters: Cluster label per row (the expiration date).
        bins: Number of equal-width bins.
        resamples: Number of resamples, at least 1.
        seed: Seed of ``numpy.random.default_rng``.
        level: Confidence level as a decimal in (0, 1).

    Returns:
        ``(low, high)`` of the resampled differences, in probability.

    Raises:
        ValueError: If the inputs are empty or mismatched, or ``resamples`` or ``level`` is
            out of range.
    """
    n = first.shape[0]
    if n == 0 or second.shape != first.shape or realised.shape != first.shape:
        raise ValueError("first, second and realised must be non-empty and of equal length")
    if resamples < 1:
        raise ValueError("resamples must be at least 1")
    if not 0.0 < level < 1.0:
        raise ValueError("level must be in (0, 1)")
    inverse, n_clusters, draws = _cluster_draws(clusters, resamples=resamples, seed=seed)
    y = realised.astype(np.float64)
    counts = np.bincount(inverse, minlength=n_clusters).astype(np.float64)
    total = draws @ counts
    values = []
    for p in (first, second):
        cell = inverse * bins + bin_index(p, bins)
        size = n_clusters * bins
        sum_p = np.bincount(cell, weights=p, minlength=size).reshape(n_clusters, bins)
        sum_y = np.bincount(cell, weights=y, minlength=size).reshape(n_clusters, bins)
        values.append(np.abs(draws @ sum_p - draws @ sum_y).sum(axis=1) / total)
    diffs = values[1] - values[0]
    low, high = np.quantile(diffs, [(1.0 - level) / 2.0, (1.0 + level) / 2.0])
    return float(low), float(high)


def _segments(oos: pd.DataFrame) -> Iterator[tuple[str, str, pd.DataFrame]]:
    """Yield the overall rows, then each regime, DTE bucket and fold in a fixed order."""
    yield "overall", "all", oos
    for segment_type in SEGMENT_TYPES:
        parts = {str(k): g for k, g in oos.groupby(segment_type, sort=True)}
        if segment_type == "regime":
            order = [r for r in REGIME_LABELS if r in parts]
        elif segment_type == "dte_bucket":
            order = [b for b in DTE_BUCKETS if b in parts]
        else:
            order = list(parts)
        for name in order:
            yield segment_type, name, parts[name]


def _metric_rows(
    segment_type: str, segment: str, part: pd.DataFrame, config: AnalyticsConfig
) -> list[dict[str, object]]:
    """Score one segment with both variants and bootstrap the paired differences."""
    y = part["realised"].to_numpy(dtype=np.bool_)
    pooled = part["predicted_pooled"].to_numpy(dtype=np.float64)
    regime = part["predicted_regime"].to_numpy(dtype=np.float64)
    clusters = part["expiration"].to_numpy()
    counts = {"n_predictions": len(part), "n_clusters": int(part["expiration"].nunique())}
    boot = {"resamples": config.bootstrap_resamples, "seed": config.bootstrap_seed}
    rows: list[dict[str, object]] = []
    for metric, terms in (("brier_score", brier_terms), ("log_loss", log_loss_terms)):
        a, b = terms(pooled, y), terms(regime, y)
        low, high = cluster_bootstrap_ci(b - a, clusters, **boot)
        rows.append(
            {
                "metric": metric,
                "pooled": float(a.mean()),
                "regime": float(b.mean()),
                "difference": float(b.mean() - a.mean()),
                "ci_low": low,
                "ci_high": high,
            }
        )
    first, second = ece(pooled, y, config.bins), ece(regime, y, config.bins)
    low, high = cluster_bootstrap_ece_difference(
        pooled, regime, y, clusters, bins=config.bins, **boot
    )
    rows.append(
        {
            "metric": "expected_calibration_error",
            "pooled": first,
            "regime": second,
            "difference": second - first,
            "ci_low": low,
            "ci_high": high,
        }
    )
    return [{"segment_type": segment_type, "segment": segment, **r, **counts} for r in rows]


def compare_metrics(paired: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """Score the pooled and regime maps on the out-of-sample rows, with paired intervals.

    Args:
        paired: Output of ``paired_sample``.
        config: Bins, bootstrap size and seed.

    Returns:
        Rows with ``COMPARISON_COLUMNS``: per segment (``overall``, then each regime, DTE
        bucket and fold) and metric (``METRICS``), the pooled and regime values, their
        difference (regime minus pooled; negative favours the regime maps) and the 95%
        cluster-bootstrap interval of the difference. Empty without out-of-sample rows.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(paired, PAIRED_COLUMNS, "paired")
    oos = paired.loc[paired["is_out_of_sample"].astype(bool)]
    if oos.empty:
        return empty_frame(COMPARISON_COLUMNS)
    rows: list[dict[str, object]] = []
    for segment_type, segment, part in _segments(oos):
        rows.extend(_metric_rows(segment_type, segment, part, config))
    return pd.DataFrame(rows, columns=list(COMPARISON_COLUMNS)).astype(
        {"n_predictions": "int64", "n_clusters": "int64"}
    )


def reliability_frame(
    paired: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """Tabulate reliability of the raw, pooled and regime probabilities out of sample.

    Args:
        paired: Output of ``paired_sample``.
        config: ``bins`` equal-width probability bins.

    Returns:
        Rows with ``RELIABILITY_COLUMNS``, ``config.bins`` per variant (``raw``, ``pooled``,
        ``regime``); empty bins have nan means. Empty without out-of-sample rows.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(paired, PAIRED_COLUMNS, "paired")
    oos = paired.loc[paired["is_out_of_sample"].astype(bool)]
    if oos.empty:
        return empty_frame(RELIABILITY_COLUMNS)
    y = oos["realised"].to_numpy(dtype=np.bool_)
    rows: list[dict[str, object]] = []
    for variant, column in VARIANTS:
        table = reliability_table(oos[column].to_numpy(dtype=np.float64), y, bins=config.bins)
        for index, b in enumerate(table):
            rows.append(
                {
                    "variant": variant,
                    "bin_index": index,
                    "lower": b.lower,
                    "upper": b.upper,
                    "n": b.n,
                    "mean_predicted": b.mean_predicted,
                    "frequency_realised": b.frequency_realised,
                }
            )
    return pd.DataFrame(rows, columns=list(RELIABILITY_COLUMNS))


@dataclass(frozen=True)
class Decision:
    """The step-1 decision: which calibration the growth lab uses downstream.

    Attributes:
        use_regime: True when the regime maps win (the overall out-of-sample Brier
            difference is negative and its 95% interval lies below 0).
        brier_pooled: Overall out-of-sample Brier score of the pooled maps.
        brier_regime: The same for the regime maps.
        difference: ``brier_regime - brier_pooled``, in squared probability.
        ci_low: Lower end of the 95% cluster-bootstrap interval of the difference.
        ci_high: Upper end.
        n_predictions: Out-of-sample predictions.
        n_clusters: Expiration dates among them.
    """

    use_regime: bool
    brier_pooled: float
    brier_regime: float
    difference: float
    ci_low: float
    ci_high: float
    n_predictions: int
    n_clusters: int

    @property
    def chosen(self) -> str:
        """``regime`` or ``pooled``: the maps steps 2 and 3 use."""
        return "regime" if self.use_regime else POOLED


def decide(comparison: pd.DataFrame) -> Decision:
    """Apply the decision rule to the overall Brier row of ``compare_metrics``.

    Args:
        comparison: Output of ``compare_metrics``.

    Returns:
        The decision; with no out-of-sample rows the pooled maps are kept and the numbers
        are nan.

    Raises:
        ValueError: If a column is missing.
    """
    require_columns(comparison, COMPARISON_COLUMNS, "comparison")
    rows = comparison.loc[
        (comparison["segment_type"] == "overall") & (comparison["metric"] == "brier_score")
    ]
    if rows.empty:
        nan = math.nan
        return Decision(False, nan, nan, nan, nan, nan, 0, 0)
    row = rows.iloc[0]
    difference, high = float(row["difference"]), float(row["ci_high"])
    return Decision(
        use_regime=difference < 0.0 and high < 0.0,
        brier_pooled=float(row["pooled"]),
        brier_regime=float(row["regime"]),
        difference=difference,
        ci_low=float(row["ci_low"]),
        ci_high=high,
        n_predictions=int(row["n_predictions"]),
        n_clusters=int(row["n_clusters"]),
    )
