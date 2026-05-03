# ModelServe

> MLOps with Cloud Season 2 — Capstone Exam

A production-grade ML serving platform built around a fraud-detection model.
The model is trained on the Kaggle fraud-detection dataset, registered in
MLflow, served from FastAPI, and looks up online features from Redis through
Feast. Sessions 1-2 deliver the local stack; later sessions add observability
(Prometheus + Grafana), AWS infrastructure (Pulumi), and CI/CD (GitHub Actions).

---

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose v2)
- **Python 3.10 or 3.11** — `pyarrow` and `numpy` wheels are not yet stable on 3.13/3.14
- **Git**
- About **800 MB free disk** for the Kaggle dataset and Docker volumes
- (Optional) **`redis-cli`** for poking at the online store — `brew install redis` on macOS

---

## Dataset

This project uses the [Credit Card Transactions Fraud Detection](https://www.kaggle.com/datasets/kartik2112/fraud-detection) dataset (Sparkov-generated synthetic transactions). Entity key for online lookups is `cc_num`.

End state on disk (folder is gitignored):

```
fraud-detection/
├── fraudTrain.csv   (~350 MB, ~1.3M rows — used by training/train.py)
└── fraudTest.csv    (~150 MB — not used in S1, kept for completeness)
```

### Option A — `curl` from the public endpoint (simplest)

```bash
# Download the zip (no auth needed for this dataset)
curl -L -o ~/Downloads/fraud-detection.zip \
    https://www.kaggle.com/api/v1/datasets/download/kartik2112/fraud-detection

# Unzip into the project's fraud-detection/ folder
mkdir -p fraud-detection
unzip -d fraud-detection ~/Downloads/fraud-detection.zip
```

### Verify

```bash
ls -lh fraud-detection/
# fraudTrain.csv  ~ 335M
# fraudTest.csv   ~ 144M
head -1 fraud-detection/fraudTrain.csv
# trans_date_trans_time,cc_num,merchant,category,amt,first,last,gender,...
```

---

## Quick Start (Local Development)

From a fresh clone you should reach a healthy stack in under 15 minutes.

### 1. Clone and configure

```bash
git clone <your-fork-url> modelserve
cd modelserve
cp .env.example .env       # adjust values if you like; defaults work
```

### 2. Set up a Python venv on the host

The host runs `train.py` and the Feast scripts. Containers have their own copies of these dependencies — the venv is just for host iteration.

```bash
python3.10 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

Sanity check:

```bash
python -c "import mlflow, feast, sklearn, pandas; print('ok')"
```

### 3. Bring up the data plane

```bash
docker compose up -d postgres redis mlflow
docker compose ps      # all three should report (healthy) within ~30s
```

MLflow UI is at <http://localhost:5000>.

### 4. Train the model and register it in MLflow

```bash
python training/train.py
```

This:
- Loads `fraud-detection/fraudTrain.csv`, samples to 200k rows
- Trains a RandomForest baseline (AUC ≈ 0.97)
- Logs params + metrics to MLflow
- Registers the model as `fraud-detector` and promotes the new version to `Production`
- Writes `training/features.parquet` and `training/sample_request.json`

Verify in the MLflow UI: **Models → fraud-detector → version N — Stage: Production**.

### 5. Apply the Feast schema and push features into Redis

```bash
python scripts/materialize_features.py
```

This calls `store.apply([cc_num, fraud_features])` (writes `feast_repo/data/registry.db`) then `store.materialize(...)` (writes per-entity feature rows to Redis).

Verify the online store has data:

```bash
python scripts/verify_features.py
```

Expected output: real numbers for `amt`, `lat`, `long`, etc. — not `[None]`.

### 6. (Sessions 2+) Bring up the FastAPI service

Coming next:

```bash
docker compose up -d api
curl http://localhost:8000/health
curl -X POST http://localhost:8000/predict -d @training/sample_request.json
```

---

## REST Endpoints

> Implemented in Session 2.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness probe — returns `{"status": "healthy", "model_version": "<v>"}` |
| `POST` | `/predict` | Predict on `{"entity_id": <cc_num>}`; returns prediction + probability + version + timestamp |
| `GET`  | `/predict/<id>?explain=true` | Same as POST `/predict` plus the feature values that were used |
| `GET`  | `/metrics` | Prometheus metrics text |

---

## Environment Variables

All variables live in `.env` (gitignored). See [`.env.example`](.env.example) for the canonical list.

| Variable | Consumer | Purpose |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | docker compose | Credentials for the MLflow backend Postgres |
| `MLFLOW_TRACKING_URI` | host scripts (`train.py`) | Where to log experiments — `http://localhost:5000` from host |
| `MLFLOW_EXPERIMENT_NAME` | `train.py` | MLflow experiment name (default `fraud-detection`) |
| `MODEL_NAME` | `train.py`, FastAPI | Registered model name in MLflow Registry |
| `MODEL_STAGE` | `train.py`, FastAPI | Stage to load (`Production`) |
| `FEAST_REPO_PATH` | host scripts | Path to the `feast_repo/` directory |
| `REDIS_CONNECTION_STRING` | host scripts, FastAPI | Redis host:port — `localhost:6379` from host, `redis:6379` in the docker network |
| `FRAUD_DATA_PATH` | `train.py` | Path to `fraudTrain.csv` |
| `SAMPLE_SIZE` | `train.py` | Rows to sample for training (default 200k) |
| `AWS_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Pulumi (Sessions 5-7) | AWS sandbox credentials |
| `GF_SECURITY_ADMIN_PASSWORD` | Grafana (Sessions 3-4) | Admin password for the Grafana UI |

`.env` has two readers:
1. **Host scripts** — `train.py`, `scripts/materialize_features.py`, `scripts/verify_features.py` — use `python-dotenv` to load it on import.
2. **`docker compose`** — auto-reads it for `${VAR}` substitution in `docker-compose.yml`. Hostname-dependent values inside containers (e.g. `MLFLOW_TRACKING_URI=http://mlflow:5000`) are set in each service's `environment:` block, **not** read from `.env`.

---

## GitHub Secrets

> Populated in Sessions 5-9 when CI/CD comes online.

| Secret | Purpose |
|---|---|
| `AWS_ACCESS_KEY_ID` | Pulumi authentication to AWS |
| `AWS_SECRET_ACCESS_KEY` | Pulumi authentication to AWS |
| `SSH_PUBLIC_KEY` | Injected into the EC2 key pair via Pulumi |
| `PULUMI_ACCESS_TOKEN` | Pulumi Service backend (or use `--local`) |

---

## Common Operations

| Task | Command |
|---|---|
| Bring stack up | `docker compose up -d postgres redis mlflow` |
| Tear stack down (keep data) | `docker compose down` |
| Tear stack down (wipe volumes) | `docker compose down -v` |
| Re-train and re-register | `python training/train.py` |
| Re-apply schema + materialize | `python scripts/materialize_features.py` |
| Smoke test online lookup | `python scripts/verify_features.py` |
| List Redis feature keys | `redis-cli keys '*' \| head` |

---

## Project Layout

```
modelserve/
├── app/                  FastAPI inference service (Session 2)
├── training/             train.py + features.parquet + sample_request.json
├── feast_repo/           Feast feature definitions and registry
├── scripts/              materialize + verify helpers
├── infrastructure/       Pulumi program (Sessions 5-7)
├── monitoring/           Prometheus + Grafana config (Sessions 3-4)
├── docs/                 ARCHITECTURE.md + diagrams
├── .github/workflows/    CI/CD pipeline (Sessions 8-9)
├── docker-compose.yml    Local stack
├── Dockerfile            FastAPI image
├── Dockerfile.mlflow     MLflow tracking server image
└── .env.example          Host-side env template
```

---

## Engineering Documentation

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full architecture documentation, ADRs, runbook, and known limitations.

---

*MLOps with Cloud Season 2 — Capstone: ModelServe | Poridhi.io*
