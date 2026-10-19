"""Private type aliases shared by the engine modules.

Arrays hold prices in dollars, volatilities as decimals or times in years, as each
function documents.
"""

from typing import Literal

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

# Option right, using the same codes as the bronze ``right`` column.
Right = Literal["C", "P"]
