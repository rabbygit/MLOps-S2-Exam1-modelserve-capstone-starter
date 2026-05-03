"""Prometheus metrics for the inference service.

A dedicated CollectorRegistry is used (instead of the global default) so
that test runs and uvicorn reloads can re-import this module without
hitting "Duplicated timeseries" errors.
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


REGISTRY = CollectorRegistry()

PREDICTION_REQUESTS = Counter(
    "prediction_requests_total",
    "Total number of prediction requests received.",
    registry=REGISTRY,
)

PREDICTION_DURATION = Histogram(
    "prediction_duration_seconds",
    "End-to-end prediction latency: feature fetch + model inference.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

PREDICTION_ERRORS = Counter(
    "prediction_errors_total",
    "Number of failed prediction requests, labeled by failure reason.",
    labelnames=("reason",),
    registry=REGISTRY,
)

MODEL_VERSION_INFO = Gauge(
    "model_version_info",
    "Currently served model version — set once on startup.",
    labelnames=("version",),
    registry=REGISTRY,
)

FEAST_HITS = Counter(
    "feast_online_store_hits_total",
    "Successful feature lookups from the Feast online store.",
    registry=REGISTRY,
)

FEAST_MISSES = Counter(
    "feast_online_store_misses_total",
    "Empty or failed feature lookups from the Feast online store.",
    registry=REGISTRY,
)

CONTENT_TYPE = CONTENT_TYPE_LATEST


def render() -> bytes:
    """Serialize the registry into Prometheus text-exposition format."""
    return generate_latest(REGISTRY)
