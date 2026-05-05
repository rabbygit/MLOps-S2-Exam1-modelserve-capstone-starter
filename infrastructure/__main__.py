"""Pulumi entry point — imports each module and exports stack outputs."""
import pulumi

import storage
import registry
import iam

# S6 modules — order doesn't matter, Pulumi figures out the resource graph.
import network    # noqa: F401  imported for side effects (registers VPC etc.)
import keypair    # noqa: F401
import instance_role  # noqa: F401
import compute


# Stack outputs — read with `pulumi stack output <name>`.
# These get consumed by the GitHub Actions workflow and by docs.
pulumi.export("artifact_bucket", storage.bucket.id)
pulumi.export("artifact_bucket_arn", storage.bucket.arn)

pulumi.export("ecr_repository_url", registry.repository.repository_url)
pulumi.export("ecr_repository_arn", registry.repository.arn)

pulumi.export("ci_access_key_id", iam.access_key.id)
# Marked as a Pulumi secret automatically; needs --show-secrets to print.
pulumi.export("ci_secret_access_key", iam.access_key.secret)

# S6 — the EC2 host
pulumi.export("ec2_public_ip", compute.instance.public_ip)
pulumi.export("ec2_public_dns", compute.instance.public_dns)
pulumi.export("ec2_instance_id", compute.instance.id)

# Convenience commands you'll actually use after `pulumi up`.
pulumi.export("ssh_command", pulumi.Output.concat(
    "ssh -i keys/modelserve ec2-user@", compute.instance.public_ip,
))
pulumi.export("api_url", pulumi.Output.concat(
    "http://", compute.instance.public_ip, ":8000",
))
pulumi.export("grafana_url", pulumi.Output.concat(
    "http://", compute.instance.public_ip, ":3000",
))
