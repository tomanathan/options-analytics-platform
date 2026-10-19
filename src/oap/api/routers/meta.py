"""Routes that describe the data as a whole: underlyings and the calibration evidence."""

from fastapi import APIRouter, HTTPException

from oap.api.models import CalibrationSummary, UnderlyingsResponse
from oap.api.routers import ERROR_RESPONSES

router = APIRouter(prefix="/api", tags=["meta"], responses=ERROR_RESPONSES)


@router.get("/underlyings", name="listUnderlyings", response_model=UnderlyingsResponse)
def list_underlyings() -> UnderlyingsResponse:
    """List the underlyings and the latest session.

    Returns:
        Every underlying in ``gold.dim_underlying`` that has quotes.
    """
    raise HTTPException(status_code=501, detail="milestone A1 serves the schema only")


@router.get("/calibration/summary", name="getCalibrationSummary", response_model=CalibrationSummary)
def get_calibration_summary() -> CalibrationSummary:
    """Summarise the production calibration map and its out-of-sample metrics.

    Returns:
        The overall raw, calibrated and delta metrics with their intervals.
    """
    raise HTTPException(status_code=501, detail="milestone A1 serves the schema only")
