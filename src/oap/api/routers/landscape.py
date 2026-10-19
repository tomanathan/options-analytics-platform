"""Routes of the landscape view: sessions, chain, distribution and heatmap of one underlying."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

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
def list_sessions(symbol: Symbol) -> SessionsResponse:
    """List the sessions of an underlying.

    Args:
        symbol: Ticker symbol.

    Returns:
        One summary per trade date, ascending.
    """
    raise HTTPException(status_code=501, detail="milestone A1 serves the schema only")


@router.get("/{symbol}/sessions/{session}/chain", name="getChain", response_model=ChainResponse)
def get_chain(symbol: Symbol, session: Session) -> ChainResponse:
    """Return the option chain of one session.

    Args:
        symbol: Ticker symbol.
        session: Trade date.

    Returns:
        The quotes grouped by expiration.
    """
    raise HTTPException(status_code=501, detail="milestone A1 serves the schema only")


@router.get(
    "/{symbol}/sessions/{session}/distribution",
    name="getDistribution",
    response_model=DistributionResponse,
)
def get_distribution(
    symbol: Symbol, session: Session, map_choice: MapParam = "auto"
) -> DistributionResponse:
    """Return the raw and calibrated risk-neutral distributions of one session.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        map_choice: Which calibration map to apply.

    Returns:
        One distribution per expiration, evaluated at the raw knots.
    """
    raise HTTPException(status_code=501, detail="milestone A1 serves the schema only")


@router.get(
    "/{symbol}/sessions/{session}/heatmap", name="getHeatmap", response_model=HeatmapResponse
)
def get_heatmap(symbol: Symbol, session: Session, map_choice: MapParam = "auto") -> HeatmapResponse:
    """Return the P(S < K) heatmap of one session.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        map_choice: Which calibration map to apply.

    Returns:
        One row per expiration with a curve, over the moneyness display grid.
    """
    raise HTTPException(status_code=501, detail="milestone A1 serves the schema only")
