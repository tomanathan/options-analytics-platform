"""Walk-forward calibration of the risk-neutral probabilities, and its evaluation.

For each calendar year Y a monotone calibration map is fitted on predictions whose
options had already expired before 1 January of Y, and applied to predictions made during
Y. A map therefore never sees an outcome that was unknown when its predictions were made.
Years before ``first_test_year`` are burn-in: their maps are identity or thinly fitted
and their rows are excluded from every metric. A production map, fitted on every settled
prediction, is stored for scoring the latest session.

Units: probabilities are decimals in [0, 1]; ``realised`` is a boolean; the Brier score is
in squared probability, the log loss in nats, and the expected calibration error (ECE) is
a probability. Dates are ``datetime64`` in frames and ``datetime.date`` in ``FittedMap``.
"""

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from oap.analytics.config import (
    DEFAULT_CONFIG,
    DTE_BUCKETS,
    PRODUCTION_MAP_ID,
    AnalyticsConfig,
    fold_map_id,
)
from oap.analytics.sample import (
    PREDICTION_COLUMNS,
    SNAPSHOT_KEY,
    empty_frame,
    require_columns,
)
from oap.engine._types import BoolArray, FloatArray
from oap.engine.calibration import (
    CalibrationMap,
    brier_score,
    expected_calibration_error,
    fit_isotonic_calibration,
    log_loss,
    reliability_table,
)

MAP_COLUMNS: Final[tuple[str, ...]] = (
    "map_id",
    "fold",
    "train_cutoff",
    "train_max_expiration",
    "knot_index",
    "predicted",
    "calibrated",
    "n_samples",
    "is_identity",
)

SAMPLE_COLUMNS: Final[tuple[str, ...]] = (
    *PREDICTION_COLUMNS,
    "map_id",
    "predicted_calibrated",
    "is_out_of_sample",
)

METRIC_COLUMNS: Final[tuple[str, ...]] = (
    "segment_type",
    "segment",
    "variant",
    "metric",
    "value",
    "ci_low",
    "ci_high",
    "n_predictions",
    "n_snapshots",
    "n_clusters",
)

BIN_COLUMNS: Final[tuple[str, ...]] = (
    "variant",
    "bin_index",
    "lower",
    "upper",
    "n",
    "mean_predicted",
    "frequency_realised",
)

FitFunction = Callable[[FloatArray, BoolArray], CalibrationMap]

_VARIANTS: Final = (("raw", "predicted_raw"), ("calibrated", "predicted_calibrated"))
_SEGMENT_TYPES: Final = ("underlying", "dte_bucket", "fold")


@dataclass(frozen=True, eq=False)
class FittedMap:
    """A calibration map with the provenance needed to audit it for leakage.

    Attributes:
        map_id: ``fold_<year>`` or ``production``.
        fold: Calendar year the map is applied to; None for the production map.
        train_cutoff: First date the map may not use, the 1 January of ``fold``; None for
            the production map.
        train_max_expiration: Latest expiration among the training rows; None if there
            were none. For a fold map it is before ``train_cutoff``.
        cmap: The map from raw to calibrated probabilities (decimals in [0, 1]).
    """

    map_id: str
    fold: int | None
    train_cutoff: date | None
    train_max_expiration: date | None
    cmap: CalibrationMap


def compact_map(cmap: CalibrationMap) -> CalibrationMap:
    """Drop knots that do not change the interpolated map.

    Isotonic fits repeat the same value over long runs of knots. Interpolation inside a
    run of equal values is constant, so every knot strictly inside a run can go while the
    ramps between runs keep their endpoints. The result is exactly equal to ``cmap``
    wherever it is evaluated, and typically has a few hundred knots instead of one per
    distinct prediction.

    Args:
        cmap: Calibration map with probabilities as decimals in [0, 1].

    Returns:
        A map with the same ``n_samples`` and ``is_identity`` and no more knots.
    """
    values = cmap.values
    if values.shape[0] <= 2:
        return cmap
    inside_run = (values[1:-1] == values[:-2]) & (values[1:-1] == values[2:])
    keep = np.concatenate([[True], ~inside_run, [True]])
    if bool(keep.all()):
        return cmap
    return CalibrationMap(
        knots=cmap.knots[keep],
        values=values[keep],
        n_samples=cmap.n_samples,
        is_identity=cmap.is_identity,
    )


