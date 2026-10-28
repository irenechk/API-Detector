import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ml.enhanced_classifier import MODEL_DIR
from app.routers import ml
from app.routers.ml import get_drift, get_model_card, list_models


@pytest.mark.skipif(not (MODEL_DIR / "registry.json").exists(), reason="models not trained")
def test_list_models_exposes_registry_without_paths():
    response = asyncio.run(list_models(None))

    models = response.data["models"]
    assert response.data["total"] == len(models)
    assert {m["model_type"] for m in models} >= {
        "category",
        "severity",
        "vulnerability",
        "risk",
        "status",
    }
    assert all("model_path" not in model for model in models)


@pytest.mark.skipif(not (MODEL_DIR / "registry.json").exists(), reason="models not trained")
def test_model_card_endpoint_returns_markdown():
    card = asyncio.run(get_model_card("status", "1.0.0"))

    assert isinstance(card, str)
    assert card.startswith("# Model Card")


def test_drift_endpoint_defaults_without_reports():
    response = asyncio.run(get_drift())

    assert response.data["threshold"] > 0
    assert response.data["buffered_predictions"] >= 0


@pytest.mark.skipif(not (MODEL_DIR / "registry.json").exists(), reason="models not trained")
def test_router_is_mounted_and_promotion_requires_auth():
    app = FastAPI()
    app.include_router(ml.router)
    client = TestClient(app)

    models_response = client.get("/api/v1/ml/models")
    assert models_response.status_code == 200
    assert models_response.json()["data"]["total"] > 0

    promote_response = client.post("/api/v1/ml/models/status/1.0.0/promote")
    assert promote_response.status_code == 401
