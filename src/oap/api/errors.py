"""Errors of the explorer API; ``oap.api.handlers`` turns them into ``ErrorBody`` responses."""

from oap.api.models import ErrorCode

BUSY_DETAIL = "The DuckDB file is locked by a writer (dbt_build or score_spreads). Retry shortly."
MISSING_DETAIL = "No gold data yet: run make dbt-build-local."


class ApiError(Exception):
    """Base class of the API's own errors."""


class DatabaseBusy(ApiError):  # noqa: N818 - named by the design spec
    """The DuckDB file is locked by a writer, so it cannot be opened read-only."""


class DatabaseMissing(ApiError):  # noqa: N818 - named by the design spec
    """The DuckDB file does not exist."""


class GoldMissing(ApiError):  # noqa: N818 - named by the design spec
    """A gold table or column the API reads is missing from the database."""


class NotFound(ApiError):  # noqa: N818 - named by the design spec
    """The requested underlying, session or spread does not exist."""


class Unprocessable(ApiError):  # noqa: N818 - answers HTTP 422 Unprocessable Content
    """The request is well formed but cannot be answered; carries its own error code.

    Attributes:
        code: ``view_required``, ``view_invalid``, ``no_distribution`` or ``no_implied_vol``
            (see docs/runbook.md).
        detail: Human-readable message.
    """

    def __init__(self, code: ErrorCode, detail: str) -> None:
        """Store the code and the message.

        Args:
            code: Machine-readable error code.
            detail: Human-readable message.
        """
        super().__init__(detail)
        self.code: ErrorCode = code
        self.detail = detail
