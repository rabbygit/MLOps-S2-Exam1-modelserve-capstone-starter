"""Apply the Feast schema and push offline features into Redis online store.

Single command for the user — does both `feast apply` (registry) and
`feast materialize` (Redis push) in one shot. Reads .env automatically.

Run order:
    1. python training/train.py        (creates features.parquet)
    2. python scripts/materialize_features.py
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

from feast import FeatureStore  # noqa: E402  (imports after load_dotenv)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("materialize")


def import_feature_definitions():
    """Load feast_repo/feature_definitions.py without making it a package."""
    fdef_path = REPO_ROOT / "feast_repo" / "feature_definitions.py"
    spec = importlib.util.spec_from_file_location("feature_definitions", fdef_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def main() -> None:
    fdef = import_feature_definitions()

    repo_path = REPO_ROOT / "feast_repo"
    log.info("Loading Feast store from %s", repo_path)

    try:
        store = FeatureStore(repo_path=str(repo_path))
    except Exception:
        log.exception("Failed to load Feast store at %s", repo_path)
        sys.exit(1)

    log.info("Applying schema (entity=cc_num, feature_view=fraud_features)")
    store.apply([fdef.cc_num, fdef.fraud_features])

    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(days=365 * 10)
    log.info("Materializing features in window [%s, %s]", start, end)

    try:
        store.materialize(start_date=start, end_date=end)
    except Exception:
        log.exception("Materialization failed")
        sys.exit(1)

    log.info("Done. Verify with: redis-cli keys '*'")


if __name__ == "__main__":
    main()
