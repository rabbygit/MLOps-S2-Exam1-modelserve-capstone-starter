"""End-to-end Feast online lookup smoke test.

Reads sample_request.json, asks Feast for the entity's features, and
prints them. Useful as a fast 'is the pipeline working?' check after
running materialize_features.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from pprint import pprint

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

from feast import FeatureStore  # noqa: E402

FEATURE_REFS = [
    "fraud_features:amt",
    "fraud_features:lat",
    "fraud_features:long",
    "fraud_features:city_pop",
    "fraud_features:merch_lat",
    "fraud_features:merch_long",
    "fraud_features:hour",
    "fraud_features:day_of_week",
    "fraud_features:month",
    "fraud_features:age",
    "fraud_features:category_code",
    "fraud_features:gender_code",
]


def main() -> None:
    sample_path = REPO_ROOT / "training" / "sample_request.json"
    sample = json.loads(sample_path.read_text())
    entity_id = int(sample["entity_id"])

    store = FeatureStore(repo_path=str(REPO_ROOT / "feast_repo"))
    result = store.get_online_features(
        features=FEATURE_REFS,
        entity_rows=[{"cc_num": entity_id}],
    ).to_dict()

    print(f"cc_num={entity_id}")
    pprint(result)

    if result.get("amt", [None])[0] is None:
        raise SystemExit(
            "No features found for this entity. Did you run "
            "scripts/materialize_features.py?"
        )


if __name__ == "__main__":
    main()
