"""Routes that describe the data as a whole: underlyings and the calibration evidence."""

from fastapi import APIRouter, Response

from oap.api.deps import StoreDep, respond
from oap.api.models import CalibrationSummary, UnderlyingsResponse
from oap.api.routers import ERROR_RESPONSES

router = APIRouter(prefix="/api", tags=["meta"], responses=ERROR_RESPONSES)


@router.get("/underlyings", name="listUnderlyings", response_model=UnderlyingsResponse)
def list_underlyings(store: StoreDep, response: Response) -> UnderlyingsResponse:
    """List the underlyings and the latest session.

    Args:
        store: The data store.
        response: The response, for the stale-data header.

    Returns:
        Every underlying in ``gold.dim_underlying`` that has quotes.
    """
    return respond(store.underlyings(), response)


@router.get("/calibration/summary", name="getCalibrationSummary", response_model=CalibrationSummary)
def get_calibration_summary(store: StoreDep, response: Response) -> CalibrationSummary:
    """Summarise the production calibration map and its out-of-sample metrics.

    Args:
        store: The data store.
        response: The response, for the stale-data header.

    Returns:
        The overall raw, calibrated and delta metrics with their intervals.
    """
    return respond(store.calibration_summary(), response)
