import json
from pathlib import Path

import pytest

from app.ml.enhanced_classifier import MODEL_DIR
from app.ml.governance import generate_model_card


@pytest.mark.skipif(not (MODEL_DIR / "registry.json").exists(), reason="models not trained")
def test_registry_contains_all_models():
    payload = json.loads((MODEL_DIR / "registry.json").read_text())
    registrations = {(v["model_type"], v["version"]) for v in payload["versions"]}

    for model_type in ("category", "severity", "vulnerability", "risk", "status"):
        assert (model_type, "1.0.0") in registrations


@pytest.mark.skipif(not (MODEL_DIR / "metadata.json").exists(), reason="models not trained")
def test_endpoint_metadata_records_provenance():
    metadata = json.loads((MODEL_DIR / "metadata.json").read_text())

    assert metadata["training_samples"] > 0
    assert metadata["label_provenance"] == "rule-derived"
    assert metadata["probabilities_calibrated"] is False
    assert len(metadata["dataset_hash"]) == 64
    assert metadata["severity_train_accuracy"] is not None


@pytest.mark.skipif(not (MODEL_DIR / "status_metadata.json").exists(), reason="models not trained")
def test_status_metadata_records_provenance():
    metadata = json.loads((MODEL_DIR / "status_metadata.json").read_text())

    assert metadata["training_samples"] > 0
    assert metadata["probabilities_calibrated"] is False
    assert metadata["cv_scores"]
    assert metadata["label_distribution"]


@pytest.mark.skipif(not (MODEL_DIR / "registry.json").exists(), reason="models not trained")
def test_model_card_renders_limitations():
    card = generate_model_card("status", "1.0.0")

    assert "Model Card" in card
    assert "uncalibrated" in card.lower()
    assert "synthetic" in card.lower()
