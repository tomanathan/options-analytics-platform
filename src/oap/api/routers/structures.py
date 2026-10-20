"""Routes of the structure calculator: which structure serves an outcome, per ticker and overall."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Response

from oap.api.deps import StoreDep
from oap.api.models import (
    Fill,
    MapChoice,
    OutcomeMapResponse,
    PresetId,
    StructuresResponse,
)
from oap.api.routers import ERROR_RESPONSES, SYMBOL_PATTERN

router = APIRouter(prefix="/api/structures", tags=["structures"], responses=ERROR_RESPONSES)

Symbol = Annotated[str, Path(pattern=SYMBOL_PATTERN, description="Ticker symbol, such as SPY.")]
Session = Annotated[date, Path(description="Trade date, YYYY-MM-DD.")]
MapParam = Annotated[
    MapChoice,
    Query(alias="map", description="auto, production or walk_forward calibration map."),
]
FillParam = Annotated[
    Fill, Query(description="natural (long legs at the ask, short at the bid) or mid.")
]
MinPopGiven = Annotated[
    float,
    Query(
        ge=0,
        le=1,
        description="Smallest P(profit | outcome), a decimal, for a structure to qualify.",
    ),
]

NOT_READY = "Structure scoring is served from the next commit of feat/structures-api."


@router.get("/map", name="getOutcomeMap", response_model=OutcomeMapResponse)
def get_outcome_map(
    store: StoreDep,
    response: Response,
    session: Annotated[
        date | Literal["latest"], Query(description="Trade date, YYYY-MM-DD, or latest.")
    ] = "latest",
    target_dte: Annotated[
        int, Query(ge=7, le=120, description="Target calendar days to expiration.")
    ] = 35,
    fill: FillParam = "natural",
    map_choice: MapParam = "auto",
    min_pop_given: MinPopGiven = 0.5,
) -> OutcomeMapResponse:
    """Return, for every underlying of a session and every preset outcome, the verdict numbers.

    Args:
        store: The data store.
        response: The response, for the stale-data header.
        session: Trade date, or ``latest`` for the latest session of the table.
        target_dte: Calendar days to expiration the expiration is picked for.
        fill: natural or mid fills.
        map_choice: Which calibration map to apply.
        min_pop_given: Smallest P(profit | outcome), a decimal, for a structure to qualify.

    Returns:
        One row per underlying with the session, one cell per preset.
    """
    raise HTTPException(status_code=501, detail=NOT_READY)


@router.get("/{symbol}/{session}", name="getStructures", response_model=StructuresResponse)
def get_structures(
    symbol: Symbol,
    session: Session,
    store: StoreDep,
    response: Response,
    expiration: Annotated[
        date | None,
        Query(description="Expiration; default the one with a distribution nearest 35 days."),
    ] = None,
    preset: Annotated[PresetId | None, Query(description="A preset outcome.")] = None,
    lo: Annotated[
        float | None,
        Query(gt=0, description="Lower bound of a custom outcome as a fraction of the close."),
    ] = None,
    hi: Annotated[
        float | None,
        Query(gt=0, description="Upper bound of a custom outcome as a fraction of the close."),
    ] = None,
    outside: Annotated[
        bool, Query(description="The outcome is the price landing outside [lo, hi).")
    ] = False,
    fill: FillParam = "natural",
    map_choice: MapParam = "auto",
    min_pop_given: MinPopGiven = 0.5,
    limit: Annotated[int, Query(ge=1, le=100, description="Most ranking rows.")] = 25,
) -> StructuresResponse:
    """Score every structure of one expiration against an outcome.

    Args:
        symbol: Ticker symbol.
        session: Trade date.
        store: The data store.
        response: The response, for the stale-data header.
        expiration: Expiration; the one with a distribution nearest 35 days when None.
        preset: A preset outcome; takes precedence over ``lo``, ``hi`` and ``outside``.
        lo: Lower bound as a fraction of the close; open when None.
        hi: Upper bound as a fraction of the close; open when None.
        outside: True for the complement of ``[lo, hi)``.
        fill: natural or mid fills.
        map_choice: Which calibration map to apply.
        min_pop_given: Smallest P(profit | outcome), a decimal, for a structure to qualify.
        limit: Most ranking rows.

    Returns:
        The best structure per kind, the ranking, the dominance strip and the verdict.
    """
    raise HTTPException(status_code=501, detail=NOT_READY)
