"""ECR repository for the FastAPI image."""
import pulumi_aws as aws


repository = aws.ecr.Repository(
    "modelserve-api",
    # Pin the AWS-side name (no random suffix) so CI can hardcode it.
    name="modelserve-api",
    # Without this `pulumi destroy` errors out if any image was pushed.
    force_delete=True,
    # Free vuln scan on every push.
    image_scanning_configuration={"scan_on_push": True},
)
