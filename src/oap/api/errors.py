"""Errors of the explorer API and the handlers that turn them into ``ErrorBody`` responses."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from oap.api.models import ErrorBody, ErrorCode

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


def _body(
    status: int, code: ErrorCode, detail: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    """Build an error response.

    Args:
        status: HTTP status code.
        code: Machine-readable error code.
        detail: Human-readable message.
        headers: Extra response headers.

    Returns:
        A JSON response holding an ``ErrorBody``.
    """
    body = ErrorBody(detail=detail, code=code)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


def install_error_handlers(app: FastAPI, *, retry_after_s: int) -> None:
    """Register the exception handlers on an application.

    Args:
        app: The application.
        retry_after_s: Seconds sent in ``Retry-After`` when the database is busy.
    """

    async def busy(_: Request, exc: Exception) -> JSONResponse:
        return _body(503, "database_busy", BUSY_DETAIL, {"Retry-After": str(retry_after_s)})

    async def missing(_: Request, exc: Exception) -> JSONResponse:
        return _body(503, "database_missing", MISSING_DETAIL)

    async def gold_missing(_: Request, exc: Exception) -> JSONResponse:
        return _body(503, "gold_missing", f"The gold schema is incomplete: {exc}")

    async def not_found(_: Request, exc: Exception) -> JSONResponse:
        return _body(404, "not_found", str(exc))

    async def invalid(_: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, RequestValidationError) and exc.errors():
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first.get("loc", ()))
            return _body(422, "invalid", f"{where}: {first.get('msg', 'invalid request')}")
        return _body(422, "invalid", "invalid request")

    async def http_error(_: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, StarletteHTTPException):
            if exc.status_code == 404:
                return _body(404, "not_found", "No such resource.")
            return _body(exc.status_code, "invalid", str(exc.detail))
        return _body(500, "invalid", "unexpected error")

    app.add_exception_handler(DatabaseBusy, busy)
    app.add_exception_handler(DatabaseMissing, missing)
    app.add_exception_handler(GoldMissing, gold_missing)
    app.add_exception_handler(NotFound, not_found)
    app.add_exception_handler(RequestValidationError, invalid)
    app.add_exception_handler(StarletteHTTPException, http_error)
