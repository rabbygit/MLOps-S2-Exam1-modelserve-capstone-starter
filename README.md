# ModelServe

> MLOps with Cloud Season 2 — Capstone Exam

A production-grade ML serving platform built around a fraud-detection model.
The model is trained on the Kaggle fraud-detection dataset, registered in
MLflow, served from FastAPI, and looks up online features from Redis through
Feast. Sessions 1-2 deliver the local stack and inference API; Sessions 3-4
harden containerization (multi-stage Dockerfile, non-root user, < 800 MB image)
and add observability (Prometheus + Grafana with provisioned dashboards and
alert rules). Sessions 5-7 provision AWS infrastructure (VPC, EC2, ECR, S3,
IAM) via Pulumi, with MLflow artifacts in S3 for durability. Sessions 8-9
add a GitHub Actions CI/CD pipeline (test → lint → build-scan-push → deploy
with `/health` verification, plus rollback via `workflow_dispatch`).

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

### 6. Build and bring up the FastAPI inference service

> **Prerequisites — do not skip:** steps 4 and 5 above must have run
> successfully. The API container loads the model from the MLflow
> Registry on startup (step 4) and reads `feast_repo/data/registry.db`
> from inside the image (step 5). If you start the api before those
> exist, it will crash-loop with `RuntimeError: No 'Production' version
> found ...` or a Feast registry error.

The API image bakes in `feast_repo/data/registry.db` and
`training/features.parquet` at build time, so any retrain or
re-materialize on the host needs a fresh `build` to take effect:

```bash
docker compose build api
docker compose up -d api
docker compose ps              # api should report (healthy) within ~30s
docker compose logs -f api     # watch the lifespan: model load + Feast init
```

Smoke test all four endpoints:

```bash
# Liveness — returns {"status": "healthy", "model_version": "<v>"}
curl http://localhost:8000/health

# Predict via POST (uses the sample body written by train.py)
curl -X POST http://localhost:8000/predict \
     -H 'content-type: application/json' \
     -d @training/sample_request.json

# Predict via GET — ?explain=true also returns the raw feature values
ENTITY_ID=$(python -c 'import json; print(json.load(open("training/sample_request.json"))["entity_id"])')
curl "http://localhost:8000/predict/${ENTITY_ID}?explain=true"

# Prometheus metrics
curl http://localhost:8000/metrics | head -30
```

OpenAPI docs are at <http://localhost:8000/docs>.

### 7. Bring up Prometheus and Grafana

Prometheus and Grafana come up alongside everything else with `docker compose
up -d` — no extra step. They're listed separately here because the
verification flow is different from the API:

```bash
docker compose up -d                # brings up prometheus + grafana too
docker compose ps                   # six services, all (healthy)
```

Prometheus targets page — both `prometheus` and `modelserve-api` should be
green / UP:

```bash
open http://localhost:9090/targets
```

Alerts page — four rules (APIServiceDown, HighPredictionLatencyP95,
HighPredictionErrorRate, FeastHighMissRate) should be listed:

```bash
open http://localhost:9090/alerts
```

Grafana — login is `admin` / `admin` (or whatever
`GF_SECURITY_ADMIN_PASSWORD` is set to in `.env`). The
**ModelServe — Inference Service** dashboard auto-loads under the General
folder via provisioning:

```bash
open http://localhost:3000
```

To populate the dashboard with data, hammer `/predict` for a minute:

```bash
for i in $(seq 1 200); do
  curl -s -X POST http://localhost:8000/predict \
    -H 'content-type: application/json' \
    -d @training/sample_request.json > /dev/null
done
```

You should see Total Requests jump, Request Rate spike, and the latency
percentile panel populate.

### TL;DR — bring everything up at once (after first-time setup)

Once steps 1-5 have run on this machine at least once, restarting the
whole stack is a one-liner. The compose dependency graph
(`api → mlflow → postgres`, `api → redis`, `grafana → prometheus`)
brings every service up in the right order:

```bash
docker compose up -d
docker compose ps     # all six services should be (healthy)
```

---

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness probe — returns `{"status": "healthy", "model_version": "<v>"}` |
| `POST` | `/predict` | Predict on `{"entity_id": <cc_num>}`; returns prediction + probability + version + timestamp |
| `GET`  | `/predict/<id>?explain=true` | Same as POST `/predict` plus the feature values that were used |
| `GET`  | `/metrics` | Prometheus metrics text — scraped every 15 s by the `prometheus` container |

---

