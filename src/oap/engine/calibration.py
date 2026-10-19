"""Calibration of predicted probabilities against realised outcomes.

The risk-neutral distribution from ``oap.engine.implied_distribution`` is not the real
world distribution, so its probabilities are compared with what happened since 2020 and
corrected. All inputs are probabilities as decimals in [0, 1] and realised outcomes as
booleans; there are no prices in dollars or times in years here beyond the CDF being
recalibrated, whose strikes stay in dollars and whose horizon stays in years.

Provides scoring rules (Brier score, log loss), a reliability table, the expected
calibration error, and an isotonic calibration map that is fitted on past outcomes and
composed with a ``RiskNeutralCdf``.
"""

from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd

from oap.engine._isotonic import isotonic_non_decreasing
from oap.engine._types import FloatArray
from oap.engine._validation import as_float_1d, require_same_length, require_strictly_increasing
from oap.engine.errors import EngineInputError
from oap.engine.implied_distribution import QualityFlag, RiskNeutralCdf

DEFAULT_BINS: Final = 10
MIN_FIT_SAMPLES: Final = 50
LOG_EPS: Final = 1e-15

_FRAME_COLUMNS: Final = ("knot_index", "predicted", "calibrated", "n_samples", "is_identity")


@dataclass(frozen=True)
class ReliabilityBin:
    """One bin of a reliability table.

    Attributes:
        lower: Lower edge of the bin, a probability in [0, 1].
        upper: Upper edge of the bin, a probability in [0, 1].
        n: Number of predictions in the bin.
        mean_predicted: Mean predicted probability in the bin; nan when ``n == 0``.
        frequency_realised: Fraction of outcomes that occurred; nan when ``n == 0``.
    """

    lower: float
    upper: float
    n: int
    mean_predicted: float
    frequency_realised: float


def _validate_pairs(
    predicted: npt.ArrayLike, realised: npt.ArrayLike
) -> tuple[FloatArray, FloatArray]:
    """Validate predicted probabilities and realised outcomes.

    Args:
        predicted: Probabilities as decimals; must be 1-D, finite and in [0, 1].
        realised: Outcomes as booleans or 0/1 values, same length, at least one.

    Returns:
        ``(p, y)`` as float64 arrays, with ``y`` holding 0.0 or 1.0.

    Raises:
        EngineInputError: If any precondition is violated.
    """
    p = as_float_1d(predicted, "predicted")
    if not (np.all(p >= 0.0) and np.all(p <= 1.0)):
        raise EngineInputError("predicted must lie in [0, 1]")
    y = as_float_1d(realised, "realised")
    require_same_length(p, y, ("predicted", "realised"))
    if not np.all((y == 0.0) | (y == 1.0)):
        raise EngineInputError("realised must be boolean or 0/1")
    return p, y


def _check_bins(bins: int) -> None:
    """Require a positive bin count.

    Args:
        bins: Number of equal-width probability bins.

    Raises:
        EngineInputError: If ``bins`` is not a positive integer.
    """
    if not isinstance(bins, int) or bins < 1:
        raise EngineInputError("bins must be a positive integer")


def reliability_table(
    predicted: npt.ArrayLike, realised: npt.ArrayLike, *, bins: int = DEFAULT_BINS
) -> tuple[ReliabilityBin, ...]:
    """Bin predictions and compare their mean with the realised frequency.

    Bins have equal width over [0, 1] (edges ``linspace(0, 1, bins + 1)``); a prediction
    belongs to the bin whose lower edge it meets or exceeds, and 1.0 goes in the last bin.

    Args:
        predicted: Probabilities as decimals in [0, 1].
        realised: Outcomes as booleans or 0/1 values, same length.
        bins: Number of equal-width bins; must be at least 1.

    Returns:
        One ``ReliabilityBin`` per bin, including empty bins (nan means).

    Raises:
        EngineInputError: If inputs or ``bins`` are invalid.
    """
    _check_bins(bins)
    p, y = _validate_pairs(predicted, realised)
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.minimum(np.searchsorted(edges, p, side="right") - 1, bins - 1)
    rows: list[ReliabilityBin] = []
    for b in range(bins):
        in_bin = index == b
        n = int(np.count_nonzero(in_bin))
        rows.append(
            ReliabilityBin(
                lower=float(edges[b]),
                upper=float(edges[b + 1]),
                n=n,
                mean_predicted=float(np.mean(p[in_bin])) if n else float("nan"),
                frequency_realised=float(np.mean(y[in_bin])) if n else float("nan"),
            )
        )
    return tuple(rows)


def brier_score(predicted: npt.ArrayLike, realised: npt.ArrayLike) -> float:
    """Return the Brier score, the mean squared error of probabilities.

    Args:
        predicted: Probabilities as decimals in [0, 1].
        realised: Outcomes as booleans or 0/1 values, same length.

    Returns:
        ``mean((p - y) ** 2)``, a decimal in [0, 1]; lower is better.

    Raises:
        EngineInputError: If inputs are invalid.
    """
    p, y = _validate_pairs(predicted, realised)
    return float(np.mean((p - y) ** 2))