def training_mask(predictions: pd.DataFrame, fold: int) -> pd.Series:
    """Select the rows a fold's map may be fitted on.

    Args:
        predictions: Frame with an ``expiration`` column of dates.
        fold: Calendar year the map will be applied to.

    Returns:
        Boolean series, True where ``expiration`` is before 1 January of ``fold``: the
        outcome was settled before the first prediction of the fold was made.
    """
    return predictions["expiration"] < pd.Timestamp(date(fold, 1, 1))


def _fit_rows(rows: pd.DataFrame, fit: FitFunction) -> tuple[CalibrationMap, date | None]:
    """Fit a map on training rows.

    Args:
        rows: Training rows with ``predicted_raw``, ``realised`` and ``expiration``.
        fit: Fitting function.

    Returns:
        The map (identity with zero samples when there are no rows) and the latest
        expiration among the rows, or None.
    """
    if rows.empty:
        return CalibrationMap.identity(0), None
    predicted = rows["predicted_raw"].to_numpy(dtype=np.float64)
    realised = rows["realised"].to_numpy(dtype=np.bool_)
    return fit(predicted, realised), pd.Timestamp(rows["expiration"].max()).date()


def walk_forward_maps(
    predictions: pd.DataFrame,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    *,
    fit: FitFunction | None = None,
) -> dict[str, FittedMap]:
    """Fit one calibration map per fold year, plus the production map.

    The map for year Y is fitted only on rows with ``expiration < 1 January Y``. A fold
    with no such rows gets the identity map without calling ``fit``. The production map
    is fitted on every row.

    Args:
        predictions: Prediction rows with ``fold``, ``expiration``, ``predicted_raw``
            (decimals in [0, 1]) and ``realised`` (boolean).
        config: Analytics parameters; ``min_fit_samples`` sets the default fit.
        fit: Fitting function from predictions and outcomes to a map. Defaults to
            ``compact_map(fit_isotonic_calibration(...))``.

    Returns:
        Maps keyed by ``fold_<year>`` for every year present, then ``production``.

    Raises:
        ValueError: If ``predictions`` lacks a required column.
    """
    require_columns(predictions, ("fold", "expiration", "predicted_raw", "realised"), "predictions")

    def default_fit(predicted: FloatArray, realised: BoolArray) -> CalibrationMap:
        return compact_map(
            fit_isotonic_calibration(predicted, realised, min_samples=config.min_fit_samples)
        )

    fit_fn = default_fit if fit is None else fit
    maps: dict[str, FittedMap] = {}
    for year in sorted(int(y) for y in predictions["fold"].unique()):
        cutoff = date(year, 1, 1)
        cmap, latest = _fit_rows(predictions.loc[training_mask(predictions, year)], fit_fn)
        maps[fold_map_id(year)] = FittedMap(fold_map_id(year), year, cutoff, latest, cmap)
    cmap, latest = _fit_rows(predictions, fit_fn)
    maps[PRODUCTION_MAP_ID] = FittedMap(PRODUCTION_MAP_ID, None, None, latest, cmap)
    return maps


def _date_column(value: date | None, n: int) -> pd.Series:
    """Repeat a date as a ``datetime64`` column.

    Args:
        value: The date, or None for null.
        n: Number of rows.

    Returns:
        Series of ``datetime64[ns]`` with ``n`` identical values (NaT for None).
    """
    stamp = pd.NaT if value is None else pd.Timestamp(value)
    return pd.Series([stamp] * n, dtype="datetime64[ns]")


