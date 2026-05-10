# Demo Runbook

Notes for the live demo. ~70 minutes total if everything goes right.

## What's already on the Poridhi VM

Pre-installed: docker, docker compose, git, python3 (3.12), pip3, jq, ssh-keygen.

Need to install on every fresh VM: pulumi, gh, AWS CLI v2, python3.12-venv. About 3 minutes total.

Python 3.12 is fine for pulumi + pytest + ruff. Training runs on the EC2 (Python 3.11 from dnf), so the host's Python doesn't matter.

## Day before

- Repo is public on GitHub
- `main` branch has the latest code (not just a working branch). The CI workflow only triggers on push to `main`, and `pulumi up` clones from `main`. Confirm with `git ls-remote origin main`.
- Read through `docs/ARCHITECTURE.md` once, especially the 5 ADRs
- Read this file
- AWS sandbox creds ready

## 30 minutes before

Open these tabs:
- GitHub repo → Actions
- GitHub repo → Settings → Secrets

Two terminal windows:
- One in the repo root
- One I'll use for SSH later

---

## T-5 → T+0: Bootstrap the VM

Runs once per fresh Poridhi VM. About 3 minutes.

If the VM is up 30 minutes before demo, do this in the prep window. If not, it eats the first 3 minutes of the cold-start budget.

```bash
# Pulumi
curl -fsSL https://get.pulumi.com | sh
echo 'export PATH=$PATH:$HOME/.pulumi/bin' >> ~/.bashrc
export PATH=$PATH:$HOME/.pulumi/bin

# gh CLI + python venv module + unzip
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install -y gh unzip python3.12-venv

# AWS CLI v2 (apt's awscli was dropped in noble)
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp && sudo /tmp/aws/install
rm -rf /tmp/awscliv2.zip /tmp/aws

# Verify
docker --version && docker compose version
pulumi version && gh --version && aws --version && python3 --version
```

Then auth and identity:

```bash
# gh login (browser-based one-time code, copy code into laptop browser)
gh auth login -h github.com -s repo,workflow -w

# Git identity (needed for git commit)
git config --global user.name "Rabby"
git config --global user.email "<your-github-email>"
```

---

## T+0: Cold start, AWS provisioning

Get fresh AWS creds from the sandbox.

```bash
# Set env vars first so everything downstream inherits them.
# PULUMI_CONFIG_PASSPHRASE has to match what was used at `stack init` time.
# Just always use the same one.
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=ap-southeast-1
export PULUMI_CONFIG_PASSPHRASE=modelserve

# Sanity check AWS auth
aws sts get-caller-identity

# Clone + EC2 SSH key
git clone https://github.com/rabbygit/MLOps-S2-Exam1-modelserve-capstone-starter modelserve
cd modelserve
mkdir -p infrastructure/keys
ssh-keygen -t ed25519 -f infrastructure/keys/modelserve -N "" -C "modelserve-demo"

# Pulumi venv
cd infrastructure
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Pulumi state + stack (idempotent)
pulumi login --local
pulumi stack select dev 2>/dev/null || pulumi stack init dev

# Provision (~2 min)
pulumi up --yes
```

Say something like: "Provisioning AWS infra via Pulumi - VPC, EC2, ECR, S3, IAM. Two minutes."

Keep ARCHITECTURE.md open while it runs.

---

## T+2: GitHub secrets, trigger CI

Pulumi finished. Stack outputs are ready.

```bash
# Still in infrastructure/
# Using sandbox creds directly because the Poridhi sandbox SCP blocks
# iam:CreateUser, so the dedicated `ci` user can't be created.
gh secret set AWS_ACCESS_KEY_ID -b "$AWS_ACCESS_KEY_ID"
gh secret set AWS_SECRET_ACCESS_KEY -b "$AWS_SECRET_ACCESS_KEY"
gh secret set EC2_HOST -b "$(pulumi stack output ec2_public_ip)"
gh secret set EC2_SSH_KEY -b "$(cat keys/modelserve)"

cd ..

# Empty commit to trigger CI
git commit --allow-empty -m "demo trigger"
git push origin main

# Set default repo so gh secret set / gh run watch work
gh repo set-default rabbygit/MLOps-S2-Exam1-modelserve-capstone-starter

# Watch the run
gh run watch
```

---

## T+3 to T+18: Architecture walkthrough while CI runs

Pipeline takes about 6-8 minutes. EC2 bootstrap takes about 7 minutes in parallel. Use the time.

### Walk through, in order

1. ARCHITECTURE.md section 2.2 (production diagram). Single EC2 in a public subnet. Compose stack runs on it. S3 holds artifacts. ECR holds the api image once CI populates it.

2. The 5 ADRs. Read the title, the decision, one trade-off. Don't read the full text.
    - ADR-1: Why single EC2. Sandbox lifecycle, SPOF acknowledged.
    - ADR-2: Incremental update over destroy-and-recreate. CI never destroys, Pulumi stays manual.
    - ADR-3: Postgres ephemeral, S3 durable. RDS is out of scope. Retrain on cold start; artifacts in S3.
    - ADR-4: Multi-stage Docker, 732 MB. mlflow-skinny + --no-compile + strip tests.
    - ADR-5: Four alerts, UID-pinned datasource. FeastHighMissRate is system-specific.

