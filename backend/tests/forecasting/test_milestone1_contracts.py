from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from app.api.schemas import Forecast, ForecastRequest, OptimizationInput
from app.forecasting.contracts import (
    FixtureForecastService, current_observations, slot_for_timestamp,
    timestamp_for_slot, validate_forecasts,
)
from app.forecasting.interfaces import ForecastService

FIXTURE = Path(__file__).resolve().parents[3] / "data/examples/forecast-contract.simulated.json"


class Milestone1ContractTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(FIXTURE.read_text())
        self.request = ForecastRequest.model_validate(self.document["request"])
        self.forecasts = [Forecast.model_validate(row) for row in self.document["forecasts"]]

    def test_fixture_conforms_to_service_and_optimizer_contracts(self):
        service: ForecastService = FixtureForecastService(FIXTURE)
        result = service.predict(self.request)
        payload = [row.model_dump(mode="json", by_alias=True) for row in result]
        self.assertEqual(len(payload), 12)
        self.assertEqual({row["targetSlot"] for row in payload}, set(range(2, 8)))
        self.assertTrue(all(row["generatedAtSlot"] == 1 for row in payload))
        self.assertTrue(all("_" not in name for row in payload for name in row))
        self.assertTrue(all(row["availabilityProbability"] is None and
                            row["interruptionProbability"] is None and
                            row["priceLowerBound"] is None and row["priceUpperBound"] is None
                            for row in payload))
        model = OptimizationInput(currentSlot=1, pendingJobs=[], runningJobs=[], reservations=[],
                                  forecasts=payload, market=[r for r in self.document["request"]["history"] if r["slot"] == 1])
        self.assertEqual(len(model.forecasts), 12)
        self.assertEqual(self.document["dataKind"], "SIMULATED")

    def test_fixture_is_not_a_general_forecaster_and_returns_fresh_models(self):
        service = FixtureForecastService(FIXTURE)
        changed = self.request.model_copy(update={"horizon_slots": 1})
        with self.assertRaisesRegex(ValueError, "exact"):
            service.predict(changed)
        result = service.predict(self.request)
        result[0].predicted_price_usd_per_unit_hour = 999
        self.assertNotEqual(service.predict(self.request)[0].predicted_price_usd_per_unit_hour, 999)

    def test_current_observations_deduplicate_and_ignore_input_order(self):
        data = deepcopy(self.document["request"])
        data["history"].reverse()
        data["history"].append(deepcopy(data["history"][0]))
        rows = current_observations(ForecastRequest.model_validate(data))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.slot == 1 for row in rows))

    def test_stale_conflicting_or_unspecified_hardware_is_rejected(self):
        stale = self.request.model_copy(update={"current_slot": 2})
        with self.assertRaisesRegex(ValueError, "Stale"):
            current_observations(stale)
        for field, value in (("priceUsdPerUnitHour", 999), ("availableUnits", 999), ("dataKind", "OBSERVED")):
            data = deepcopy(self.document["request"])
            duplicate = dict(data["history"][0])
            duplicate[field] = value
            data["history"].append(duplicate)
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                current_observations(ForecastRequest.model_validate(data))
        data = deepcopy(self.document["request"])
        data["history"][0]["gpuType"] = None
        with self.assertRaisesRegex(ValueError, "gpuType"):
            current_observations(ForecastRequest.model_validate(data))

    def test_empty_history_produces_no_invented_forecasts(self):
        request = ForecastRequest(currentSlot=5, history=[])
        self.assertEqual(current_observations(request), [])
        self.assertEqual(validate_forecasts(request, []), [])
        with self.assertRaises(ValueError):
            validate_forecasts(request, self.forecasts)

    def test_future_and_forecast_as_history_and_invalid_horizons_rejected(self):
        for field, value in (("slot", 2), ("dataKind", "FORECAST")):
            data = deepcopy(self.document["request"])
            data["history"][0][field] = value
            with self.assertRaises(ValidationError):
                ForecastRequest.model_validate(data)
        for horizon in (0, 7):
            with self.assertRaises(ValidationError):
                ForecastRequest(currentSlot=1, horizonSlots=horizon, history=[])

    def test_response_completeness_timestamps_intervals_and_provenance(self):
        for forecasts in (self.forecasts[:-1], self.forecasts + [self.forecasts[0]]):
            with self.assertRaises(ValueError):
                validate_forecasts(self.request, forecasts)
        for update in ({"generated_at_slot": 0}, {"target_slot": 8}, {"region": "unsupported"},
                       {"model_version": " "}, {"price_lower_bound": 0},
                       {"price_lower_bound": 1, "price_upper_bound": 2}):
            forecasts = [f.model_copy(deep=True) for f in self.forecasts]
            forecasts[0] = forecasts[0].model_copy(update=update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_forecasts(self.request, forecasts)

    def test_slot_mapping_normalizes_utc_and_rejects_ambiguous_boundaries(self):
        origin = self.document["originUtc"]
        self.assertEqual(timestamp_for_slot(origin, 2), datetime(2026, 10, 24, 2, tzinfo=timezone.utc))
        self.assertEqual(slot_for_timestamp(origin, "2026-10-24T03:00:00+01:00"), 2)
        for timestamp in ("2026-10-24T00:30:00Z", "2026-10-23T23:00:00Z", "2026-10-24T02:00:00"):
            with self.assertRaises(ValueError):
                slot_for_timestamp(origin, timestamp)
        for slot in (-1, True, 0.5):
            with self.assertRaises(ValueError):
                timestamp_for_slot(origin, slot)


if __name__ == "__main__":
    unittest.main()