def maps_to_frame(maps: Mapping[str, FittedMap]) -> pd.DataFrame:
    """Flatten fitted maps into one table, one row per knot.

    Args:
        maps: Fitted maps keyed by map id.

    Returns:
        Frame with ``MAP_COLUMNS``: ``fold`` is a nullable integer, the two date columns
        are ``datetime64`` (null for the production cutoff), ``predicted`` and
        ``calibrated`` are probabilities as decimals. Empty if ``maps`` is empty.
    """
    parts: list[pd.DataFrame] = []
    for map_id, fitted in maps.items():
        part = fitted.cmap.to_frame()
        n = len(part)
        part["map_id"] = map_id
        part["fold"] = pd.array([fitted.fold] * n, dtype="Int64")
        part["train_cutoff"] = _date_column(fitted.train_cutoff, n)
        part["train_max_expiration"] = _date_column(fitted.train_max_expiration, n)
        parts.append(part)
    if not parts:
        return empty_frame(MAP_COLUMNS)
    return pd.concat(parts, ignore_index=True)[list(MAP_COLUMNS)]


def maps_from_frame(frame: pd.DataFrame) -> dict[str, CalibrationMap]:
    """Rebuild calibration maps from the table written by ``maps_to_frame``.

    Args:
        frame: Table with ``map_id`` and the columns of ``CalibrationMap.to_frame``.

    Returns:
        Maps keyed by map id, in ascending id order.

    Raises:
        EngineInputError: If a group violates the map invariants.
        ValueError: If ``map_id`` is missing.
    """
    require_columns(frame, ("map_id",), "map table")
    return {
        str(map_id): CalibrationMap.from_frame(group)
        for map_id, group in frame.groupby("map_id", sort=True)
    }


