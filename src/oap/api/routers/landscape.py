"""Routes of the landscape view: sessions, chain, distribution and heatmap of one underlying."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from oap.api.deps import StoreDep, respond
from oap.api.models import (
    ChainResponse,
    DistributionResponse,
    HeatmapResponse,
    MapChoice,
    SessionsResponse,
)
from oap.api.routers import ERROR_RESPONSES, SYMBOL_PATTERN

router = APIRouter(prefix="/api/underlyings", tags=["landscape"], responses=ERROR_RESPONSES)

Symbol = Annotated[str, Path(pattern=SYMBOL_PATTERN, description="Ticker symbol, such as SPY.")]
Session = Annotated[date, Path(description="Trade date, YYYY-MM-DD.")]
MapParam = Annotated[
    MapChoice,
    Query(alias="map", description="auto, production or walk_forward calibration map."),
]


@router.get("/{symbol}/sessions", name="listSessions", response_model=SessionsResponse)
def list_sessions(symbol: Symbol, store: StoreDep, response: Response) -> SessionsResponse:
    """List the sessions of an underlying.

    Args:
        symbol: Ticker symbol.
        store: The data store.
        response: The response, for the stale-data header.

    Returns:
        One summary per trade date, ascending.
    """
    return respond(store.sessions(symbol), response)


@router.get("/{symbol}/sessions/{session}/chain", name="getChain", response_model=ChainResponse)
def get_chain(
    symbol: Symbol, session: Session, store: StoreDep, response: Response
) -> ChainResponse:
    """Return the option chain of one session.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        store: The data store.
        response: The response, for the stale-data header.

    Returns:
        The quotes grouped by expiration.
    """
    return respond(store.chain(symbol, session), response)


@router.get(
    "/{symbol}/sessions/{session}/distribution",
    name="getDistribution",
    response_model=DistributionResponse,
)
def get_distribution(
    symbol: Symbol,
    session: Session,
    store: StoreDep,
    response: Response,
    map_choice: MapParam = "auto",
) -> DistributionResponse:
    """Return the raw and calibrated risk-neutral distributions of one session.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        store: The data store.
        response: The response, for the stale-data header.
        map_choice: Which calibration map to apply.

    Returns:
        One distribution per expiration, evaluated at the raw knots.
    """
    return respond(store.distribution(symbol, session, map_choice), response)


@router.get(
    "/{symbol}/sessions/{session}/heatmap", name="getHeatmap", response_model=HeatmapResponse
)
def get_heatmap(
    symbol: Symbol,
    session: Session,
    store: StoreDep,
    response: Response,
    map_choice: MapParam = "auto",
) -> HeatmapResponse:
    """Return the P(S < K) heatmap of one session.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        store: The data store.
        response: The response, for the stale-data header.
        map_choice: Which calibration map to apply.

    Returns:
        One row per expiration with a curve, over the moneyness display grid.
    """
    return respond(store.heatmap(symbol, session, map_choice), response)
