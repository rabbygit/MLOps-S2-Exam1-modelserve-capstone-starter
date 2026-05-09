"""Feast entities, source, and feature view for the fraud-detection model.

The schema here has to match exactly what train.py writes to
features.parquet and what app/feature_client.py requests at inference
time. If these three drift, Feast silently returns [None] for the
missing columns.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float64, Int64


PARQUET_PATH = str(
    (Path(__file__).resolve().parent.parent / "training" / "features.parquet")
)

# Entity. Join key for online lookups.
cc_num = Entity(
    name="cc_num",
    join_keys=["cc_num"],
    description="Credit card number, the join key for transaction features.",
)

# Source. Where the offline (training-time) features live.
fraud_source = FileSource(
    name="fraud_features_source",
    path=PARQUET_PATH,
    timestamp_field="event_timestamp",
    created_timestamp_column="created",
)

# FeatureView. What the online store holds and serves.
fraud_features = FeatureView(
    name="fraud_features",
    entities=[cc_num],
    ttl=timedelta(days=365 * 5),
    schema=[
        Field(name="amt", dtype=Float64),
        Field(name="lat", dtype=Float64),
        Field(name="long", dtype=Float64),
        Field(name="city_pop", dtype=Int64),
        Field(name="merch_lat", dtype=Float64),
        Field(name="merch_long", dtype=Float64),
        Field(name="hour", dtype=Int64),
        Field(name="day_of_week", dtype=Int64),
        Field(name="month", dtype=Int64),
        Field(name="age", dtype=Int64),
        Field(name="category_code", dtype=Int64),
        Field(name="gender_code", dtype=Int64),
    ],
    source=fraud_source,
    online=True,
)