3. Refresh the Actions page. Show test → build → deploy.

4. If asked about `infrastructure/compute.py`:
    - SSM/AMI lookup (latest AL2023, no hardcoded IDs)
    - `metadata_options.http_put_response_hop_limit=2` so the mlflow container can reach IMDS for S3 creds
    - `user_data_replace_on_change=True` forces EC2 replace when user_data changes
    - Output substitutions into user_data

5. If asked about the workflow file: three jobs, plus lint and pulumi validate.

### Questions I should be ready for

| Question | Answer |
|---|---|
| Why single EC2? | ADR-1. SPOF acknowledged, fine for sandbox. |
| Why no RDS? | Out of scope per exam. ADR-3. |
| Why Postgres on EC2 if it dies on destroy? | Retraining is cheap. Orphan trade-off documented + lifecycle rule. |
| Why is ECR empty before first CI run? | ADR-2. CI populates it. Build-on-EC2 is the bridge. |
| Why mlflow-skinny? | Trimmed runtime deps for the api. Saves ~150 MB. |
| Why hop_limit=2? | Docker containers are 2 hops from IMDS. |
| Why no auth on /predict? | Known limitation. Sandbox demo. |
| Git push to serving, what happens? | test → ECR push → SSH to EC2 → set API_IMAGE → docker compose pull api && up -d api → /health verify. ~6 min. |
| Why t2.micro? | Sandbox SCP denies larger types. Within the exam's typical envelope anyway. |

---

## T+9 to T+12: Pipeline turns green

All three jobs check in the Actions tab. EC2 bootstrap finishes around the same time. Sanity check:

```bash
EC2_IP=$(cd infrastructure && pulumi stack output ec2_public_ip)
curl http://$EC2_IP:8000/health
# {"status":"healthy","model_version":"1"}
```

---

## T+18 to T+25: Live demo

```bash
# Health
curl http://$EC2_IP:8000/health

# Predict (POST)
curl -X POST http://$EC2_IP:8000/predict \
  -H 'content-type: application/json' \
  -d @training/sample_request.json

# Predict with explain (GET)
ENTITY_ID=$(jq -r .entity_id training/sample_request.json)
curl "http://$EC2_IP:8000/predict/$ENTITY_ID?explain=true"

# Metrics
curl http://$EC2_IP:8000/metrics | head -30

# Grafana - admin/admin
echo "http://$EC2_IP:3000"
```

Predictions return the model version. Grafana auto-provisioned. Dashboard has 8 panels: latency p50/p95/p99, request rate, error rate, model version, hit ratio, etc.

---

## T+25 to T+40: Generate load, watch dashboards

```bash
for i in $(seq 1 200); do
  curl -s -X POST http://$EC2_IP:8000/predict \
    -H 'content-type: application/json' \
    -d @training/sample_request.json > /dev/null
  sleep 0.1
done
```

Refresh Grafana. Total Requests, Request Rate, latency panel populate.

### TA picks something to look up

| TA asks | Where to point |
|---|---|
| "p99 latency last 5 min" | Latency panel, red line. Hover for value. |
| "Hit ratio" | Stat panel top right. ~100%. |
| "Total predictions" | Total Requests stat panel. |
| "Why is p99 above p95?" | Histogram bucketing + tail latency. Some requests hit a slow Redis or a model swap moment. |

---

## T+40 to T+55: Failure injection

TA picks one or two from this set.

### Kill api → APIServiceDown alert fires

```bash
ssh -i infrastructure/keys/modelserve ec2-user@$EC2_IP \
  "cd modelserve && docker compose stop api"
```

Open `http://$EC2_IP:9090/alerts`. Wait ~60s. APIServiceDown flips to firing.

```bash
ssh -i infrastructure/keys/modelserve ec2-user@$EC2_IP \
  "cd modelserve && docker compose up -d api"
```

### Trigger missing-feature errors → HighPredictionErrorRate

```bash
for i in $(seq 1 100); do
  curl -s -X POST http://$EC2_IP:8000/predict \
    -H 'content-type: application/json' \
    -d '{"entity_id": 0}' > /dev/null
done
```

Wait 2 min. Alert fires. Show Grafana → "Error Rate (by reason)" → missing_features line spikes.

### Rollback to a previous commit

```bash
git log --oneline -5

# Trigger workflow with explicit SHA
gh workflow run deploy.yml -f deploy_sha=<old-sha>

# Or manual SSH if workflow_dispatch isn't wired
ssh -i infrastructure/keys/modelserve ec2-user@$EC2_IP \
  "cd modelserve && sed -i 's|API_IMAGE=.*|API_IMAGE=<ecr-url>:<old-sha>|' .env && \
   docker compose pull api && docker compose up -d api"
curl http://$EC2_IP:8000/health
```

