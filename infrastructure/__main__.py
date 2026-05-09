"""Pulumi entry point. Imports each module and exports stack outputs."""
import pulumi

import storage
import registry

# Note on CI auth: a dedicated `ci` IAM user with scoped ECR-push perms
# would be the production-shape choice. The Poridhi sandbox SCP denies
# iam:CreateUser, so we use the sandbox's own creds directly via GitHub
# Secrets instead.

# Order doesn't matter; Pulumi works it out from the resource graph.
import network    # noqa: F401  side-effect import
import keypair    # noqa: F401
import instance_role  # noqa: F401
import compute


# Stack outputs. Read with `pulumi stack output <name>`.
pulumi.export("artifact_bucket", storage.bucket.id)
pulumi.export("artifact_bucket_arn", storage.bucket.arn)

pulumi.export("ecr_repository_url", registry.repository.repository_url)
pulumi.export("ecr_repository_arn", registry.repository.arn)

pulumi.export("ec2_public_ip", compute.instance.public_ip)
pulumi.export("ec2_public_dns", compute.instance.public_dns)
pulumi.export("ec2_instance_id", compute.instance.id)

# Convenience strings to copy/paste after `pulumi up`.
pulumi.export("ssh_command", pulumi.Output.concat(
    "ssh -i keys/modelserve ec2-user@", compute.instance.public_ip,
))
pulumi.export("api_url", pulumi.Output.concat(
    "http://", compute.instance.public_ip, ":8000",
))
pulumi.export("grafana_url", pulumi.Output.concat(
    "http://", compute.instance.public_ip, ":3000",
))
