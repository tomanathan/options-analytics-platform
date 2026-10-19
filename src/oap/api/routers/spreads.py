"""Routes of the spread explorer: the scored spreads and the detail of one spread."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import StringConstraints

from oap.api.models import SpreadDetail, SpreadsResponse
from oap.api.routers import ERROR_RESPONSES, SYMBOL_PATTERN

router = APIRouter(prefix="/api/spreads", tags=["spreads"], responses=ERROR_RESPONSES)

MAX_LIMIT = 5000

SymbolFilter = Annotated[str, StringConstraints(pattern=SYMBOL_PATTERN)]


@router.get("", name="listSpreads", response_model=SpreadsResponse)
def list_spreads(
    underlying: Annotated[
        list[SymbolFilter] | None, Query(description="Underlyings to keep.")
    ] = None,
    expiration: Annotated[date | None, Query(description="Expiration to keep.")] = None,
    min_width: Annotated[float | None, Query(ge=0, description="Minimum width, $/sh.")] = None,
    max_width: Annotated[float | None, Query(ge=0, description="Maximum width, $/sh.")] = None,
    min_pop: Annotated[float, Query(ge=0, le=1, description="Minimum calibrated POP.")] = 0.0,
    min_credit: Annotated[float, Query(ge=0, description="Minimum mid credit, $/sh.")] = 0.0,
    eligible_only: Annotated[bool, Query(description="Keep eligible spreads only.")] = True,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Most rows returned.")] = MAX_LIMIT,
) -> SpreadsResponse:
    """List the scored put credit spreads of the latest session.

    Args:
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
    raise HTTPException(status_code=501, detail="milestone A1 serves the schema only")


@router.get("/{spread_key}", name="getSpread", response_model=SpreadDetail)
def get_spread(spread_key: str) -> SpreadDetail:
    """Return one spread with its payoff curve and the densities behind it.

    Args:
        spread_key: The ``spread_key`` column, URL-encoded (``|`` is ``%7C``).

    Returns:
        The spread detail.
    """
    raise HTTPException(status_code=501, detail="milestone A1 serves the schema only")
