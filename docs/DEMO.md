# Demo Runbook

Notes for the live demo. ~70 minutes total if everything goes right.

## Bootstrap the VM

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

## AWS provisioning

Get fresh AWS creds from the sandbox.

```bash
# Set env vars first so everything downstream inherits them.
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

# Set default repo so gh secret set / gh run watch work
gh repo set-default rabbygit/MLOps-S2-Exam1-modelserve-capstone-starter


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

---

## Set GitHub secrets and trigger CI

Pulumi finished. Stack outputs are ready.

```bash
# Still in infrastructure/
gh secret set AWS_ACCESS_KEY_ID -b "$AWS_ACCESS_KEY_ID"
gh secret set AWS_SECRET_ACCESS_KEY -b "$AWS_SECRET_ACCESS_KEY"
gh secret set EC2_HOST -b "$(pulumi stack output ec2_public_ip)"
gh secret set EC2_SSH_KEY -b "$(cat keys/modelserve)"

cd ..

# Empty commit to trigger CI
git commit --allow-empty -m "demo trigger"
git push origin main

# Watch the run
gh run watch
```

---

## Architecture walkthrough while CI runs

Pipeline takes about 2-3 minutes. EC2 bootstrap takes about 1-2 minutes in parallel.

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

## Pipeline turns green

All three jobs check in the Actions tab. EC2 bootstrap finishes around the same time. Sanity check:

```bash
EC2_IP=$(cd infrastructure && pulumi stack output ec2_public_ip)
curl http://$EC2_IP:8000/health
# {"status":"healthy","model_version":"1"}
```

---

## Live demo

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

Predictions return the model version. Grafana auto-provisioned and Dashboard has 8 panels: latency p50/p95/p99, request rate, error rate, model version, hit ratio, etc.

---

## Generate load, watch dashboards

```bash
for i in $(seq 1 200); do
  curl -s -X POST http://$EC2_IP:8000/predict \
    -H 'content-type: application/json' \
    -d @training/sample_request.json > /dev/null
  sleep 0.1
done
```

Refresh Grafana. Total Requests, Request Rate, latency panel populate.

---

## Failure injection

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