def log_loss(predicted: npt.ArrayLike, realised: npt.ArrayLike, *, eps: float = LOG_EPS) -> float:
    """Return the log loss (negative mean log-likelihood) of probabilities.

    Args:
        predicted: Probabilities as decimals in [0, 1].
        realised: Outcomes as booleans or 0/1 values, same length.
        eps: Probabilities are clipped to ``[eps, 1 - eps]`` to keep the loss finite.

    Returns:
        ``-mean(y ln(pc) + (1 - y) ln(1 - pc))`` in nats; lower is better.

    Raises:
        EngineInputError: If inputs are invalid or ``eps`` is not in (0, 0.5).
    """
    if not (np.isfinite(eps) and 0.0 < eps < 0.5):
        raise EngineInputError("eps must be in (0, 0.5)")
    p, y = _validate_pairs(predicted, realised)
    pc = np.clip(p, eps, 1.0 - eps)
    return float(-np.mean(y * np.log(pc) + (1.0 - y) * np.log(1.0 - pc)))


def expected_calibration_error(
    predicted: npt.ArrayLike, realised: npt.ArrayLike, *, bins: int = DEFAULT_BINS
) -> float:
    """Return the expected calibration error over equal-width probability bins.

    Args:
        predicted: Probabilities as decimals in [0, 1].
        realised: Outcomes as booleans or 0/1 values, same length.
        bins: Number of equal-width bins; must be at least 1.

    Returns:
        ``sum(n_b / N * |mean_predicted_b - frequency_realised_b|)`` over non-empty bins,
        a decimal in [0, 1]; 0 means perfectly calibrated.

    Raises:
        EngineInputError: If inputs or ``bins`` are invalid.
    """
    table = reliability_table(predicted, realised, bins=bins)
    total = sum(row.n for row in table)
    return float(
        sum(
            row.n / total * abs(row.mean_predicted - row.frequency_realised)
            for row in table
            if row.n > 0
        )
    )


@dataclass(frozen=True, eq=False)
class CalibrationMap:
    """Monotone map from predicted to calibrated probabilities.

    Attributes:
        knots: Predicted probabilities, strictly increasing, in [0, 1].
        values: Calibrated probabilities at the knots, non-decreasing, in [0, 1].
        n_samples: Number of outcomes the map was fitted on.
        is_identity: True when the map leaves probabilities unchanged.
    """

    knots: FloatArray
    values: FloatArray
    n_samples: int
    is_identity: bool

    def __post_init__(self) -> None:
        """Validate the knots and values, then freeze the arrays.

        Knots and values are probabilities as decimals in [0, 1]; knots must be strictly
        increasing and values non-decreasing. Arrays are replaced by read-only copies.

        Raises:
            EngineInputError: If any invariant is violated.
        """
        knots = as_float_1d(self.knots, "knots")
        values = as_float_1d(self.values, "values")
        require_same_length(knots, values, ("knots", "values"))
        require_strictly_increasing(knots, "knots")
        for name, arr in (("knots", knots), ("values", values)):
            if not (np.all(arr >= 0.0) and np.all(arr <= 1.0)):
                raise EngineInputError(f"{name} must lie in [0, 1]")
        if not np.all(np.diff(values) >= 0.0):
            raise EngineInputError("values must be non-decreasing")
        if not isinstance(self.n_samples, int) or self.n_samples < 0:
            raise EngineInputError("n_samples must be a non-negative int")
        knots.setflags(write=False)
        values.setflags(write=False)
        object.__setattr__(self, "knots", knots)
        object.__setattr__(self, "values", values)

    @classmethod
    def identity(cls, n_samples: int = 0) -> "CalibrationMap":
        """Return the map that leaves probabilities unchanged.

        Args:
            n_samples: Number of outcomes that were available when fitting was attempted.

        Returns:
            A map with knots and values ``[0, 1]`` and ``is_identity`` set.
        """
        line = np.array([0.0, 1.0])
        return cls(knots=line, values=line.copy(), n_samples=n_samples, is_identity=True)

    def apply(self, p: float) -> float:
        """Calibrate one probability.

        Args:
            p: Predicted probability as a decimal; values outside [0, 1] are clipped.

        Returns:
            Calibrated probability as a decimal in [0, 1], flat beyond the outer knots.
        """
        return float(self.apply_array(p))

    def apply_array(self, p: npt.ArrayLike) -> FloatArray:
        """Calibrate an array of probabilities.

        Args:
            p: Predicted probabilities as decimals; values outside [0, 1] are clipped.

        Returns:
            Calibrated probabilities as decimals in [0, 1], same shape as ``p``, flat
            beyond the outer knots.
        """
        x = np.clip(np.asarray(p, dtype=np.float64), 0.0, 1.0)
        return np.asarray(np.interp(x, self.knots, self.values), dtype=np.float64)

    def to_frame(self) -> pd.DataFrame:
        """Return the map as a table for storage.

        Returns:
            One row per knot with columns ``knot_index`` (int64), ``predicted`` and
            ``calibrated`` (probabilities as decimals), and ``n_samples`` (int64) and
            ``is_identity`` (bool) repeated on every row.
        """
        n = self.knots.shape[0]
        return pd.DataFrame(
            {
                "knot_index": np.arange(n, dtype=np.int64),
                "predicted": self.knots,
                "calibrated": self.values,
                "n_samples": np.full(n, self.n_samples, dtype=np.int64),
                "is_identity": np.full(n, self.is_identity, dtype=np.bool_),
            }
        )

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> "CalibrationMap":
        """Rebuild a map from the table produced by ``to_frame``.

        Args:
            frame: Table with the columns written by ``to_frame``, in any row order.

        Returns:
            The calibration map.

        Raises:
            EngineInputError: If a column is missing, the frame is empty, the repeated
                columns disagree, or the knots and values violate the map invariants.
        """
        missing = [c for c in _FRAME_COLUMNS if c not in frame.columns]
        if missing:
            raise EngineInputError(f"frame is missing columns: {missing}")
        if len(frame) == 0:
            raise EngineInputError("frame must have at least one row")
        ordered = frame.sort_values("knot_index", kind="stable")
        n_samples = ordered["n_samples"].to_numpy()
        flags = ordered["is_identity"].to_numpy()
        if not (np.all(n_samples == n_samples[0]) and np.all(flags == flags[0])):
            raise EngineInputError("n_samples and is_identity must be constant across rows")
        return cls(
            knots=ordered["predicted"].to_numpy(dtype=np.float64),
            values=ordered["calibrated"].to_numpy(dtype=np.float64),
            n_samples=int(n_samples[0]),
            is_identity=bool(flags[0]),
        )


