"""HTTP routers of the explorer API; every handler is a sync ``def`` and runs in the threadpool.

Every route has a fixed ``name`` that is also its OpenAPI operation id, so the generated
TypeScript client does not change when a path is refactored.
"""

from typing import Any, Final

from oap.api.models import ErrorBody

SYMBOL_PATTERN: Final = r"^[A-Z][A-Z.]{0,9}$"
"""Valid ticker symbols; the same rule as ``oap.analytics.io``."""

STALE_HEADER: Final = "X-OAP-Data-Stale"
"""Response header set to ``1`` when a locked database made the service answer from memory."""

ERROR_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    404: {"model": ErrorBody, "description": "Unknown underlying, session or spread."},
    422: {
        "model": ErrorBody,
        "description": "A path or query parameter is invalid (invalid), or the structures "
        "calculator cannot answer: view_required, view_invalid, no_distribution or "
        "no_implied_vol (see docs/runbook.md).",
    },
    503: {
        "model": ErrorBody,
        "description": "The database is locked by a writer, missing, or lacks a gold table.",
        "headers": {
            "Retry-After": {
                "description": "Seconds to wait before retrying (database_busy only).",
                "schema": {"type": "string"},
            }
        },
    },
}
"""Error responses documented on every data route."""