### Push a code change, watch it deploy

```bash
sed -i 's/Fraud Detection API/Fraud Detection API v2/' app/main.py
git add -A && git commit -m "demo update"
git push origin main
gh run watch
```

5-7 min later the new version is live. Hit `/docs` to see the new title.

---

## T+55 to T+60: Wrap up + teardown

Final TA questions, then:

```bash
cd infrastructure
pulumi destroy --yes
```

All 23 AWS resources destroyed. force_delete on ECR handles the non-empty repo. Lifecycle rule sweeps S3 orphans. Pulumi state lives locally so next session is a fresh start.

---

## Things that can break + recovery

| Problem | Recovery |
|---|---|
| `pulumi: command not found` after install | `export PATH=$PATH:$HOME/.pulumi/bin`. Add to `~/.bashrc` if not there. |
| `pulumi login --local` errors "expected project to be an object, was '<nil>'" | Cloned `main` but the work is on another branch. `git checkout <branch>`, or merge to main first. |
| `python3 -m venv` says "ensurepip is not available" | `sudo apt install -y python3.12-venv`, then `rm -rf .venv && python3 -m venv .venv` |
| `pip install` says "externally-managed-environment" | The venv isn't active. Run `source .venv/bin/activate` first. |
| `gh: command not found` after install | `which gh`. If missing, re-run the apt install gh step. |
| `aws: command not found` | Run the AWS CLI v2 bundle install from the bootstrap section. |
| `gh auth login` says "Failed opening a web browser" | Expected on a headless VM. Copy the one-time code, open `https://github.com/login/device` on the laptop, paste, approve. |
| Any gh command says "no default remote repository" | `gh repo set-default rabbygit/MLOps-S2-Exam1-modelserve-capstone-starter` |
| `git commit` says "Please tell me who you are" | `git config --global user.name "Rabby" && git config --global user.email "..."` |
| `pulumi up` fails on AWS API throttle | Re-run `pulumi up --yes` |
| Stack state is dirty | `pulumi refresh --yes`, then `pulumi up --yes` |
| `pulumi up` says "incorrect passphrase" | `export PULUMI_CONFIG_PASSPHRASE=modelserve` (or whatever was used at stack init). |
| `ec2:RunInstances` denied for t3.small or larger | Sandbox SCP whitelist. t2.micro works. `pulumi config set modelserve:instance_type t2.micro`, re-run. |
| Containers OOM-killed on t2.micro (1 GB RAM) | SSH in: `sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`. Then `docker compose up -d` to bring back killed services. user_data.sh does this on fresh boots. |
| `iam:TagInstanceProfile` / `iam:CreateUser` denied | Sandbox SCP. defaultTags is removed from Pulumi.dev.yaml. CI uses sandbox creds directly (no dedicated CI user provisioned). |
| EC2 user_data still booting when CI tries to SSH | `gh run rerun --failed` |
| Predict returns 500 with `FeatureViewNotFoundException: Feature view fraud_features does not exist` | Bind mount missing or registry.db not on host. Check `grep volumes docker-compose.yml`. If missing, the EC2 cloned an old branch. `git checkout main && docker compose up -d --force-recreate api`. If host's `feast_repo/data/registry.db` is missing, re-run `python scripts/materialize_features.py` and `docker compose restart api`. |
| CI deploy fails with `bash: line N: .env: Permission denied` | `.env` on the EC2 is root-owned. user_data's final `chown -R` didn't run. SSH in: `sudo chown -R ec2-user:ec2-user /home/ec2-user/modelserve`. The workflow now does this defensively before writing .env. |
| Kaggle dataset download flakes | SSH in, run the curl manually, re-trigger CI. |
| Pipeline fails on test (Python version mismatch) | Workflow pins 3.10 in the GitHub runner. Should pass even though VM has 3.12. If it fails, read the error and patch. |
| `EC2_HOST` IP changed (re-provisioned) | `gh secret set EC2_HOST -b "$(pulumi stack output ec2_public_ip)"`, re-run the workflow. |
| AWS creds expired mid-demo (sandbox token rotated) | Re-export `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`. Re-set the four `gh secret set` commands. |
| `pulumi destroy` fails on a resource | `pulumi destroy --target '<urn>' --yes` to skip. `aws s3 rm s3://<bucket> --recursive` if the bucket is the blocker. |
| Forgot the passphrase | `pulumi stack rm dev --yes && pulumi stack init dev`, start over (~3 min lost). |

---

## Things to avoid

- `git pull` mid-demo. Code on the laptop matches the running pipeline only because nothing changed.
- `pulumi up` while CI is running. Race condition.
- `pulumi destroy` until the very end.
- Editing locally to fix a failing CI job. Re-trigger or re-run, debug after.
- Apologizing for things that work. ("Took a couple seconds longer than usual" - TA doesn't care.)
- Rabbit-holing on a question. Two-sentence answer, then continue.
