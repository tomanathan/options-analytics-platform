"""Routes of the spread explorer: the scored spreads and the detail of one spread."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import StringConstraints

from oap.api.deps import StoreDep, respond
from oap.api.models import SpreadDetail, SpreadsResponse
from oap.api.routers import ERROR_RESPONSES, SYMBOL_PATTERN
from oap.api.spreads import MAX_SPREAD_ROWS, SpreadFilters

router = APIRouter(prefix="/api/spreads", tags=["spreads"], responses=ERROR_RESPONSES)

SymbolFilter = Annotated[str, StringConstraints(pattern=SYMBOL_PATTERN)]


@router.get("", name="listSpreads", response_model=SpreadsResponse)
def list_spreads(
    store: StoreDep,
    response: Response,
    underlying: Annotated[
        list[SymbolFilter] | None, Query(description="Underlyings to keep.")
    ] = None,
    expiration: Annotated[date | None, Query(description="Expiration to keep.")] = None,
    min_width: Annotated[float | None, Query(ge=0, description="Minimum width, $/sh.")] = None,
    max_width: Annotated[float | None, Query(ge=0, description="Maximum width, $/sh.")] = None,
    min_pop: Annotated[float, Query(ge=0, le=1, description="Minimum calibrated POP.")] = 0.0,
    min_credit: Annotated[float, Query(ge=0, description="Minimum mid credit, $/sh.")] = 0.0,
    eligible_only: Annotated[bool, Query(description="Keep eligible spreads only.")] = True,
    limit: Annotated[
        int, Query(ge=1, le=MAX_SPREAD_ROWS, description="Most rows returned.")
    ] = MAX_SPREAD_ROWS,
) -> SpreadsResponse:
    """List the scored put credit spreads of the latest session.

    Args:
        store: The data store.
        response: The response, for the stale-data header.
        underlying: Underlyings to keep; all when empty.
        expiration: Expiration to keep; all when None.
        min_width: Narrowest spread in dollars per share.
        max_width: Widest spread in dollars per share.
        min_pop: Smallest calibrated probability of profit, a decimal.
        min_credit: Smallest mid credit in dollars per share.
        eligible_only: Keep only spreads that pass the eligibility rules.
        limit: Most rows returned.

    Returns:
        The matching spreads in rank order, with the facets of the whole table.
    """
    filters = SpreadFilters(
        underlyings=tuple(underlying or ()),
        expiration=expiration,
        min_width=min_width,
        max_width=max_width,
        min_pop=min_pop,
        min_credit=min_credit,
        eligible_only=eligible_only,
        limit=limit,
    )
    return respond(store.spreads(filters), response)


@router.get("/{spread_key}", name="getSpread", response_model=SpreadDetail)
def get_spread(spread_key: str, store: StoreDep, response: Response) -> SpreadDetail:
    """Return one spread with its payoff curve and the densities behind it.

    Args:
        spread_key: The ``spread_key`` column, URL-encoded (``|`` is ``%7C``).
        store: The data store.
        response: The response, for the stale-data header.

    Returns:
        The spread detail.
    """
    return respond(store.spread(spread_key), response)
