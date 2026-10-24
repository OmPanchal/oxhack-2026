"""Pin existing contract boundaries without introducing new API fields."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.schemas import Forecast, ForecastRequest, JobCreate, Reservation


FIXTURE = Path(__file__).resolve().parents[3] / "data/scenarios/demo.json"


def test_impossible_deadline_remains_representable():
    payload = json.loads(FIXTURE.read_text())["jobs"][0]
    payload.pop("status")
    payload["deadlineSlot"] = 0
    assert JobCreate.model_validate(payload).deadline_slot == 0
    with pytest.raises(ValidationError):
        JobCreate.model_validate({**payload, "status": "RUNNING"})


def test_adjacent_reservations_are_valid_but_empty_windows_are_not():
    fields = dict(job_id="j", region="r", resource_type="GPU", resource_units=1)
    first = Reservation(**fields, start_slot=0, end_slot=2)
    second = Reservation(**fields, start_slot=2, end_slot=3)
    assert first.end_slot == second.start_slot
    with pytest.raises(ValidationError):
        Reservation(**fields, start_slot=2, end_slot=2)


@pytest.mark.parametrize("horizon", [0, 7])
def test_forecast_request_horizon_bounds(horizon):
    with pytest.raises(ValidationError):
        ForecastRequest(current_slot=0, horizon_slots=horizon, history=[])


def test_forecast_history_accepts_current_scenario_rows_but_not_predictions():
    rows = json.loads(FIXTURE.read_text())["market"]
    assert ForecastRequest(current_slot=0, history=rows).history
    rows[0]["dataKind"] = "FORECAST"
    with pytest.raises(ValidationError):
        ForecastRequest(current_slot=0, history=rows)


def test_forecast_unknown_risk_stays_null_and_target_must_be_future():
    fields = dict(generated_at_slot=2, region="r", resource_type="CPU",
                  predicted_price_usd_per_unit_hour=1, model_version="test")
    forecast = Forecast(**fields, target_slot=3).model_dump(by_alias=True)
    assert forecast["availabilityProbability"] is None
    assert forecast["interruptionProbability"] is None
    with pytest.raises(ValidationError):
        Forecast(**fields, target_slot=2)
