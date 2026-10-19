import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from oap.api.models import (
    DistributionCurve,
    ErrorBody,
    HeatmapRow,
    MetricValue,
    SpreadDetail,
    SpreadRow,
)


def _heatmap_row(value: float | None) -> HeatmapRow:
    return HeatmapRow(
        expiration=date(2024, 3, 28),
        dte_days=22,
        target_strikes=[1.0],
        prob_below=[value],
        prob_below_calibrated=[value],
        forward_moneyness=value,
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_serialise_as_null(value: float) -> None:
    text = _heatmap_row(value).model_dump_json()
    assert "NaN" not in text
    assert "Infinity" not in text
    assert json.loads(text)["forward_moneyness"] is None
    assert json.loads(text)["prob_below"] == [None]


def test_finite_floats_are_untouched() -> None:
    assert json.loads(_heatmap_row(0.25).model_dump_json())["prob_below"] == [0.25]


def test_models_are_frozen() -> None:
    body = ErrorBody(detail="x", code="invalid")
    with pytest.raises(ValidationError):
        body.detail = "y"


def test_error_codes_are_closed() -> None:
    with pytest.raises(ValidationError):
        ErrorBody(detail="x", code="teapot")  # type: ignore[arg-type]


def test_metric_variants_are_closed() -> None:
    with pytest.raises(ValidationError):
        MetricValue(metric="ece", variant="other", value=1.0, ci_low=None, ci_high=None)  # type: ignore[arg-type]


def test_spread_detail_is_a_spread_row_plus_the_gold_columns() -> None:
    row_fields = set(SpreadRow.model_fields)
    extra = set(SpreadDetail.model_fields) - row_fields
    assert row_fields < set(SpreadDetail.model_fields)
    assert {
        "trade_date",
        "years",
        "underlying_close",
        "expected_payoff",
        "interest",
        "annualised_roc_raw",
        "calibrated",
        "map_id",
        "cash_apy",
        "risk_free_apy",
        "forward",
        "payoff",
        "density_mid",
        "density_raw",
        "density_calibrated",
        "regions",
        "knot_range",
    } == extra


def test_curve_fields_carry_the_documented_units() -> None:
    for name, field in DistributionCurve.model_fields.items():
        assert field.description, name


def test_a_fastapi_response_serialises_non_finite_floats_as_null() -> None:
    app = FastAPI()

    @app.get("/curve", response_model=DistributionCurve)
    def curve() -> DistributionCurve:
        nan, inf = float("nan"), float("inf")
        return DistributionCurve(
            knots=[1.0, inf],
            moneyness=[nan, 1.0],
            cdf=[0.0, 1.0],
            raw_cdf=[0.0, 1.0],
            cdf_calibrated=[0.0, 1.0],
            density_mid=[1.5],
            density=[-inf],
            density_calibrated=[nan],
        )

    response = TestClient(app).get("/curve")
    assert response.status_code == 200
    assert "NaN" not in response.text
    assert "Infinity" not in response.text
    body = response.json()
    assert body["knots"] == [1.0, None]
    assert body["moneyness"] == [None, 1.0]
    assert body["density"] == [None]
