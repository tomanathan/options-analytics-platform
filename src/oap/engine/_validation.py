"""Private input validation helpers for the engine.

Each helper raises ``EngineInputError`` naming the offending argument. Values are in the
units of the caller: dollars for prices and strikes, decimals for volatility, years for
time.
"""

import math

import numpy as np
import numpy.typing as npt

from oap.engine._types import FloatArray
from oap.engine.errors import EngineInputError


def as_float_1d(x: npt.ArrayLike, name: str, *, min_len: int = 1) -> FloatArray:
    """Convert to a finite 1-D float64 array with at least ``min_len`` elements.

    Args:
        x: Values in the caller's units (dollars, decimals or years).
        name: Argument name used in error messages.
        min_len: Minimum number of elements.

    Returns:
        A new float64 array with the same units as the input.

    Raises:
        EngineInputError: If the input is not numeric, not 1-D, too short or not finite.
    """
    try:
        arr = np.array(x, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise EngineInputError(f"{name} must be numeric") from exc
    if arr.ndim != 1:
        raise EngineInputError(f"{name} must be 1-D, got {arr.ndim}-D")
    if arr.shape[0] < min_len:
        raise EngineInputError(f"{name} needs at least {min_len} values, got {arr.shape[0]}")
    if not np.all(np.isfinite(arr)):
        raise EngineInputError(f"{name} must be finite")
    return arr


def require_positive(a: FloatArray, name: str) -> None:
    """Require every value to be strictly greater than zero.

    Args:
        a: Values in the caller's units.
        name: Argument name used in error messages.

    Raises:
        EngineInputError: If any value is not greater than zero.
    """
    if not np.all(a > 0):
        raise EngineInputError(f"{name} must be positive")


def require_non_negative(a: FloatArray, name: str) -> None:
    """Require every value to be greater than or equal to zero.

    Args:
        a: Values in the caller's units.
        name: Argument name used in error messages.

    Raises:
        EngineInputError: If any value is negative.
    """
    if not np.all(a >= 0):
        raise EngineInputError(f"{name} must be non-negative")


def require_strictly_increasing(a: FloatArray, name: str) -> None:
    """Require values to increase strictly (no ties, no decreases).

    Args:
        a: Values in the caller's units, such as strikes in dollars.
        name: Argument name used in error messages.

    Raises:
        EngineInputError: If any consecutive difference is not positive.
    """
    if not np.all(np.diff(a) > 0):
        raise EngineInputError(f"{name} must be strictly increasing")


def require_same_length(a: FloatArray, b: FloatArray, names: tuple[str, str]) -> None:
    """Require two arrays to have the same length.

    Args:
        a: First array, in the caller's units.
        b: Second array, in the caller's units.
        names: Argument names of ``a`` and ``b`` used in error messages.

    Raises:
        EngineInputError: If the lengths differ.
    """
    if a.shape != b.shape:
        raise EngineInputError(
            f"{names[0]} and {names[1]} must have the same length, "
            f"got {a.shape[0]} and {b.shape[0]}"
        )


def require_finite_scalar(x: float, name: str) -> float:
    """Require a finite real number.

    Args:
        x: Value in the caller's units.
        name: Argument name used in error messages.

    Returns:
        The value as a ``float``.

    Raises:
        EngineInputError: If the value is not a finite real number.
    """
    try:
        value = float(x)
    except (TypeError, ValueError) as exc:
        raise EngineInputError(f"{name} must be a number") from exc
    if not math.isfinite(value):
        raise EngineInputError(f"{name} must be finite")
    return value
