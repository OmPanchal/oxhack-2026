import json
from pathlib import Path

import pytest

from app.api.schemas import ForecastRequest, MarketSnapshot
from app.forecasting.baselines import PersistenceForecastService

FIXTURE = Path(__file__).resolve().parents[3]/"data/examples/forecast-contract.simulated.json"


def test_persistence_exact_values_and_schema_for_all_pools():
    request = ForecastRequest.model_validate(json.loads(FIXTURE.read_text())["request"])
    result = PersistenceForecastService().predict(request)
    assert len(result) == 12
    for row in result:
        assert row.predicted_price_usd_per_unit_hour == (0.25 if row.resource_type == "GPU" else 0.05)
        assert row.target_slot in range(2, 8)
        assert row.generated_at_slot == 1
        assert row.model_version == "persistence-v1"
        assert row.availability_probability is None and row.interruption_probability is None
        assert row.price_lower_bound is None and row.price_upper_bound is None


def test_persistence_order_duplicates_empty_and_no_future_data():
    data = json.loads(FIXTURE.read_text())["request"]
    request = ForecastRequest.model_validate(data)
    expected = PersistenceForecastService().predict(request)
    data["history"].reverse()
    data["history"].append(data["history"][0].copy())
    assert PersistenceForecastService().predict(ForecastRequest.model_validate(data)) == expected
    assert PersistenceForecastService().predict(ForecastRequest(currentSlot=0, history=[])) == []
    with pytest.raises(ValueError, match="Stale"):
        PersistenceForecastService().predict(request.model_copy(update={"current_slot": 2}))
    bad = request.model_copy(deep=True)
    bad.history[0].slot = 99
    with pytest.raises(ValueError):
        PersistenceForecastService().predict(bad)


def test_persistence_unseen_resource_is_still_supported_from_current_observation():
    row = MarketSnapshot(slot=0, region="new-region", resourceType="GPU", gpuType="new-gpu",
                         priceUsdPerUnitHour=7.5, availableUnits=1, source="synthetic test", dataKind="SIMULATED")
    result = PersistenceForecastService().predict(ForecastRequest(currentSlot=0, horizonSlots=1, history=[row]))
    assert result[0].predicted_price_usd_per_unit_hour == 7.5
