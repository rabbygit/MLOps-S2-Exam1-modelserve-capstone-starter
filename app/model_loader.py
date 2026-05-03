"""Loads the fraud-detection model from the MLflow Model Registry.

Uses the `sklearn` flavor (not `pyfunc`) so that `predict_proba` survives
the round-trip — the API needs the probability, not just the label.
"""
from __future__ import annotations

import logging
from typing import Optional

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.tracking import MlflowClient

from app.metrics import MODEL_VERSION_INFO

logger = logging.getLogger(__name__)


class ModelLoader:
    def __init__(self, tracking_uri: str, model_name: str, stage: str) -> None:
        self.tracking_uri = tracking_uri
        self.model_name = model_name
        self.stage = stage
        self.model = None
        self.version: Optional[str] = None

    def load(self) -> None:
        """Resolve the current stage version and load the sklearn estimator."""
        mlflow.set_tracking_uri(self.tracking_uri)
        client = MlflowClient(tracking_uri=self.tracking_uri)

        versions = client.get_latest_versions(self.model_name, stages=[self.stage])
        if not versions:
            raise RuntimeError(
                f"No '{self.stage}' version found for model '{self.model_name}'. "
                "Run `python training/train.py` first."
            )
        self.version = versions[0].version

        uri = f"models:/{self.model_name}/{self.stage}"
        logger.info("Loading model from %s (v%s)", uri, self.version)
        self.model = mlflow.sklearn.load_model(uri)

        MODEL_VERSION_INFO.labels(version=self.version).set(1)

    def predict(self, features: pd.DataFrame) -> tuple[int, float]:
        """Return (label, fraud_probability) for a single-row feature frame."""
        if self.model is None:
            raise RuntimeError("Model not loaded — call load() first.")
        proba = float(self.model.predict_proba(features)[0, 1])
        label = int(proba >= 0.5)
        return label, proba
