# ModelServe — Demo Runbook (~70 min)

> Cheat sheet for the live demo. Read it the day before; use it on the day.

## Exam VM environment (Poridhi sandbox)

What's pre-installed on the Poridhi VM (Ubuntu 24.04 noble):
- `docker`, `docker compose`, `git`, `python3` (3.12), `pip3`, `jq`, `ssh-keygen`

What needs installing every fresh VM (~3 min):
- `pulumi` (one-line installer)
- `gh` (apt repo)
- `aws` CLI v2 (AWS bundle, since `awscli` isn't in noble's apt)

Python 3.12 (default on this VM) is fine for Pulumi + pytest + ruff. Training runs on the EC2 (which has its own Python 3.11 via `dnf`), so the host Python version doesn't actually matter much.

## Day-before checklist

- Repo public on GitHub at `https://github.com/rabbygit/MLOps-S2-Exam1-modelserve-capstone-starter`
- **`main` branch must be up to date** — `session-8-9` (or whatever working branch) is merged into `main`. The CI workflow only triggers on push to `main`, and the cloned repo's `main` is what `pulumi up` reads from. Verify with: `git ls-remote origin main` should match the latest commit you want demoed.
- Re-read the 5 ADRs in `docs/ARCHITECTURE.md` once
- Re-read this file
- Have AWS sandbox creds ready (or know where to grab them on demo day)
- Sleep

## 30 minutes before

Open these tabs:
- GitHub repo → Actions
- GitHub repo → Settings → Secrets
- `docs/ARCHITECTURE.md` (in editor)

Two terminal windows ready (both on the Poridhi VM):
- one in repo root
- one for SSH later

Confirm AWS sandbox credentials are at hand, and the Poridhi VM is provisioned.

---

## T-5 → T+0 — Bootstrap the exam VM (~3 min)

Runs once per fresh Poridhi VM. The exam VM doesn't have Pulumi, gh, or AWS CLI v2.

**Where to fit this in:** if the VM is alive 30 minutes before demo time, do this in the prep window so T+0 starts with all tools ready. If you only get the VM at demo start, this eats into the first ~3 minutes of the 10-min cold-start budget — still fits.

```bash
# 1. Pulumi
curl -fsSL https://get.pulumi.com | sh
echo 'export PATH=$PATH:$HOME/.pulumi/bin' >> ~/.bashrc
export PATH=$PATH:$HOME/.pulumi/bin

# 2. gh CLI + python venv module + unzip
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install -y gh unzip python3.12-venv

# 3. AWS CLI v2 (apt's `awscli` was dropped in noble)
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp && sudo /tmp/aws/install
rm -rf /tmp/awscliv2.zip /tmp/aws

# 4. Verify everything is wired
docker --version && docker compose version
pulumi version && gh --version && aws --version && python3 --version
```

Then auth + identity:

```bash
# 5. gh login (browser-based one-time code)
gh auth login -h github.com -s repo,workflow -w
# Answer prompts: HTTPS → Y → Web browser. Paste the code, approve.
gh auth status

# 6. Git identity (needed before any `git commit`)
git config --global user.name "Rabby"
git config --global user.email "<your-github-email>"
```

---

## T+0 — Cold start, AWS provisioning

Get fresh AWS creds from the sandbox. Run from your home directory (or anywhere — the script clones the repo first).

```bash
# Set env vars first so they're inherited by everything downstream.
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=ap-southeast-1
export PULUMI_CONFIG_PASSPHRASE=demo

# Sanity-check AWS auth before doing anything.
aws sts get-caller-identity
# Expected: JSON with the sandbox account ID.

# Clone the repo + set up the EC2 SSH key.
git clone https://github.com/rabbygit/MLOps-S2-Exam1-modelserve-capstone-starter modelserve
cd modelserve
mkdir -p infrastructure/keys
ssh-keygen -t ed25519 -f infrastructure/keys/modelserve -N "" -C "modelserve-demo"

# Pulumi venv. python3.12-venv was installed in the bootstrap step.
cd infrastructure
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Pulumi state backend + stack (idempotent — works whether or not stack exists).
pulumi login --local
pulumi stack select dev 2>/dev/null || pulumi stack init dev

# Provision (~2 min).
pulumi up --yes
```

Tell the TA: *"Provisioning AWS infra via Pulumi — VPC, EC2, ECR, S3, IAM. Two minutes."*

Keep `ARCHITECTURE.md` open on the side while it runs.

---

## T+2 — GitHub secrets, trigger CI

Pulumi finished. Stack outputs are now available.

