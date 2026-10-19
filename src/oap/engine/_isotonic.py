"""Weighted isotonic regression by pool-adjacent-violators (PAV).

The input values and weights are dimensionless here: the engine applies it to cumulative
probabilities in [0, 1] (strike spacing in dollars acts as the weight) and to realised
frequencies. No time dimension (years) enters; the function only reorders levels.
"""

import numpy as np
import numpy.typing as npt

from oap.engine._types import FloatArray
from oap.engine._validation import as_float_1d, require_positive, require_same_length


def isotonic_non_decreasing(
    values: npt.ArrayLike, weights: npt.ArrayLike | None = None
) -> FloatArray:
    """Return the non-decreasing sequence closest to ``values`` in weighted least squares.

    Minimises ``sum(w_i * (fit_i - y_i) ** 2)`` subject to ``fit`` being non-decreasing,
    using the weighted pool-adjacent-violators algorithm. Violations are strict, so equal
    neighbours are not pooled.

    Args:
        values: Observations ``y_i`` (dimensionless, for example probabilities).
        weights: Positive weights ``w_i`` of the same length; ones when omitted.

    Returns:
        The fitted non-decreasing sequence, same length as ``values``. Empty input gives
        an empty array.

    Raises:
        EngineInputError: If inputs are not 1-D and finite, or weights are not positive
            and of matching length.
    """
    y = as_float_1d(values, "values", min_len=0)
    if weights is None:
        w = np.ones_like(y)
    else:
        w = as_float_1d(weights, "weights", min_len=0)
        require_same_length(y, w, ("values", "weights"))
        require_positive(w, "weights")
    level: list[float] = []
    weight: list[float] = []
    count: list[int] = []
    for y_i, w_i in zip(y.tolist(), w.tolist(), strict=True):
        level.append(y_i)
        weight.append(w_i)
        count.append(1)
        while len(level) > 1 and level[-2] > level[-1]:
            w_2 = weight.pop()
            l_2 = level.pop()
            c_2 = count.pop()
            w_total = weight[-1] + w_2
            level[-1] = (level[-1] * weight[-1] + l_2 * w_2) / w_total
            weight[-1] = w_total
            count[-1] += c_2
    return np.repeat(np.array(level, dtype=np.float64), np.array(count, dtype=np.int64))
