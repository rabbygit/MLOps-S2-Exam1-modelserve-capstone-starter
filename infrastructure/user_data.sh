#!/bin/bash
# cloud-init user-data — runs once as root on first boot.
#
# Placeholders replaced by compute.py at `pulumi up` time:
#   __REPO_URL__       modelserve:repo_url from Pulumi.dev.yaml
#   __AWS_REGION__     aws:region from Pulumi.dev.yaml
#   __S3_BUCKET__      MLflow artifact bucket name (output of storage.py)
#
# Logs land in:
#   /var/log/modelserve-bootstrap.log   (this script's own tee)
#   /var/log/cloud-init-output.log      (cloud-init's full capture)

set -e
set -o pipefail
exec > >(tee -a /var/log/modelserve-bootstrap.log) 2>&1

echo "==> [$(date)] starting modelserve bootstrap"

# 1. system packages
dnf install -y docker git unzip python3.11 python3.11-pip

# 2. start docker, let ec2-user run it without sudo
systemctl enable --now docker
usermod -aG docker ec2-user

# 3. compose v2 plugin (AL2023 doesn't ship it as a dnf package)
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL --retry 3 --retry-delay 5 \
  https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# 4. clone the repo
cd /home/ec2-user
git clone __REPO_URL__ modelserve
cd modelserve

# 5. Kaggle dataset (unauthenticated endpoint, retries on flake)
mkdir -p fraud-detection
curl -fL --retry 3 --retry-delay 10 \
  -o /tmp/fraud-detection.zip \
  https://www.kaggle.com/api/v1/datasets/download/kartik2112/fraud-detection
unzip -d fraud-detection /tmp/fraud-detection.zip
rm /tmp/fraud-detection.zip

# 6. python venv for train.py + materialize_features.py
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 7. .env — template plus the one EC2-only override (artifacts to S3).
# AWS_REGION is here so boto3 in the mlflow container picks the right region.
cp .env.example .env
cat >> .env <<EOF

# Appended by user_data.sh — EC2-specific overrides
MLFLOW_DEFAULT_ARTIFACT_ROOT=s3://__S3_BUCKET__/
AWS_REGION=__AWS_REGION__
EOF

# 8. data plane up + wait for healthy. mlflow now writes artifacts to S3
# via boto3, which picks up the EC2 IAM role through IMDS.
docker compose up -d --wait postgres redis mlflow

# 9. train + materialize. Model registry rows go to Postgres (local
# volume). model.pkl uploads to S3. SAMPLE_SIZE=50k keeps cold-start ~3 min.
SAMPLE_SIZE=50000 python training/train.py
python scripts/materialize_features.py

# 10. build the api image and bring up the rest. ECR-pull path lands in
# S8-9 once CI publishes images; until then we build on the EC2.
docker compose build api
docker compose up -d api prometheus grafana

# 11. fix ownership — we ran as root, ec2-user owns from here on
chown -R ec2-user:ec2-user /home/ec2-user/modelserve

echo "==> [$(date)] bootstrap complete"