```bash
# still inside infrastructure/
gh secret set AWS_ACCESS_KEY_ID -b "$(pulumi stack output ci_access_key_id)"
gh secret set AWS_SECRET_ACCESS_KEY -b "$(pulumi stack output ci_secret_access_key --show-secrets)"
gh secret set EC2_HOST -b "$(pulumi stack output ec2_public_ip)"
gh secret set EC2_SSH_KEY -b "$(cat keys/modelserve)"

cd ..

# trigger the workflow with an empty commit
git commit --allow-empty -m "demo trigger"
git push origin main
```

Tell the TA: *"Secrets are synced from this fresh stack. Pushed to main, which triggers the GitHub Actions workflow."*

Open the Actions tab. Watch the run from the second terminal:

```bash
gh run watch
```

---

## T+3 to T+18 — Architecture walkthrough while CI runs

Roughly 15 minutes. The pipeline takes ~6-8 min; EC2 bootstrap takes ~7 min in parallel. Use the time.

### What to show, in order

1. **`docs/ARCHITECTURE.md` — section 2.2 (production diagram).**
   *"Single EC2 in a public subnet. Compose stack runs on it. S3 holds artifacts. ECR holds the api image once CI populates it."*

2. **The 5 ADRs.** Read the title, the decision, and one trade-off. Don't read the full text.
   - ADR-1 — Why single-EC2: *"Sandbox lifecycle. SPOF acknowledged."*
   - ADR-2 — Incremental update, not destroy-and-recreate: *"CI never destroys. Pulumi stays manual."*
   - ADR-3 — Postgres ephemeral, S3 durable: *"RDS is out of scope. Retrain on cold start; artifacts in S3."*
   - ADR-4 — Multi-stage Docker → 732 MB: *"mlflow-skinny + --no-compile + strip tests."*
   - ADR-5 — Four alerts, UID-pinned datasource: *"FeastHighMissRate is system-specific."*

3. **Pipeline running.** Refresh the Actions page. Show test → build-and-push → deploy.

4. **`infrastructure/compute.py`** if asked. Walk through:
   - SSM AMI lookup (latest AL2023, no hardcoded IDs)
   - `metadata_options.http_put_response_hop_limit=2` — *"so the mlflow container can reach IMDS for S3 creds"*
   - `user_data_replace_on_change=True` — *"editing user_data forces EC2 replace"*
   - Output substitution into user_data

5. **`.github/workflows/deploy.yml`** if asked — three jobs.

### TA questions to be ready for

| Q | A |
|---|---|
| Why single-EC2? | ADR-1. Tradeoff is SPOF, acceptable for sandbox. |
| Why no RDS? | Out of scope per exam. ADR-3. |
| Why Postgres on EC2 if it dies on destroy? | Re-running train.py is cheap. Orphan trade-off documented + lifecycle rule. |
| Why is ECR empty before first CI run? | ADR-2. CI populates it. Build-on-EC2 is the bridge. |
| Why mlflow-skinny? | Trimmed runtime deps for the api. Saves ~150 MB. |
| Why hop_limit=2? | Docker containers are 2 hops from IMDS. |
| Why no auth on /predict? | Known limitation. Sandbox demo. |
| What happens between git push and serving? | test → ECR push → SSH to EC2 → set API_IMAGE → docker compose pull api && up -d api → /health verify. ~6 min. |

---

## T+9 to T+12 — Pipeline turns green

All three jobs check ✓ in the Actions tab. EC2 bootstrap finishes around the same time. Quick sanity check:

```bash
EC2_IP=$(cd infrastructure && pulumi stack output ec2_public_ip)
curl http://$EC2_IP:8000/health
# {"status":"healthy","model_version":"1"}
```

---

## T+18 to T+25 — Live demo

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

# Open Grafana — admin/admin
open http://$EC2_IP:3000
```

Tell the TA: *"Predictions return the model version. Grafana is auto-provisioned — no UI clicks after compose up. The dashboard has 8 panels: latency p50/p95/p99, request rate, error rate, model version, hit ratio, etc."*

---

## T+25 to T+40 — Generate load, watch dashboards

```bash
for i in $(seq 1 200); do
  curl -s -X POST http://$EC2_IP:8000/predict \
    -H 'content-type: application/json' \
    -d @training/sample_request.json > /dev/null
  sleep 0.1
done
```

Refresh Grafana. Total Requests, Request Rate, and the latency panel will all populate.

### TA picks something to look up on the dashboard

| TA asks | Where to point |
|---|---|
| "p99 latency last 5 min" | Latency panel, red line. Hover for value. |
| "Hit ratio" | Stat panel top-right. Should be ~100%. |
| "Total predictions since deploy" | Total Requests stat panel. |
| "Why is p99 above p95?" | Histogram bucketing + tail latency. Some requests hit a slow Redis or a model swap moment. |

---

## T+40 to T+55 — Failure injection

The TA picks one or two from this set.

### Kill api → APIServiceDown alert fires

```bash
ssh -i infrastructure/keys/modelserve ec2-user@$EC2_IP \
  "cd modelserve && docker compose stop api"
