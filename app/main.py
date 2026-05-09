"""FastAPI inference service for the fraud-detection model.

Three collaborators:
  ModelLoader    - loads the model from MLflow Registry on startup
  FeatureClient  - fetches features from Feast/Redis at request time
  metrics        - Prometheus counters/histograms on /metrics
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

from app.feature_client import FeatureClient, FeatureNotFoundError
from app.metrics import (
    CONTENT_TYPE,
    PREDICTION_DURATION,
    PREDICTION_ERRORS,
    PREDICTION_REQUESTS,
    render,
)
from app.model_loader import ModelLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)


# Pydantic schemas
class PredictRequest(BaseModel):
    entity_id: int = Field(..., description="cc_num of the cardholder.")


class PredictResponse(BaseModel):
    # Pydantic v2 reserves `model_` as a protected namespace. Opt out so
    # `model_version` works as a field name without a warning.
    model_config = ConfigDict(protected_namespaces=())

    prediction: int
    probability: float
    model_version: str
    timestamp: str
    features: dict | None = None


# Lifespan: load model + feature store once, before serving any request.
@asynccontextmanager
async def lifespan(app: FastAPI):
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
    model_name = os.environ.get("MODEL_NAME", "fraud-detector")
    model_stage = os.environ.get("MODEL_STAGE", "Production")
    feast_repo = os.environ.get("FEAST_REPO_PATH", str(REPO_ROOT / "feast_repo"))

    logger.info("Loading model %s/%s from %s", model_name, model_stage, tracking_uri)
    loader = ModelLoader(tracking_uri, model_name, model_stage)
    loader.load()

    logger.info("Initializing Feast client (repo=%s)", feast_repo)
    feature_client = FeatureClient(feast_repo)

    app.state.model_loader = loader
    app.state.feature_client = feature_client
    logger.info("Service ready. Model v%s loaded.", loader.version)
    yield


app = FastAPI(title="ModelServe - Fraud Detection API", version="0.2.0", lifespan=lifespan)


# Dependencies. Read from app.state so tests can override.
def get_model_loader(request: Request) -> ModelLoader:
    return request.app.state.model_loader


def get_feature_client(request: Request) -> FeatureClient:
    return request.app.state.feature_client


# Shared by GET and POST handlers.
def _do_predict(
    entity_id: int,
    loader: ModelLoader,
    fc: FeatureClient,
    explain: bool,
) -> PredictResponse:
    PREDICTION_REQUESTS.inc()
    try:
        with PREDICTION_DURATION.time():
            features_df, raw_values = fc.get_features(entity_id)
            label, proba = loader.predict(features_df)
    except FeatureNotFoundError as e:
        PREDICTION_ERRORS.labels(reason="missing_features").inc()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        PREDICTION_ERRORS.labels(reason="model_error").inc()
        logger.exception("Prediction failed for entity_id=%s", entity_id)
        raise HTTPException(status_code=500, detail="prediction failed")

    return PredictResponse(
        prediction=label,
        probability=proba,
        model_version=loader.version or "unknown",
        timestamp=datetime.now(timezone.utc).isoformat(),
        features=raw_values if explain else None,
    )


# Endpoints
@app.get("/health")
def health(loader: ModelLoader = Depends(get_model_loader)) -> dict:
    return {"status": "healthy", "model_version": loader.version}


@app.post("/predict", response_model=PredictResponse, response_model_exclude_none=True)
def predict(
    req: PredictRequest,
    loader: ModelLoader = Depends(get_model_loader),
    fc: FeatureClient = Depends(get_feature_client),
) -> PredictResponse:
    return _do_predict(req.entity_id, loader, fc, explain=False)


@app.get("/predict/{entity_id}", response_model=PredictResponse, response_model_exclude_none=True)
def predict_by_id(
    entity_id: int,
    explain: bool = Query(False, description="Include raw feature values in the response."),
    loader: ModelLoader = Depends(get_model_loader),
    fc: FeatureClient = Depends(get_feature_client),
) -> PredictResponse:
    return _do_predict(entity_id, loader, fc, explain=explain)


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=render(), media_type=CONTENT_TYPE)