## Observability (Sessions 3-4)

### URLs

| Service | URL | Login |
|---|---|---|
| FastAPI | <http://localhost:8000/docs> | — |
| MLflow | <http://localhost:5000> | — |
| Prometheus | <http://localhost:9090> | — |
| Grafana | <http://localhost:3000> | `admin` / `${GF_SECURITY_ADMIN_PASSWORD:-admin}` |

### Metrics exposed by the API

Defined in [`app/metrics.py`](app/metrics.py); registered in `app/main.py` at the `/metrics` route.

| Metric | Type | Notes |
|---|---|---|
| `prediction_requests_total` | Counter | One increment per `/predict` call |
| `prediction_duration_seconds` | Histogram | Buckets cover 5 ms → 5 s; latency percentiles come from `_bucket` series |
| `prediction_errors_total{reason}` | Counter | `reason` label is `missing_features` (404) or `model_error` (500) |
| `model_version_info{version}` | Gauge | Set once at startup with the loaded version as a label |
| `feast_online_store_hits_total` | Counter | Incremented when Feast returns a full feature row |
| `feast_online_store_misses_total` | Counter | Incremented when at least one feature is `None` |

### Provisioned Grafana dashboard

`monitoring/grafana/dashboards/modelserve.json` is loaded automatically via
the file provider at `monitoring/grafana/provisioning/dashboards/dashboard.yml`.
Eight panels cover: Model Version, Total Requests, Total Errors, Feast Hit
Ratio, Request Rate, Error Rate (broken down by reason), Latency
p50 / p95 / p99, and Hits vs Misses (stacked).

### Alert rules

`monitoring/prometheus/alerts.yml` defines four rules:

| Alert | Severity | Trigger |
|---|---|---|
| `APIServiceDown` | critical | `up{job="modelserve-api"} == 0` for 1 m |
| `HighPredictionLatencyP95` | warning | p95 latency > 500 ms for 5 m |
| `HighPredictionErrorRate` | warning | error rate > 5% for 2 m (with traffic floor to avoid flapping) |
| `FeastHighMissRate` | warning | Feast miss ratio > 20% for 5 m |

To trigger `HighPredictionErrorRate` on demand for a demo:

```bash
for i in $(seq 1 100); do
  curl -s -X POST http://localhost:8000/predict \
    -H 'content-type: application/json' \
    -d '{"entity_id": 0}' > /dev/null
done
# Wait ~3 minutes, then refresh http://localhost:9090/alerts
```

### Reload Prometheus rules without restart

Edit `monitoring/prometheus/alerts.yml`, then:

```bash
docker compose kill -s SIGHUP prometheus
# or:
curl -X POST http://localhost:9090/-/reload
```

`--web.enable-lifecycle` is set on the prometheus service so this works.

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

## GitHub Secrets (Sessions 8-9)

