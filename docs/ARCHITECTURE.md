# ModelServe — Engineering Documentation

> Standalone reference for the system. Reading this end-to-end should be
> enough to understand and reproduce ModelServe without opening the code.
> The README is the quick-start; this is the why.

---

## 1. System Overview

ModelServe is a production-shaped ML serving platform built around a fraud-detection
model trained on the Sparkov synthetic transactions dataset
([Kaggle: kartik2112/fraud-detection](https://www.kaggle.com/datasets/kartik2112/fraud-detection)).
The core capability is a `POST /predict` endpoint that takes a credit-card number,
fetches the cardholder's most recent feature snapshot from a Redis-backed online
feature store, runs it through a sklearn `RandomForestClassifier` loaded from the
MLflow Model Registry, and returns a fraud probability with the model version that
produced it. The system is wrapped in everything a real serving platform needs:
experiment tracking, a feature store, observability, and infrastructure-as-code.

The audience is the MLOps capstone TA grading the system, but the design choices
target a hypothetical platform team wanting to operate the model in production:
the deployment is reproducible (`pulumi up` from a fresh clone reaches a healthy
state), the failure modes are explicit (alerts cover service-down, latency, error
rate, feature-store miss rate), and the operational boundaries are documented
(this file's runbook). Model quality is intentionally de-emphasized — a baseline
RandomForest at AUC≈0.97 is fine; the rubric weights infrastructure, observability,
documentation, and CI/CD far above it.

The design philosophy is **simplicity over availability**: a single AWS EC2 instance
runs the entire compose stack. There is no horizontal scaling, no multi-AZ, no
load balancer. The trade-off is acknowledged (single point of failure) and is
appropriate for a sandbox-bounded demo. The component split is canonical:
PostgreSQL holds MLflow's experiment-tracking metadata, S3 holds MLflow's
artifacts (so model bytes survive `pulumi destroy`), Redis holds Feast's
materialized online features, and Prometheus + Grafana give the runtime view.
Pulumi (Python) provisions everything in AWS; GitHub Actions (S8-9) will
automate the deploy pipeline.

---

## 2. Architecture Diagrams

### 2.1 Local Development

`docker compose up -d` from the repo root brings everything up in one Docker
network on the developer's laptop. No AWS resources are touched.

```
Developer Laptop
═══════════════════════════════════════════════════════════════════
   Host browser ─────────────────────────┐
   curl ──────────────────────────────┐  │
                                      │  │
   ┌──────────────────────────────────┼──┼──────────────────────┐
   │  Docker network: modelserve      │  │                       │
   │                                  ▼  ▼                       │
   │  ┌──────────┐   ┌──────────┐   ┌─────────┐                 │
   │  │ postgres │   │  redis   │   │   api   │                 │
   │  │ :5432    │◄──┤  :6379   │◄──┤  :8000  │ ← /predict      │
   │  │ (volume) │   │ (volume) │   │         │ ← /metrics      │
   │  └────▲─────┘   └────▲─────┘   └────┬────┘                 │
   │       │              │              │                       │
   │       │ metadata     │ features     │ model lookup          │
   │       │              │              │                       │
   │  ┌────┴─────┐        │              ▼                       │
   │  │  mlflow  │        │         registry call                │
   │  │  :5000   │◄───────┼───────── via HTTP ──────►            │
   │  │ artifact │        │                                      │
   │  │ store:   │        │  ┌─────────────┐   ┌──────────────┐  │
   │  │ /ml...   │        └──┤ prometheus  │◄──┤   grafana    │◄─┐
   │  │ (volume) │           │  :9090      │   │   :3000      │  │
   │  └──────────┘           │  scrapes    │   │  dashboards  │  │
   │                         │  /metrics   │   │  alerts      │  │
   │                         └─────────────┘   └──────────────┘  │
   └─────────────────────────────────────────────────────────────┘
                                                                  │
   Host UI access (host browser hits localhost:<port>)            │
   ─ http://localhost:8000/docs   (FastAPI OpenAPI)               │
   ─ http://localhost:5000        (MLflow UI)                     │
   ─ http://localhost:3000        (Grafana, admin/admin) ─────────┘
   ─ http://localhost:9090        (Prometheus targets/alerts)

Volumes (persist across `down`, wiped by `down -v`):
   postgres_data   redis_data   mlflow_artifacts
   prometheus_data grafana_data
```

### 2.2 Production (AWS, single-EC2)

`pulumi up --yes` from `infrastructure/` provisions AWS resources and bootstraps
the EC2 host. The same `docker-compose.yml` runs there, with two env-var overrides
(`MLFLOW_DEFAULT_ARTIFACT_ROOT=s3://...`, `AWS_REGION=...`) appended to `.env` by
`user_data.sh`.

```
   ┌────────────────────────────────────────────────────────────────────┐
   │  Public internet                                                    │
   │                                                                     │
   │  TA's curl ──────► Demo URL: http://<ec2-public-ip>:8000            │
   │  TA's browser ───► Grafana:  http://<ec2-public-ip>:3000            │
   └─────────────────────────────────┬───────────────────────────────────┘
                                     │
                                     ▼
   ╔═════════════════════════════════════════════════════════════════════╗
   ║  AWS Account (region: ap-southeast-1)                                ║
   ║  ┌─────────────────────────────────────────────────────────────┐    ║
   ║  │  VPC 10.0.0.0/16                                            │    ║
   ║  │  ┌────────────────┐                                          │    ║
   ║  │  │ Internet GW    │                                          │    ║
   ║  │  └───────┬────────┘                                          │    ║
   ║  │          │ default route 0.0.0.0/0                          │    ║
   ║  │  ┌───────┴──────────────────────────────────────────────┐   │    ║
   ║  │  │ Public Subnet 10.0.1.0/24 (map_public_ip_on_launch)  │   │    ║
   ║  │  │                                                       │   │    ║
   ║  │  │  ┌─────────────────────────────────────────────────┐ │   │    ║
   ║  │  │  │  EC2 t3.small (modelserve-host)                  │ │   │    ║
   ║  │  │  │  Amazon Linux 2023, 30 GB gp3                    │ │   │    ║
   ║  │  │  │  user_data.sh bootstraps once on first boot:     │ │   │    ║
   ║  │  │  │   • install docker + python                      │ │   │    ║
   ║  │  │  │   • git clone repo                               │ │   │    ║
   ║  │  │  │   • download dataset (Kaggle, public endpoint)   │ │   │    ║
   ║  │  │  │   • train.py + materialize_features.py           │ │   │    ║
   ║  │  │  │   • docker compose build api && up               │ │   │    ║
   ║  │  │  │                                                  │ │   │    ║
   ║  │  │  │  Docker network "modelserve" (same as local):    │ │   │    ║
   ║  │  │  │   postgres │ redis │ mlflow │ api                │ │   │    ║
   ║  │  │  │   prometheus │ grafana                           │ │   │    ║
   ║  │  │  │                                                  │ │   │    ║
   ║  │  │  │  IAM Instance Profile: ec2-host-role             │ │   │    ║
   ║  │  │  │   ↳ ECR pull (scoped to modelserve-api repo)     │ │   │    ║
   ║  │  │  │   ↳ S3 r/w  (scoped to mlflow-artifacts bucket)  │ │   │    ║
   ║  │  │  │   ↳ delivered via IMDSv2, hop_limit=2            │ │   │    ║
   ║  │  │  └─────────────────────────────────────────────────┘ │   │    ║
   ║  │  └───────────────────────────────────────────────────────┘   │    ║
   ║  │                                                               │    ║
   ║  │  Security Group (ingress 0.0.0.0/0):                          │    ║
   ║  │   22 ssh │ 8000 api │ 3000 grafana │ 5000 mlflow │ 9090 prom  │    ║
   ║  └───────────────────────────────────────────────────────────────┘    ║
   ║                                                                       ║
   ║  Stateless / stateful resources outside the VPC:                      ║
   ║  ┌──────────────────────┐  ┌──────────────────────┐                  ║
   ║  │ S3: mlflow-artifacts │  │ ECR: modelserve-api  │                  ║
   ║  │  versioned, locked   │  │  scan-on-push        │                  ║
   ║  │  7d lifecycle expiry │  │  force_delete=True   │                  ║
   ║  │  (orphan cleanup)    │  │  (S8-9 will populate)│                  ║
   ║  └──────────▲───────────┘  └──────────────────────┘                  ║
   ║             │                                                          ║
   ║             │ MLflow artifact uploads via boto3 in mlflow container    ║
   ║             │ (creds from EC2 IAM role via IMDS)                       ║
   ║             │                                                          ║
   ║  ┌──────────┴───────────┐                                              ║
   ║  │ IAM: ci user (S5)    │  Provisioned for S8-9 GitHub Actions.        ║
   ║  │  ECR push perms      │  Access keys exported as Pulumi secrets.     ║
   ║  └──────────────────────┘                                              ║
   ╚═════════════════════════════════════════════════════════════════════╝

External dependencies (off-AWS):
   • GitHub: source repo cloned by user_data.sh
   • Kaggle: dataset downloaded once per cold-start (unauthenticated endpoint)
   • Docker Hub: postgres, redis, prometheus, grafana base images
```

### 2.3 What's the same vs. different between local and prod

| Component             | Local                            | Prod (EC2)                                          |
|-----------------------|----------------------------------|-----------------------------------------------------|
| `docker-compose.yml`  | same file                        | same file                                            |
| postgres              | local volume                     | local volume on EC2 (lost on `pulumi destroy`)       |
| redis                 | local volume                     | local volume on EC2                                  |
| mlflow artifacts      | local volume `/mlartifacts`      | **S3** via `MLFLOW_DEFAULT_ARTIFACT_ROOT=s3://...`   |
| api image             | `docker compose build api`       | `docker compose build api` (S8-9 → ECR pull)         |
| Prometheus / Grafana  | local volumes                    | local volumes on EC2                                 |

The only true topology divergence is the MLflow artifact destination. Postgres
and Redis are local-volume in both. This keeps the local development experience
fast (no S3 round-trips) while giving the prod path durable artifact storage.

---

## 3. Architecture Decision Records (ADRs)

### ADR-1: Single-EC2 deployment topology

**Context.** The exam offered three sample topologies (single AWS EC2,
Poridhi-VM-only, hybrid split) and explicitly noted that the rubric is
topology-neutral. We needed to pick one and defend it.

**Decision.** Run the entire `docker-compose.yml` (postgres, redis, mlflow, api,
prometheus, grafana) on a single AWS EC2 t3.small. No load balancer, no second
AZ, no separation between data plane and serving plane.

**Rationale.** The capstone's primary teaching goal is *operating the surrounding
infrastructure*, not building a horizontally-scaled service. A single-EC2 layout
exercises all the relevant Pulumi primitives (VPC, subnet, IGW, route table,
security group, EC2, key pair, IAM role + instance profile, ECR, S3) without
adding cross-host networking debugging. The compose stack is unchanged from the
local dev workflow, so a working `docker compose up` locally reproduces in prod
modulo two env var overrides.

**Trade-offs.** Single point of failure: if the EC2 dies, every component dies.
Resource contention on a 2 GB t3.small is real — the six containers share RAM
with system overhead. Mitigations available but not implemented: bump to
t3.medium (4 GB) if compose OOMs; switch to Strategy 3 (split mlflow + monitoring
to a second instance) if scaling becomes a real concern. Acceptable for the
sandbox-bounded demo lifecycle that ends with `pulumi destroy` after every
session.

### ADR-2: Build-on-EC2 in S5-7, ECR-pull deferred to CI in S8-9

**Context.** ECR is provisioned in S5 (with `force_delete=True` to satisfy the
"`pulumi destroy` cleans up" AC) but, prior to S8-9, has no images pushed to it.
The api container has to come from somewhere on the EC2.

**Decision.** Keep `docker compose build api` in `user_data.sh` for S5-7. In
S8-9, GitHub Actions will build once and push to ECR; `user_data.sh` will then
flip to `docker compose pull api` by setting `API_IMAGE=<ecr-url>:latest` in
`.env` before bringing services up.

**Rationale.** A manual `docker push` from the developer's laptop in S7 would be
a one-time bridge: the moment CI lands in S8-9, that manual step disappears. We
already prove the IAM scoping (the EC2 role has `ecr:GetAuthorizationToken` and
the pull-actions on the specific repo ARN) without exercising it. The compose
file is forward-compatible: `image: ${API_IMAGE:-modelserve-api:local}` defaults
to the local-build tag in S5-7 and accepts a CI-set ECR URL in S8-9 with no
compose changes.

**Trade-offs.** Cold-start time on EC2 is ~5 minutes longer in S5-7 than it will
be in S8-9 (build vs. pull). The build pulls fresh layers from Docker Hub every
time (no layer cache between EC2 lifecycles), which is occasionally rate-limited.
Both costs vanish once CI is wired.

### ADR-3: Postgres ephemeral, S3 durable for MLflow state

**Context.** MLflow has a split state model: experiment metadata (run IDs,
parameters, metrics, registered model versions, stage transitions) lives in a
backend store; artifacts (model.pkl, MLmodel descriptor, conda.yaml) live in an
artifact store. We had to choose where each lives in prod.

**Decision.** Postgres on a local EC2 volume (lost on `pulumi destroy`); S3 for
artifacts (durable across the EC2 lifecycle). On every cold-start, `train.py`
runs on the EC2, registers a new model run in the empty Postgres, and writes
fresh `model.pkl` artifacts to S3. The earlier deploy's artifacts in S3 become
orphans — mitigated by a 7-day lifecycle rule on the bucket
(`infrastructure/storage.py`).

**Rationale.** The straightforward alternative is RDS for Postgres so the
metadata persists too. RDS is explicitly out of scope per the exam ("RDS, EKS,
ALB, NAT Gateway, Lambda, SageMaker… are covered in later episodes"). The
remaining options were: (a) full Strategy 2 — `pg_dump` to S3 on the dev machine,
restore on EC2 cold-start, skip retraining; (b) hybrid — retrain on EC2 at deploy
time, artifacts to S3 anyway. We picked (b). Retraining on a 50k-row sample takes
~45 s, comparable to the round-trip time of pulling and restoring a Postgres
dump. The artifacts-in-S3 part is the same in both options.

**Trade-offs.** Demo cold-start re-trains the model — if the run-to-run RNG
yielded a degraded baseline, we'd notice in MLflow but not at request time
(threshold-bucketed predictions). Orphan artifacts in S3 cost a few cents in
storage per week before the lifecycle rule sweeps them. For real prod we'd
introduce RDS (or a managed equivalent) so model registry rows survive deploys
and explicit retirement-driven cleanup replaces the time-based sweep.

### ADR-4: Multi-stage Docker, mlflow-skinny, slim-and-prune to fit < 800 MB

**Context.** Containerization AC requires the api image under 800 MB, multi-stage
build, non-root user, HEALTHCHECK directive, production WSGI/ASGI server.

**Decision.** Two-stage Dockerfile (builder + final, both `python:3.10-slim-bookworm`)
with three structural choices:

1. **`requirements-api.txt`** (separate from host `requirements.txt`) drops
   `mlflow` for `mlflow-skinny` (no tracking-server stack), drops `boto3`
   (transitive of full mlflow; we use the MLflow proxy, not direct S3),
   drops `psycopg2-binary` (api never connects to Postgres directly), and
   drops test-only deps (`pytest`, `httpx`).
2. **Wheels built in stage 1, installed in stage 2** with `--no-compile` so pip
   doesn't byte-compile installed modules (we don't keep them anyway).
3. **Post-install strip** of `tests/`, `test/`, `__pycache__/`, `.pyc`, `.pyo`
   inside `/usr/local/lib/python3.10/site-packages` — done in the *same RUN
   layer* as `pip install` so the deletes actually shrink the image (Docker
   union-mount semantics: deletes in a later layer don't reclaim space from an
   earlier layer).

Process: `gunicorn -w 2 -k uvicorn.workers.UvicornWorker` on a non-root `app`
user with a `python -c "urllib.request.urlopen('/health')"` HEALTHCHECK.

**Rationale.** Naive single-stage build was 1.07 GB. Multi-stage alone got us to
873 MB — still over. The cumulative wins came from `mlflow → mlflow-skinny`
(~150 MB), `--no-compile` + strip (~140 MB), and dropping unneeded deps (~100 MB)
to land at 732 MB. Each technique addresses a different category of bloat
(application deps, byte-compilation, package internals).

**Trade-offs.** `requirements.txt` and `requirements-api.txt` can drift; CI
should run dependency reconciliation as part of the api test job.
`mlflow-skinny` lacks the tracking-server modules — fine for the api (which
only loads models), but if we ever wanted to run `mlflow server` from the api
container we'd be blocked. Stripping `tests/` directories is technically risky
if any third-party library does runtime import of its own test fixtures (rare
but exists); we accept the risk and would catch it with the smoke tests.

### ADR-5: Aggressive observability, four alert rules, UID-pinned datasource

**Context.** Observability AC requires Prometheus scraping the api, Grafana
dashboard provisioned automatically (no manual UI clicks), and at least three
alert rules covering high latency, error rate, and service-down scenarios.

**Decision.** Four alert rules (one bonus): `APIServiceDown` (critical, 1 min),
`HighPredictionLatencyP95` (warning, 5 min, p95 > 500 ms), `HighPredictionErrorRate`
(warning, 2 min, error ratio > 5% with traffic floor anti-flap), `FeastHighMissRate`
(warning, 5 min, miss ratio > 20%). Grafana datasource provisioned with
`uid: prometheus` explicitly set; all dashboard panels reference that UID.

**Rationale.** The fourth alert (`FeastHighMissRate`) is the one that
demonstrates we understand *this specific system*: a high miss rate means the
materialize-features step didn't cover the entities being predicted on, which
is a deployment-pipeline failure mode unique to feature-store-backed serving.
The UID pinning matters because it eliminates the "Grafana dashboard exists
but shows no data" pitfall called out in exam section 7.4 — without an explicit
UID, Grafana auto-generates one and the dashboard JSON's references silently
miss.

**Trade-offs.** Thresholds (500 ms p95, 5% error rate, 20% miss rate) are
educated guesses not derived from real traffic. Real prod would baseline
against historical p95 and alert on percent-deviation rather than absolute.
Listing this as a known limitation rather than tuning blindly; the demo
will fire alerts deliberately rather than from real load.

---

## 4. CI/CD Pipeline Documentation

> Pipeline lands in Sessions 8-9. This section describes the *intended* shape so
> ADR-2 has something concrete to point at; the workflow file
> (`.github/workflows/deploy.yml`) is currently a placeholder.

### Intended workflow shape

Three jobs, each with explicit triggers and required secrets:

| Job              | Trigger                       | What it does                                                                 | Secrets needed                              |
|------------------|-------------------------------|------------------------------------------------------------------------------|---------------------------------------------|
| `test`           | every push, every PR          | Install deps, run pytest (api + integration tests against ephemeral compose) | none                                        |
| `build-and-push` | push to `main` (after `test`) | Build api image, tag with commit SHA + `latest`, push to ECR                 | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`|
| `deploy`         | after `build-and-push`        | SSH to EC2, set `API_IMAGE=<ecr-url>:<sha>` in `.env`, `docker compose pull api && up -d api`, verify `/health` returns 200 | `AWS_*`, `SSH_PRIVATE_KEY`                  |

### CI/CD strategy: incremental update, not destroy-and-recreate

`pulumi up` runs only on infrastructure-affecting commits (changes under
`infrastructure/`), and applies an *incremental update*. We do not destroy and
recreate on every push. Reasoning:

- The EC2 carries Postgres state across pushes (ADR-3 already accepts that
  `pulumi destroy` discards it; we want to *avoid* destroying within a
  session). A fresh EC2 means a 6-min user-data bootstrap on every deploy.
- The api image is the thing that changes on every code push; rebuilding the
  EC2 to deploy a new api image is wasteful.
- Incremental Pulumi updates respect resource dependencies — if `compute.py`
  references a `network.py` resource that didn't change, the EC2 isn't touched.

The CI deploy job uses SSH (not Pulumi) to swap the api image, on the principle
that infrastructure changes (Pulumi) and application deploys (SSH `docker compose
pull && up`) have different cadences and should be on different paths.

### Failure handling

- `test` fails → no push, no deploy. The api image in ECR is whatever the
  previous green commit produced. Rollback is implicit: don't merge red.
- `build-and-push` fails → `latest` tag in ECR doesn't move. Last successful
  image is still pulled by EC2. Rollback is implicit.
- `deploy` fails (e.g. `/health` returns non-200 after pull) → CI fails the
  job. Rollback is *not* automatic; we'd `ssh` in, set `API_IMAGE` to the
  prior SHA, and `docker compose pull api && up -d api` manually. A cleaner
  fix would be a `:rollback` tag in ECR that always points at the previous
  green; deferring as a known limitation.

### Expected end-to-end deploy time

Branch | Time
---|---
`test` only (PR) | ~3-4 min
push to `main` (test + build-and-push + deploy) | ~6-8 min

The dominant cost is the api image build (~3 min on a clean GitHub runner cache).
ECR push and deploy are each ~30 s.

---

## 5. Runbook

### 5.1 Bootstrapping from a Fresh Clone

A new contributor on a clean machine:

```bash
# 1. Clone, copy env template
git clone https://github.com/rabbygit/MLOps-S2-Exam1-modelserve-capstone-starter modelserve
cd modelserve
cp .env.example .env

# 2. Host venv (for train.py + materialize, not the API)
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Dataset download (one-time, ~500 MB)
mkdir -p fraud-detection
curl -L -o /tmp/fraud-detection.zip \
  https://www.kaggle.com/api/v1/datasets/download/kartik2112/fraud-detection
unzip -d fraud-detection /tmp/fraud-detection.zip

# 4. Local stack — first the data plane
docker compose up -d --wait postgres redis mlflow

# 5. Train and materialize features
python training/train.py
python scripts/materialize_features.py

# 6. Bring up everything else
docker compose build api && docker compose up -d
docker compose ps     # six services, all (healthy)

# 7. Smoke test
curl http://localhost:8000/health
curl -X POST http://localhost:8000/predict \
  -H 'content-type: application/json' \
  -d @training/sample_request.json
```

For AWS deploy (Pulumi):

```bash
# 1. Generate SSH key for the EC2 (one-time)
mkdir -p infrastructure/keys
ssh-keygen -t ed25519 -f infrastructure/keys/modelserve -N "" -C "modelserve-dev"

# 2. Pulumi venv + login
cd infrastructure
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pulumi login --local

# 3. Stack init (one-time per machine)
pulumi stack init dev

# 4. AWS creds from sandbox
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...

# 5. Apply
pulumi preview     # always preview before up
pulumi up --yes    # ~3 min for AWS resources; then ~5 min user_data on EC2

# 6. Watch the bootstrap
ssh -i infrastructure/keys/modelserve ec2-user@$(pulumi stack output ec2_public_ip)
sudo tail -f /var/log/modelserve-bootstrap.log

# 7. Smoke test from your laptop
curl $(pulumi stack output api_url)/health
```

### 5.2 Deploying a New Model Version

Without restarting the whole stack:

```bash
# 1. Edit training/train.py (or the data path, sample size, etc.)

# 2. Re-train. Registers a new MLflow version, transitions to Production,
#    archives the previous version automatically.
python training/train.py

# 3. Re-materialize features (only needed if features.parquet changed)
python scripts/materialize_features.py

# 4. The api loads the model on startup. Restart only the api container:
docker compose restart api

# 5. Verify the new version is live
curl http://localhost:8000/health
# {"status": "healthy", "model_version": "<new-version>"}
```

In prod (after S8-9 CI lands), the same flow is automated: push the model code,
CI runs `train.py` against a sample dataset, pushes a new image, deploys. For
S5-7, the EC2 only has its bootstrap-time model — re-training in prod requires
SSH and the same commands as local.

### 5.3 Common Failure Recovery

| Symptom | Likely cause | Recovery |
|---|---|---|
| `api` container restart-loops with `RuntimeError: No 'Production' version found` | MLflow Registry empty (Postgres lost data, no model registered) | `python training/train.py` to re-register |
| `api` container restart-loops with Feast `FileNotFoundError: feature_store.yaml` | Container path mismatch — usually after a Dockerfile WORKDIR change | Verify `FEAST_REPO_PATH` env var matches the actual `WORKDIR/feast_repo` |
| `verify_features.py` returns `[None]` for a known cc_num | Materialize step didn't run, or Redis was wiped | `docker compose up -d redis && python scripts/materialize_features.py` |
| Grafana dashboard renders but every panel says "No data" | Datasource UID mismatch | Check `monitoring/grafana/provisioning/datasources/prometheus.yml` has `uid: prometheus`; check `modelserve.json` panels reference the same UID |
| `pulumi destroy` fails on the ECR repository | Images present and `force_delete` not set | Already set in `infrastructure/registry.py`; verify it's still `True` |
| MLflow container can't write to S3 (Boto3 `NoCredentialsError`) | IMDS hop limit is 1, container is 2 hops | `metadata_options.http_put_response_hop_limit=2` in `infrastructure/compute.py` — already set; verify with `aws ec2 describe-instances` |
| `docker compose up` succeeds but `/predict` returns 404 with `not materialized` | Redis empty | Same as above — re-run materialize |
| EC2 cold-start hangs in user_data.sh on Kaggle download | Kaggle endpoint rate-limiting your IP | Wait, retry. `--retry 3` is set in `user_data.sh`; if that fails, SSH in and run the curl manually |
| Pulumi state corrupted (`error: snapshot integrity failure`) | Concurrent `pulumi up` runs, or filesystem corruption on the state file | `pulumi stack export > backup.json`, edit out the corrupted resource, `pulumi stack import < backup.json` |

### 5.4 Teardown

End of every session — push, then destroy AWS resources:

```bash
# 1. Push uncommitted changes (Golden Rule)
git add -A && git commit -m "..." && git push

# 2. Destroy AWS resources
cd infrastructure
source .venv/bin/activate
pulumi destroy --yes
# Cleans: EC2, VPC + subnets + IGW + RT + SG, ECR repo, S3 bucket
# (force_delete handles non-empty ECR; lifecycle rule handles old S3 objects)

# 3. (Optional) Remove the local Docker stack — frees ~5 GB
cd ..
docker compose down -v   # -v wipes volumes too

# 4. (Optional) Remove pulumi state for this stack — fresh start next session
pulumi stack rm dev --yes
```

The Poridhi VM and AWS sandbox terminate at session end regardless. `pulumi
destroy` is good hygiene that avoids dangling resources interfering with the
next session.

---

## 6. Known Limitations

Honest accounting of what this system does *not* do well, and what would change
for a real production deployment.

**Single-host, no high availability.** ADR-1 covers the trade-off. A real
production deployment would put the api behind a load balancer with at least two
replicas across two availability zones. MLflow and Postgres would migrate to a
managed service (RDS) so they're not co-located with serving.

**Postgres is ephemeral; model registry is rebuilt every deploy.** ADR-3
discusses this. In prod, MLflow's registry is the canonical source of truth for
"which model is in Production"; rebuilding it from `train.py` on every deploy
means two consecutive deploys produce different `model_version` values even
when the same code runs. Workable for the demo, ugly for real.

**Multi-worker Prometheus metrics are per-process.** Gunicorn runs `-w 2`,
meaning each worker has its own `prometheus_client` registry. Each `/metrics`
scrape hits one of the two workers (round-robin), so consecutive scrapes return
different values. Real prod would use `prometheus_client.multiprocess.MultiProcessCollector`
with a shared directory for accurate cross-worker aggregation.

**Alert thresholds are not baselined.** ADR-5 calls this out. The 500 ms p95
threshold and 5% error rate are educated guesses. Real prod would baseline
historical traffic and alert on percent-deviation from a 7-day rolling p95.

**No request-level logging.** The api logs at INFO with no structured fields,
no trace IDs, no request body capture. A real deployment would add structured
JSON logs with a trace ID per request, shipped to a log aggregator (CloudWatch,
Loki, etc.).

**No rate limiting on /predict.** Anyone with the IP can hit `/predict` as fast
as they want. Real deployment would rate-limit per-client (api gateway, or an
in-process limiter like `slowapi`).

**No authentication on any endpoint.** `/predict` is fully public.
`/health` and `/metrics` should arguably stay public (operations); `/predict`
should require an API key in prod.

**Model artifacts in S3 leak across deploys.** ADR-3 covers the orphan
trade-off. The 7-day lifecycle rule limits the leak to ~$0.001/week of S3
storage, but a curious onlooker reading the bucket's listing can see how many
deploys have happened. Real prod would either lifecycle-cleanup more aggressively
or move artifacts to a private repository pattern (e.g. one bucket per
environment).

**ECR is provisioned but unused until S8-9.** ADR-2. Once CI lands, ECR is
populated and the EC2 pulls instead of building.

**Security group is open to the world.** `0.0.0.0/0` on ports 8000/3000/5000/9090.
For a sandbox demo this is required so the TA can reach the services. Real prod
would put the api behind an ALB with a TLS cert (out of scope per the exam),
restrict 22 to a bastion or VPN, and not expose 5000/9090/3000 externally at all
(operators reach them via private network or a jump box).

**Dataset download from Kaggle is a flake risk.** The unauthenticated endpoint
is rate-limited by Kaggle on a per-IP basis; we accept retries in `user_data.sh`,
but a freshly-spawned EC2 IP can occasionally land in a blocked range and the
deploy fails. Mitigation: pre-stage the dataset in our S3 bucket (Strategy 2
deferred to S8-9) so cold-start downloads from a path we control.

**`feature_definitions.py` evolution is not tracked.** Adding a new feature to
the FeatureView requires re-running `train.py` (regenerates `features.parquet`)
and `materialize_features.py` (writes new feature columns to Redis), plus
rebuilding the api image (because `FEATURES` list in `app/feature_client.py`
must match). There's no integration test that catches a drift between these
three.

**No A/B testing or shadow traffic.** A new model version replaces the old one
atomically (when MLflow's `archive_existing_versions=True` flips the stage). No
mechanism to send 5% of traffic to a new version while comparing predictions.
Listed in the rubric's bonus items.

---

*MLOps with Cloud Season 2 — Capstone: ModelServe | Poridhi.io*