def fit_isotonic_calibration(
    predicted: npt.ArrayLike, realised: npt.ArrayLike, *, min_samples: int = MIN_FIT_SAMPLES
) -> CalibrationMap:
    """Fit a monotone calibration map by isotonic regression of outcomes on predictions.

    Equal predictions are grouped, their outcomes averaged, and the group means made
    non-decreasing with weighted pool-adjacent-violators (weights are group sizes).

    Args:
        predicted: Probabilities as decimals in [0, 1].
        realised: Outcomes as booleans or 0/1 values, same length.
        min_samples: With fewer observations than this the identity map is returned.

    Returns:
        The fitted map, or the identity map when data is insufficient.

    Raises:
        EngineInputError: If inputs are invalid.
    """
    p, y = _validate_pairs(predicted, realised)
    if p.shape[0] < min_samples:
        return CalibrationMap.identity(int(p.shape[0]))
    knots, inverse, counts = np.unique(p, return_inverse=True, return_counts=True)
    means = np.bincount(inverse, weights=y, minlength=knots.shape[0]) / counts
    fitted = np.clip(isotonic_non_decreasing(means, counts.astype(np.float64)), 0.0, 1.0)
    return CalibrationMap(
        knots=knots,
        values=np.maximum.accumulate(fitted),
        n_samples=int(p.shape[0]),
        is_identity=False,
    )


def apply_calibration(cdf: RiskNeutralCdf, cmap: CalibrationMap) -> RiskNeutralCdf:
    """Compose a calibration map with a risk-neutral CDF.

    The composite of two piecewise-linear functions is piecewise linear, with extra knots
    where the CDF crosses the map's knots, so the result is exact. Strikes stay in
    dollars and the horizon in years.

    Args:
        cdf: Risk-neutral CDF of the price at expiry.
        cmap: Calibration map from predicted to calibrated probabilities.

    Returns:
        A new CDF with calibrated probabilities, ``raw_cdf`` equal to the calibrated
        values, the same metadata, and the ``CALIBRATED`` flag added.
    """
    lo, hi = cdf.cdf[0], cdf.cdf[-1]
    extra = [cdf.quantile(float(x)) for x in cmap.knots if lo < x < hi]
    knots = np.unique(np.concatenate([cdf.strikes, np.array(extra, dtype=np.float64)]))
    values = np.maximum.accumulate(cmap.apply_array(cdf.prob_below_array(knots)))
    return RiskNeutralCdf(
        strikes=knots,
        cdf=values,
        raw_cdf=values,
        forward=cdf.forward,
        years=cdf.years,
        rate=cdf.rate,
        n_quotes=cdf.n_quotes,
        flags=cdf.flags | {QualityFlag.CALIBRATED},
    )
