from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ml.enhanced_classifier import MODEL_DIR
from app.routers import scanner
from app.routers.scanner import scan_results


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(scanner.router)
    return TestClient(app)


def test_analyze_batch_returns_classification(client):
    scan_results.clear()
    response = client.post(
        "/api/v1/scanner/analyze",
        json={
            "client": {"name": "zaddp-cli", "version": "test"},
            "endpoints": [
                {"path": "/api/v1/users/{user_id}", "method": "get", "service": "http://127.0.0.1:8000"},
                {"path": "/admin/config", "method": "GET"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["total"] == 2
    assert body["results"][0]["method"] == "GET"
    assert body["results"][0]["security"]
    assert body["results"][0]["ml_enhanced"]["category"]
    assert body["results"][0]["status_prediction"] is None
    assert scan_results == []


@pytest.mark.skipif(not (MODEL_DIR / "status_model.pkl").exists(), reason="status model not trained")
def test_analyze_predicts_status_with_lifecycle_data(client):
    now = datetime.utcnow()
    response = client.post(
        "/api/v1/scanner/analyze",
        json={
            "endpoints": [
                {
                    "path": "/api/v1/accounts/{account_id}",
                    "method": "GET",
                    "owner": "platform",
                    "has_workflow": False,
                    "last_seen": (now - timedelta(days=45)).isoformat(),
                    "traffic": [
                        {
                            "timestamp": (now - timedelta(days=40)).isoformat(),
                            "request_count": 2,
                            "error_4xx_count": 0,
                            "error_5xx_count": 0,
                            "avg_response_time_ms": 120,
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    prediction = response.json()["data"]["results"][0]["status_prediction"]
    assert prediction is not None
    assert prediction["status"] in {"active", "deprecated", "orphaned", "shadow", "zombie"}
    assert 0 <= prediction["status_confidence"] <= 1


def test_analyze_rejects_invalid_path_and_method(client):
    bad_path = client.post(
        "/api/v1/scanner/analyze",
        json={"endpoints": [{"path": "api/v1/users", "method": "GET"}]},
    )
    assert bad_path.status_code == 422

    bad_method = client.post(
        "/api/v1/scanner/analyze",
        json={"endpoints": [{"path": "/api/v1/users", "method": "BREW"}]},
    )
    assert bad_method.status_code == 422


def test_analyze_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("SCANNER_API_TOKEN", "test-secret")
    payload = {"endpoints": [{"path": "/api/v1/users", "method": "GET"}]}

    assert client.post("/api/v1/scanner/analyze", json=payload).status_code == 401
    assert (
        client.post(
            "/api/v1/scanner/analyze",
            json=payload,
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )

    authorized = client.post(
        "/api/v1/scanner/analyze",
        json=payload,
        headers={"Authorization": "Bearer test-secret"},
    )
    assert authorized.status_code == 200
