"""Fraud-detection training script.

Loads fraudTrain.csv, engineers a small numeric feature set, trains a
RandomForest baseline, logs to MLflow, registers under MODEL_NAME, and
promotes to Production.

Also writes (consumed by Feast and the API):
    training/features.parquet     one row per cc_num (latest event)
    training/sample_request.json  a valid POST /predict body
"""
from __future__ import annotations

import json
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root before reading any os.environ values.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore")

# Config (override via env)
DATA_PATH = Path(os.environ.get("FRAUD_DATA_PATH", "fraud-detection/fraudTrain.csv"))
SAMPLE_SIZE = int(os.environ.get("SAMPLE_SIZE", "200000"))
RANDOM_STATE = 42

MODEL_NAME = os.environ.get("MODEL_NAME", "fraud-detector")
MODEL_STAGE = os.environ.get("MODEL_STAGE", "Production")
TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT_NAME = os.environ.get("MLFLOW_EXPERIMENT_NAME", "fraud-detection")

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURES_OUT = REPO_ROOT / "training" / "features.parquet"
SAMPLE_REQUEST_OUT = REPO_ROOT / "training" / "sample_request.json"

FEATURES = [
    "amt",
    "lat",
    "long",
    "city_pop",
    "merch_lat",
    "merch_long",
    "hour",
    "day_of_week",
    "month",
    "age",
    "category_code",
    "gender_code",
]


# Steps
def load_and_engineer(path: Path) -> pd.DataFrame:
    """Load fraudTrain.csv and engineer a purely numeric feature set."""
    df = pd.read_csv(path)
    if SAMPLE_SIZE and len(df) > SAMPLE_SIZE:
        df = df.sample(n=SAMPLE_SIZE, random_state=RANDOM_STATE).reset_index(drop=True)

    df["trans_date_trans_time"] = pd.to_datetime(df["trans_date_trans_time"])
    df["dob"] = pd.to_datetime(df["dob"])

    df["hour"] = df["trans_date_trans_time"].dt.hour.astype("int64")
    df["day_of_week"] = df["trans_date_trans_time"].dt.dayofweek.astype("int64")
    df["month"] = df["trans_date_trans_time"].dt.month.astype("int64")
    df["age"] = ((df["trans_date_trans_time"] - df["dob"]).dt.days // 365).astype("int64")
    df["category_code"] = df["category"].astype("category").cat.codes.astype("int64")
    df["gender_code"] = (df["gender"] == "M").astype("int64")
    df["city_pop"] = df["city_pop"].astype("int64")
    return df


def train_model(df: pd.DataFrame) -> tuple[RandomForestClassifier, dict, dict]:
    """Train a RandomForest baseline; return (clf, params, metrics)."""
    X = df[FEATURES]
    y = df["is_fraud"].astype(int)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )

    params = {
        "model_type": "RandomForestClassifier",
        "n_estimators": 150,
        "max_depth": 12,
        "class_weight": "balanced",
        "random_state": RANDOM_STATE,
        "n_jobs": -1,
        "sample_size": len(df),
    }

    clf = RandomForestClassifier(
        n_estimators=params["n_estimators"],
        max_depth=params["max_depth"],
        class_weight=params["class_weight"],
        random_state=params["random_state"],
        n_jobs=params["n_jobs"],
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]
    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, y_proba)),
    }
    return clf, params, metrics


def export_feast_artifacts(df: pd.DataFrame) -> int:
    """One row per cc_num (latest event). Feast materializes from this."""
    feature_df = (
        df.sort_values("trans_date_trans_time")
        .drop_duplicates("cc_num", keep="last")
        .loc[:, ["cc_num"] + FEATURES + ["trans_date_trans_time"]]
        .rename(columns={"trans_date_trans_time": "event_timestamp"})
        .copy()
    )
    feature_df["event_timestamp"] = pd.to_datetime(feature_df["event_timestamp"]).dt.tz_localize(None)
    feature_df["created"] = datetime.now(timezone.utc).replace(tzinfo=None)

    FEATURES_OUT.parent.mkdir(parents=True, exist_ok=True)
    feature_df.to_parquet(FEATURES_OUT, index=False)

    sample_cc = int(feature_df["cc_num"].iloc[0])
    SAMPLE_REQUEST_OUT.write_text(json.dumps({"entity_id": sample_cc}, indent=2))
    return len(feature_df)


def promote_latest_to_stage(client: MlflowClient, name: str, stage: str) -> str:
    versions = client.search_model_versions(f"name='{name}'")
    latest = max(versions, key=lambda v: int(v.version))
    client.transition_model_version_stage(
        name=name,
        version=latest.version,
        stage=stage,
        archive_existing_versions=True,
    )
    return latest.version


# Entry point
def main() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(
            f"Dataset not found at {DATA_PATH}. Download fraudTrain.csv from "
            "https://www.kaggle.com/datasets/kartik2112/fraud-detection "
            f"and place it at {DATA_PATH}."
        )

    print(f"Loading {DATA_PATH} ...")
    df = load_and_engineer(DATA_PATH)
    print(f"Working with {len(df):,} rows.")

    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run() as run:
        clf, params, metrics = train_model(df)

        mlflow.log_params(params)
        mlflow.log_param("features", ",".join(FEATURES))
        for k, v in metrics.items():
            mlflow.log_metric(k, v)
        print("Test metrics:", metrics)

        mlflow.sklearn.log_model(
            clf,
            artifact_path="model",
            registered_model_name=MODEL_NAME,
            input_example=df[FEATURES].head(2),
        )
        print(f"MLflow run: {run.info.run_id}")

    version = promote_latest_to_stage(MlflowClient(), MODEL_NAME, MODEL_STAGE)
    print(f"Promoted {MODEL_NAME} v{version} -> {MODEL_STAGE}.")

    rows = export_feast_artifacts(df)
    print(f"Wrote {rows:,} rows to {FEATURES_OUT.relative_to(REPO_ROOT)}")
    print(f"Wrote sample request to {SAMPLE_REQUEST_OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
