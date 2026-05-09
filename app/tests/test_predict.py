"""Unit tests for the FastAPI inference service.

TestClient is constructed WITHOUT a `with` block on purpose. That
bypasses Starlette's lifespan, which would otherwise try to reach a
live MLflow server and Redis. Fakes are injected via FastAPI's
dependency_overrides so the endpoint code runs against in-memory mocks.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.feature_client import FEATURES, FeatureClient, FeatureNotFoundError
from app.main import app, get_feature_client, get_model_loader
from app.model_loader import ModelLoader


SAMPLE_FEATURES = {
    "amt": 50.0,
    "lat": 40.7,
    "long": -74.0,
    "city_pop": 8_000_000,
    "merch_lat": 40.8,
    "merch_long": -74.1,
    "hour": 14,
    "day_of_week": 2,
    "month": 6,
    "age": 35,
    "category_code": 3,
    "gender_code": 1,
}


@pytest.fixture
def fake_loader() -> MagicMock:
    loader = MagicMock(spec=ModelLoader)
    loader.version = "1"
    loader.predict.return_value = (1, 0.87)
    return loader


@pytest.fixture
def fake_feature_client() -> MagicMock:
    fc = MagicMock(spec=FeatureClient)
    fc.get_features.return_value = (
        pd.DataFrame([SAMPLE_FEATURES], columns=FEATURES),
        SAMPLE_FEATURES,
    )
    return fc


@pytest.fixture
def client(fake_loader, fake_feature_client) -> TestClient:
    app.dependency_overrides[get_model_loader] = lambda: fake_loader
    app.dependency_overrides[get_feature_client] = lambda: fake_feature_client
    yield TestClient(app)
    app.dependency_overrides.clear()


# /health
def test_health_returns_status_and_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "model_version": "1"}


# POST /predict
def test_post_predict_returns_full_response(client, fake_loader, fake_feature_client):
    response = client.post("/predict", json={"entity_id": 1234567890123456})
    assert response.status_code == 200

    body = response.json()
    assert body["prediction"] == 1
    assert body["probability"] == pytest.approx(0.87)
    assert body["model_version"] == "1"
    assert "timestamp" in body
    assert "features" not in body

    fake_feature_client.get_features.assert_called_once_with(1234567890123456)
    fake_loader.predict.assert_called_once()


def test_post_predict_invalid_body_returns_422(client):
    response = client.post("/predict", json={})
    assert response.status_code == 422


def test_post_predict_missing_features_returns_404(client, fake_feature_client):
    fake_feature_client.get_features.side_effect = FeatureNotFoundError("not materialized")
    response = client.post("/predict", json={"entity_id": 9999})
    assert response.status_code == 404
    assert "not materialized" in response.json()["detail"]


# GET /predict/{id}
def test_get_predict_with_explain_returns_features(client):
    response = client.get("/predict/1234567890123456?explain=true")
    assert response.status_code == 200
    body = response.json()
    assert body["prediction"] == 1
    assert body["features"] == SAMPLE_FEATURES


def test_get_predict_without_explain_omits_features(client):
    response = client.get("/predict/1234567890123456")
    assert response.status_code == 200
    assert "features" not in response.json()


# /metrics
def test_metrics_endpoint_returns_prometheus_text(client):
    # Hit /predict once so the counter has a non-zero value to render.
    client.post("/predict", json={"entity_id": 1234567890123456})

    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")

    body = response.text
    assert "prediction_requests_total" in body
    assert "prediction_duration_seconds" in body
    assert "model_version_info" in body
