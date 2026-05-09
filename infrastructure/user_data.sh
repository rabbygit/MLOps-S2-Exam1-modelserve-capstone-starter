#!/bin/bash
# cloud-init user-data. Runs once as root on first boot.
#
# Placeholders replaced by compute.py at `pulumi up` time:
#   __REPO_URL__     modelserve:repo_url from Pulumi.dev.yaml
#   __AWS_REGION__   aws:region from Pulumi.dev.yaml
#   __S3_BUCKET__    MLflow artifact bucket name (storage.py output)
#
# Logs go to:
#   /var/log/modelserve-bootstrap.log   (this script's tee)
#   /var/log/cloud-init-output.log      (cloud-init's full capture)

set -e
set -o pipefail
exec > >(tee -a /var/log/modelserve-bootstrap.log) 2>&1

echo "==> [$(date)] starting modelserve bootstrap"

# 0. 2 GB swap. t2.micro has only 1 GB RAM; the 6-service stack OOMs without it.
if ! swapon --show | grep -q /swapfile; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# 1. System packages.
dnf install -y docker git unzip python3.11 python3.11-pip

# 2. Docker daemon, ec2-user can run docker without sudo.
systemctl enable --now docker
usermod -aG docker ec2-user

# 3. Compose v2 plugin (AL2023 doesn't ship it).
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL --retry 3 --retry-delay 5 \
  https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# 4. Clone the repo (main has the latest after merge from session-8-9).
cd /home/ec2-user
git clone --branch main __REPO_URL__ modelserve
cd modelserve

# 5. Kaggle dataset. Unauthenticated endpoint, sometimes flakes.
mkdir -p fraud-detection
curl -fL --retry 3 --retry-delay 10 \
  -o /tmp/fraud-detection.zip \
  https://www.kaggle.com/api/v1/datasets/download/kartik2112/fraud-detection
unzip -d fraud-detection /tmp/fraud-detection.zip
rm /tmp/fraud-detection.zip

# 6. Host venv for train.py and materialize_features.py.
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 7. .env. Template plus EC2-only overrides (artifacts to S3, AWS_REGION
# so boto3 in mlflow picks the right region).
cp .env.example .env
cat >> .env <<EOF

# Appended by user_data.sh
MLFLOW_DEFAULT_ARTIFACT_ROOT=s3://__S3_BUCKET__/
AWS_REGION=__AWS_REGION__
EOF

# 8. Data plane up + wait healthy. mlflow now writes to S3 via boto3 +
# the EC2 IAM role (delivered through IMDS, hop_limit=2).
docker compose up -d --wait postgres redis mlflow

# 9. Train + materialize. Postgres rows are local; model.pkl goes to S3.
# SAMPLE_SIZE=50k keeps cold-start around 3 min.
SAMPLE_SIZE=50000 python training/train.py
python scripts/materialize_features.py

# 10. Build the api locally. CI replaces this with an ECR pull on push to main.
docker compose build api
docker compose up -d api prometheus grafana

# 11. Fix ownership. We ran as root; ec2-user takes over from here.
chown -R ec2-user:ec2-user /home/ec2-user/modelserve

echo "==> [$(date)] bootstrap complete"
