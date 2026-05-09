"""S3 bucket for MLflow artifacts."""
import pulumi_aws as aws


bucket = aws.s3.BucketV2("mlflow-artifacts")

# Recover from accidental overwrites of model.pkl.
versioning = aws.s3.BucketVersioningV2(
    "mlflow-artifacts-versioning",
    bucket=bucket.id,
    versioning_configuration={"status": "Enabled"},
)

# Block public access in case an ACL or policy slips through.
public_access_block = aws.s3.BucketPublicAccessBlock(
    "mlflow-artifacts-pab",
    bucket=bucket.id,
    block_public_acls=True,
    block_public_policy=True,
    ignore_public_acls=True,
    restrict_public_buckets=True,
)

# `pulumi destroy` wipes Postgres but keeps S3, so old run artifacts pile up.
# 7-day expiry sweeps them. Documented in ADR-3.
lifecycle = aws.s3.BucketLifecycleConfigurationV2(
    "mlflow-artifacts-lifecycle",
    bucket=bucket.id,
    rules=[{
        "id": "expire-orphan-artifacts",
        "status": "Enabled",
        "filter": {"prefix": ""},   # all objects
        "expiration": {"days": 7},
        # versioning keeps old copies, clean those too.
        "noncurrent_version_expiration": {"noncurrent_days": 7},
    }],
)