def apply_fold_maps(
    predictions: pd.DataFrame,
    maps: Mapping[str, CalibrationMap],
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> pd.DataFrame:
    """Calibrate every prediction with the map of its own fold.

    Args:
        predictions: Prediction rows with ``PREDICTION_COLUMNS``.
        maps: Calibration maps keyed by map id; must hold ``fold_<year>`` for every year
            in ``predictions``.
        config: Analytics parameters; ``first_test_year`` starts the out-of-sample years.

    Returns:
        The rows with ``SAMPLE_COLUMNS``: ``map_id``, ``predicted_calibrated`` (a
        decimal in [0, 1]) and ``is_out_of_sample``, which is true when the fold is at
        least ``first_test_year`` and its map is not the identity.

    Raises:
        ValueError: If a column or a fold's map is missing.
    """
    require_columns(predictions, PREDICTION_COLUMNS, "predictions")
    if predictions.empty:
        return empty_frame(SAMPLE_COLUMNS)
    ids = predictions["fold"].map(fold_map_id)
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
    out["map_id"] = ids.astype(object)
    out["predicted_calibrated"] = calibrated
    out["is_out_of_sample"] = out_of_sample
    return out.reset_index(drop=True)


def cluster_bootstrap_ci(
    values: FloatArray,
    clusters: npt.ArrayLike,
    *,
    resamples: int,
    seed: int,
    level: float = 0.95,
) -> tuple[float, float]:
    """Return a percentile confidence interval for a mean, resampling whole clusters.

    Observations in one cluster (predictions resolving on the same expiration date share
    one market move) are not independent, so clusters are drawn with replacement and the
    mean is recomputed over all observations in the drawn clusters.

    Args:
        values: One observation per row, in any unit (for example squared probability
            errors); finite.
        clusters: One cluster label per row, same length as ``values``.
        resamples: Number of bootstrap resamples; at least 1.
        seed: Seed of ``numpy.random.default_rng``; the result is deterministic.
        level: Confidence level as a decimal in (0, 1).

    Returns:
        ``(low, high)`` percentiles of the resampled means, in the unit of ``values``.

    Raises:
        ValueError: If the inputs are empty, mismatched or non-finite, ``resamples`` is
            below 1 or ``level`` is outside (0, 1).
    """
    v = np.asarray(values, dtype=np.float64)
    c = np.asarray(clusters)
    if v.ndim != 1 or v.shape[0] == 0 or c.shape != v.shape:
        raise ValueError("values and clusters must be non-empty 1-D arrays of equal length")
    if not np.all(np.isfinite(v)):
        raise ValueError("values must be finite")
    if resamples < 1:
        raise ValueError("resamples must be at least 1")
    if not 0.0 < level < 1.0:
        raise ValueError("level must be in (0, 1)")
    _, inverse = np.unique(c, return_inverse=True)
    inverse = inverse.reshape(-1)
    n_clusters = int(inverse.max()) + 1
    sums = np.bincount(inverse, weights=v, minlength=n_clusters)
    counts = np.bincount(inverse, minlength=n_clusters).astype(np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(n_clusters, np.full(n_clusters, 1.0 / n_clusters), size=resamples)
    means = (draws @ sums) / (draws @ counts)
    low, high = np.quantile(means, [(1.0 - level) / 2.0, (1.0 + level) / 2.0])
    return float(low), float(high)


def _segments(
    sample: pd.DataFrame,
) -> Iterator[tuple[str, str, pd.DataFrame]]:
    """Yield the overall sample and every segment of it.

    Args:
        sample: Out-of-sample rows.

    Yields:
        ``(segment_type, segment, rows)``: ``overall`` first, then underlyings, DTE
        buckets (shortest first) and folds in ascending order.
    """
    yield "overall", "all", sample
    for segment_type in _SEGMENT_TYPES:
        parts = {str(k): g for k, g in sample.groupby(segment_type, sort=True)}
        order = (
            [b for b in DTE_BUCKETS if b in parts] if segment_type == "dte_bucket" else list(parts)
        )
        for name in order:
            yield segment_type, name, parts[name]


def _metric_row(
    segment_type: str,
    segment: str,
    variant: str,
    metric: str,
    value: float,
    ci: tuple[float, float] | None,
    counts: tuple[int, int, int],
) -> dict[str, object]:
    """Build one row of the metrics table.

    Args:
        segment_type: Kind of segment.
        segment: Segment name.
        variant: ``raw``, ``calibrated`` or ``delta``.
        metric: Metric name.
        value: Metric value.
        ci: Confidence interval, or None for null bounds.
        counts: Numbers of predictions, snapshots and expiration clusters.

    Returns:
        The row as a dictionary keyed by ``METRIC_COLUMNS``.
    """
    low, high = (float("nan"), float("nan")) if ci is None else ci
    n_predictions, n_snapshots, n_clusters = counts
    return {
        "segment_type": segment_type,
        "segment": segment,
        "variant": variant,
        "metric": metric,
        "value": value,
        "ci_low": low,
        "ci_high": high,
        "n_predictions": n_predictions,
        "n_snapshots": n_snapshots,
        "n_clusters": n_clusters,
    }


def calibration_metrics(
    sample: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """Score raw and calibrated probabilities on the out-of-sample rows.

    Metrics are the Brier score (squared probability), log loss (nats) and ECE
    (probability), each for the ``raw`` and ``calibrated`` variant, overall and by
    underlying, DTE bucket and fold. The overall Brier score also has a ``delta`` variant
    (calibrated minus raw; negative is an improvement). Those three overall Brier rows
    carry 95% percentile confidence intervals from a cluster bootstrap over expiration
    dates; every other row has null intervals.

    Args:
        sample: Output of ``apply_fold_maps``.
        config: Analytics parameters (bins, bootstrap size and seed).

    Returns:
        Frame with ``METRIC_COLUMNS``; empty when there are no out-of-sample rows.

    Raises:
        ValueError: If ``sample`` lacks a required column.
    """
    require_columns(sample, SAMPLE_COLUMNS, "sample")
    oos = sample.loc[sample["is_out_of_sample"].astype(bool)]
    if oos.empty:
        return empty_frame(METRIC_COLUMNS)
    rows: list[dict[str, object]] = []
    for segment_type, segment, part in _segments(oos):
        realised = part["realised"].to_numpy(dtype=np.bool_)
        counts = (
            len(part),
            len(part[list(SNAPSHOT_KEY)].drop_duplicates()),
            int(part["expiration"].nunique()),
        )
        scores: dict[str, float] = {}
        for variant, column in _VARIANTS:
            p = part[column].to_numpy(dtype=np.float64)
            for metric, value in (
                ("brier_score", brier_score(p, realised)),
                ("log_loss", log_loss(p, realised)),
                (
                    "expected_calibration_error",
                    expected_calibration_error(p, realised, bins=config.bins),
                ),
            ):
                interval = None
                if segment_type == "overall" and metric == "brier_score":
                    errors = (p - realised) ** 2
                    interval = cluster_bootstrap_ci(
                        errors,
                        part["expiration"].to_numpy(),
                        resamples=config.bootstrap_resamples,
                        seed=config.bootstrap_seed,
                    )
                    scores[variant] = value
                rows.append(
                    _metric_row(segment_type, segment, variant, metric, value, interval, counts)
                )
        if segment_type == "overall":
            rows.append(_delta_row(part, scores, counts, config))
    return pd.DataFrame(rows, columns=list(METRIC_COLUMNS)).astype(
        {"n_predictions": "int64", "n_snapshots": "int64", "n_clusters": "int64"}
    )


def _delta_row(
    part: pd.DataFrame,
    scores: Mapping[str, float],
    counts: tuple[int, int, int],
    config: AnalyticsConfig,
) -> dict[str, object]:
    """Build the overall Brier delta row with its bootstrap interval.

    Args:
        part: All out-of-sample rows.
        scores: Overall Brier scores by variant.
        counts: Numbers of predictions, snapshots and expiration clusters.
        config: Analytics parameters.

    Returns:
        The ``delta`` row (calibrated minus raw, in squared probability).
    """
    realised = part["realised"].to_numpy(dtype=np.bool_)
    raw = part["predicted_raw"].to_numpy(dtype=np.float64)
    calibrated = part["predicted_calibrated"].to_numpy(dtype=np.float64)
    interval = cluster_bootstrap_ci(
        (calibrated - realised) ** 2 - (raw - realised) ** 2,
        part["expiration"].to_numpy(),
        resamples=config.bootstrap_resamples,
        seed=config.bootstrap_seed,
    )
    value = scores["calibrated"] - scores["raw"]
    return _metric_row("overall", "all", "delta", "brier_score", value, interval, counts)


def calibration_bins(
    sample: pd.DataFrame, config: AnalyticsConfig = DEFAULT_CONFIG
) -> pd.DataFrame:
    """Tabulate reliability over the out-of-sample rows, raw and calibrated.

    Args:
        sample: Output of ``apply_fold_maps``.
        config: Analytics parameters; ``bins`` equal-width probability bins.

    Returns:
        Frame with ``BIN_COLUMNS``, ``config.bins`` rows per variant; bin edges and mean
        predicted are probabilities, ``frequency_realised`` is the fraction of outcomes
        that occurred. Empty bins have null means. The frame is empty when there are no
        out-of-sample rows.

    Raises:
        ValueError: If ``sample`` lacks a required column.
    """
    require_columns(sample, SAMPLE_COLUMNS, "sample")
    oos = sample.loc[sample["is_out_of_sample"].astype(bool)]
    if oos.empty:
        return empty_frame(BIN_COLUMNS)
    realised = oos["realised"].to_numpy(dtype=np.bool_)
    rows: list[dict[str, object]] = []
    for variant, column in _VARIANTS:
        table = reliability_table(
            oos[column].to_numpy(dtype=np.float64), realised, bins=config.bins
        )
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
    return pd.DataFrame(rows, columns=list(BIN_COLUMNS)).astype(
        {"bin_index": "int64", "n": "int64"}
    )