```

Open `http://$EC2_IP:9090/alerts`. Wait ~60 s. `APIServiceDown` flips to firing.

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

Wait 2 min. Alert fires. Show Grafana → "Error Rate (by reason)" → `missing_features` line spikes.

### Rollback to a previous commit

```bash
git log --oneline -5

# trigger the workflow with an explicit SHA
gh workflow run deploy.yml -f deploy_sha=<old-sha>

# OR manual SSH if workflow_dispatch isn't wired:
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

## T+55 to T+60 — Wrap-up + teardown

Final TA questions, then:

```bash
cd infrastructure
pulumi destroy --yes
```

Tell the TA: *"All 23 AWS resources destroyed. force_delete on ECR handles non-empty repo. Lifecycle rule sweeps S3 orphans. Pulumi state lives locally — fresh start next session."*

---

## Things that can break + recovery

| Problem | Recovery |
|---|---|
| `pulumi: command not found` after install | `export PATH=$PATH:$HOME/.pulumi/bin`. Add to `~/.bashrc` if not already. |
| `pulumi login --local` errors "expected project to be an object, was '<nil>'" | Cloned `main` but the work is on another branch. `git checkout session-8-9` (or merge to main first). |
| `python3 -m venv` says "ensurepip is not available" | `sudo apt install -y python3.12-venv`, then `rm -rf .venv && python3 -m venv .venv` |
| `pip install` says "externally-managed-environment" | The venv isn't active. Run `source .venv/bin/activate` first. The error means pip is hitting system Python because the venv failed silently. |
| `gh: command not found` after install | `which gh`; if missing, re-run the `apt install gh` step |
| `aws: command not found` | Run the AWS CLI v2 bundle install from the bootstrap section |
| `gh auth login` says "Failed opening a web browser" | Expected on a headless VM. Copy the one-time code shown, open `https://github.com/login/device` on your laptop, paste, approve. Terminal continues automatically. |
| `git commit` says "Please tell me who you are" | `git config --global user.name "Rabby" && git config --global user.email "..."` |
| `pulumi up` fails on AWS API throttle | Re-run `pulumi up --yes` |
| Stack state is dirty | `pulumi refresh --yes` then `pulumi up --yes` |
| `pulumi up` says secrets passphrase is wrong | `export PULUMI_CONFIG_PASSPHRASE=demo` (or whatever you used at `stack init`) |
| EC2 user_data still booting when CI tries to SSH | `gh run rerun --failed` |
| Kaggle dataset download flakes | SSH in, run the curl manually, re-trigger CI |
| Pipeline fails on `test` (Python version mismatch) | Workflow pins 3.10 in the GitHub runner. Should pass even though VM has 3.12. If it fails, read the error and patch. |
| `EC2_HOST` IP changed (re-provisioned) | `gh secret set EC2_HOST -b "$(pulumi stack output ec2_public_ip)"`, then re-run the workflow |
| AWS creds expired mid-demo (sandbox token rotated) | Re-export `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`. Re-set the four `gh secret set` commands. |
| `pulumi destroy` fails on a resource | `pulumi destroy --target '<urn>' --yes` to skip; `aws s3 rm s3://<bucket> --recursive` if bucket is the blocker |
| Forgot the passphrase | `pulumi stack rm dev --yes && pulumi stack init dev` and start over (~3 min lost). |

---

## What to avoid

- `git pull` mid-demo. Code on the laptop matches the running pipeline only because nothing changed.
- `pulumi up` again while CI is running. Race condition.
- `pulumi destroy` until the very end.
- Editing locally to fix a failing CI job — re-trigger or re-run, debug after.
- Apologizing for things that work. ("Took a couple seconds longer than usual" — TA doesn't care.)
- Rabbit-holing on a question. Two-sentence answer, then continue.

---

## What each phase proves

| Phase | Proof |
|---|---|
| Pulumi up | Infrastructure-as-code, clean provision, tagged resources |
| Push triggers CI | Three jobs in order, secrets configured, ECR populated |
| /health and /predict | The system actually works end-to-end |
| Grafana populated | Observability is wired (provisioned datasource, dashboard, scrape) |
| Alert fires when api dies | Alerts are real, not just configured |
| Rollback / new push | Pipeline is re-runnable, deploys are reversible |
| Pulumi destroy | Clean teardown, nothing dangling |

---

*Print it. Read it on the bus.*
