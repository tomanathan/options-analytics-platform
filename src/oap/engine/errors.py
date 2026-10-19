"""Exception types raised by the options engine.

Every engine function validates its inputs (prices in dollars, volatility as a decimal,
time in years) and signals a violated precondition with ``EngineInputError``, so callers
can tell bad inputs apart from programming errors.
"""


class EngineError(Exception):
    """Base class for engine errors."""


class EngineInputError(EngineError, ValueError):
    """Inputs violate a documented precondition of an engine function."""