The CI/CD workflow ([`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)) reads four
secrets. All four come straight out of `pulumi stack output` after a
successful `pulumi up`, so refreshing them is one command per secret.

| Secret | Source | Purpose |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | `pulumi stack output ci_access_key_id` | Auth for `build-and-push` (ECR push) and `deploy` (ECR login proxy) |
| `AWS_SECRET_ACCESS_KEY` | `pulumi stack output ci_secret_access_key --show-secrets` | Same |
| `EC2_HOST` | `pulumi stack output ec2_public_ip` | Where the `deploy` job SSHes to |
| `EC2_SSH_KEY` | `cat infrastructure/keys/modelserve` | Private key for the SSH session (the `.pub` is already on the EC2) |

### Setting them in one shot

After every `pulumi up` (because IPs and access keys are fresh):

```bash
cd infrastructure
gh secret set AWS_ACCESS_KEY_ID -b "$(pulumi stack output ci_access_key_id)"
gh secret set AWS_SECRET_ACCESS_KEY -b "$(pulumi stack output ci_secret_access_key --show-secrets)"
gh secret set EC2_HOST -b "$(pulumi stack output ec2_public_ip)"
gh secret set EC2_SSH_KEY -b "$(cat keys/modelserve)"
```

### Triggering the pipeline

Empty commit + push is the simplest trigger — pushes to `main` run the full pipeline:

```bash
git commit --allow-empty -m "deploy"
git push origin main
```

For a rollback (deploy a previous SHA's image without rebuilding):

```bash
gh workflow run deploy.yml -f deploy_sha=<old-commit-sha>
```

The image must already be in ECR from a prior successful `build-and-push`. The
`build-and-push` job tags every image with both `:<sha>` and `:latest`, so any
green build's SHA is rollback-eligible.

---

## Common Operations

| Task | Command |
|---|---|
| Bring data plane up (first-time setup) | `docker compose up -d postgres redis mlflow` |
| Bring everything up (after train + materialize) | `docker compose up -d` |
| Rebuild API image after retrain or re-materialize | `docker compose build api && docker compose up -d api` |
| Tear stack down (keep data) | `docker compose down` |
| Tear stack down (wipe volumes — full reset) | `docker compose down -v` |
| Re-train and re-register | `python training/train.py` |
| Re-apply schema + materialize | `python scripts/materialize_features.py` |
| Smoke test online lookup (host) | `python scripts/verify_features.py` |
| Smoke test API health | `curl http://localhost:8000/health` |
| Smoke test API predict | `curl -X POST http://localhost:8000/predict -H 'content-type: application/json' -d @training/sample_request.json` |
| Tail API logs | `docker compose logs -f api` |
| List Redis feature keys | `redis-cli keys '*' \| head` |
| Reload Prometheus rules | `docker compose kill -s SIGHUP prometheus` |
| Open Prometheus targets | `open http://localhost:9090/targets` |
| Open Grafana | `open http://localhost:3000` |
| Tail Grafana provisioning logs | `docker compose logs grafana \| grep -iE 'provision\|datasource\|dashboard'` |
| Verify image size (< 800 MB) | `docker images mlops-s2-exam1-modelserve-capstone-starter-api --format '{{.Size}}'` |
| Verify api runs as non-root | `docker compose exec api id` |
| Run unit tests | `pytest app/tests/ -v` |
| Trigger CI deploy | `git commit --allow-empty -m deploy && git push origin main` |
| Watch CI run | `gh run watch` |
| Rollback to a prior SHA | `gh workflow run deploy.yml -f deploy_sha=<old-sha>` |

---

## Project Layout

```
modelserve/
├── app/                                FastAPI inference service (Session 2)
│   ├── main.py                         endpoints + lifespan
│   ├── model_loader.py                 MLflow Registry client
│   ├── feature_client.py               Feast online lookup wrapper
│   └── metrics.py                      Prometheus counters/histograms
├── training/                           train.py + features.parquet + sample_request.json
├── feast_repo/                         Feast feature definitions and registry
├── scripts/                            materialize + verify helpers
├── monitoring/                         Prometheus + Grafana (Sessions 3-4)
│   ├── prometheus/
│   │   ├── prometheus.yml              scrape config + rule_files
│   │   └── alerts.yml                  4 alert rules
│   └── grafana/
│       ├── provisioning/
│       │   ├── datasources/prometheus.yml   auto-wires Prometheus as datasource
│       │   └── dashboards/dashboard.yml     file-provider config
│       └── dashboards/modelserve.json  the actual dashboard
├── infrastructure/                     Pulumi program (Sessions 5-7)
│   ├── storage.py                      S3 bucket
│   ├── registry.py                     ECR repository
│   ├── iam.py                          CI IAM user
│   ├── network.py                      VPC + subnet + IGW + RT + SG
│   ├── keypair.py                      EC2 SSH key pair
│   ├── instance_role.py                EC2 IAM role + instance profile
│   ├── compute.py                      EC2 instance
│   ├── user_data.sh                    First-boot bootstrap script
│   └── __main__.py                     Pulumi entry point + stack outputs
├── docs/
│   ├── ARCHITECTURE.md                 5 ADRs + runbook + known limits
│   └── DEMO.md                         60-min live demo runbook
├── .github/workflows/
│   └── deploy.yml                      CI/CD pipeline (Sessions 8-9)
├── docker-compose.yml                  Local stack (6 services)
├── Dockerfile                          FastAPI image (multi-stage, non-root, < 800 MB)
├── Dockerfile.mlflow                   MLflow tracking server image
├── requirements.txt                    Host venv (full mlflow, pytest, etc.)
├── requirements-api.txt                API runtime deps (mlflow-skinny, no boto3)
├── .dockerignore                       Trims build context
└── .env.example                        Host-side env template
```

---

## Engineering Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full architecture: diagrams, 5 ADRs, CI/CD pipeline shape, runbook, known limitations
- [`docs/DEMO.md`](docs/DEMO.md) — 60-minute live-demo runbook (cold start through teardown)

---

*MLOps with Cloud Season 2 — Capstone: ModelServe | Poridhi.io*
