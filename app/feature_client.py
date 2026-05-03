"""Feast online-store wrapper for the inference service.

We use the Feast SDK (not direct Redis access) so that the entity-key
serialization, TTL, and feature-view contract stay consistent with what
`scripts/materialize_features.py` writes into Redis. Bypassing Feast
would silently desync the moment either side changes.
"""
from __future__ import annotations

import logging

import pandas as pd
from feast import FeatureStore

from app.metrics import FEAST_HITS, FEAST_MISSES

logger = logging.getLogger(__name__)

FEATURE_VIEW = "fraud_features"

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

FEATURE_REFS = [f"{FEATURE_VIEW}:{name}" for name in FEATURES]


class FeatureNotFoundError(Exception):
    """Raised when an entity has no materialized features in the online store."""


class FeatureClient:
    def __init__(self, repo_path: str) -> None:
        self.store = FeatureStore(repo_path=repo_path)

    def get_features(self, entity_id: int) -> tuple[pd.DataFrame, dict]:
        """Fetch features for a cc_num.

        Returns (model_input_df, raw_values_dict). The DataFrame has
        columns in the exact order the model was trained on; the dict
        is suitable for the `?explain=true` response body.
        """
        result = self.store.get_online_features(
            features=FEATURE_REFS,
            entity_rows=[{"cc_num": int(entity_id)}],
        ).to_dict()

        values = {name: result.get(name, [None])[0] for name in FEATURES}

        if any(v is None for v in values.values()):
            FEAST_MISSES.inc()
            missing = [name for name, v in values.items() if v is None]
            raise FeatureNotFoundError(
                f"No features materialized for cc_num={entity_id} "
                f"(missing: {missing})"
            )

        FEAST_HITS.inc()
        df = pd.DataFrame([values], columns=FEATURES)
        return df, values
