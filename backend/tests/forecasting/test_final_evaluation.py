from datetime import datetime, timezone
import json

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("sklearn")

from app.forecasting.evaluate_final import DEFAULT_DESIGN, run_final
from app.forecasting.training_data import Example, PriceDataset, PriceSeries
from app.market.features import SeriesIdentity


def test_final_runner_freezes_recipe_keeps_calibration_out_and_excludes_post_test(tmp_path, monkeypatch):
    import app.forecasting.evaluate_final as module
    identity = SeriesIdentity("r", "z", "cpu", "Linux/UNIX", "CPU")
    dataset = PriceDataset(datetime(2026, 7, 28, tzinfo=timezone.utc), 2136,
        [PriceSeries(identity, {t: .1 for t in range(2136)})], "synthetic", "SIMULATED")
    design = json.loads(DEFAULT_DESIGN.read_text())
    design["datasetSha256"] = "synthetic"
    path = tmp_path / "design.json"
    path.write_text(json.dumps(design))
    monkeypatch.setattr(module, "load_prepared_dataset", lambda _: dataset)

    def fake_evaluation(bounded, train, score, recipe):
        assert (train.start, train.end) == (0, 1257)
        assert (score.start, score.end) == (1791, 2112)
        assert bounded.end_slot == 2112
        assert max(bounded.series[0].prices) == 2111
        assert recipe["parameters"] == design["parameters"]
        return dict(metrics={"CPU": {"overall": {"ml": {"mae": .01}, "persistence": {"mae": .02}, "maeImprovementPct": 50}}}), [
            Example(identity, 1791, 1792, 1, .1, .2, {})], [.19]

    monkeypatch.setattr(module, "evaluate_period", fake_evaluation)
    report = run_final(tmp_path, tmp_path / "report", design_path=path)
    assert report["passesByResource"] == {"CPU": True}
    assert (tmp_path / "report/started.json").exists()
    assert report["partitions"]["test"]["startSlot"] == 1791
    with pytest.raises(ValueError, match="fresh"):
        run_final(tmp_path, tmp_path / "report", design_path=path)


def test_changed_recipe_is_rejected_before_opening_final_data(tmp_path, monkeypatch):
    import app.forecasting.evaluate_final as module
    design = json.loads(DEFAULT_DESIGN.read_text())
    design["correctionWeight"] = 1.
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(design))
    monkeypatch.setattr(module, "load_prepared_dataset", lambda _: pytest.fail("Final data opened before recipe guard"))
    with pytest.raises(ValueError, match="differs"):
        run_final(tmp_path, tmp_path / "report", design_path=path)
