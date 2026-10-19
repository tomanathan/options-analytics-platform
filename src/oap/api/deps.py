"""FastAPI dependencies shared by the routers."""

from typing import Annotated, cast

from fastapi import Depends, Request, Response

from oap.api.routers import STALE_HEADER
from oap.api.store import GoldStore, Served


def get_store(request: Request) -> GoldStore:
    """Return the store of the running application.

    Args:
        request: The request.

    Returns:
        The ``GoldStore`` that ``create_app`` put on the application state.
    """
    return cast(GoldStore, request.app.state.store)


StoreDep = Annotated[GoldStore, Depends(get_store)]


def respond[T](served: Served[T], response: Response) -> T:
    """Unwrap a served value and mark the response stale when it came from old data.

    Args:
        served: The store's answer.
        response: The response that FastAPI will send.

    Returns:
        The value; the ``X-OAP-Data-Stale: 1`` header is set when ``served.stale``.
    """
    if served.stale:
        response.headers[STALE_HEADER] = "1"
    return served.value
