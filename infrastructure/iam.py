"""IAM user for the GitHub Actions CI/CD pipeline"""
import pulumi
import pulumi_aws as aws
from registry import repository


# Programmatic access only — no console login.
user = aws.iam.User("ci")

# Two-statement policy:
#   1. ecr:GetAuthorizationToken must be Resource: * (it's a global action).
#   2. push/pull scoped to the modelserve-api repo only.
policy = aws.iam.Policy(
    "ci-policy",
    policy=pulumi.Output.json_dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["ecr:GetAuthorizationToken"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                ],
                "Resource": repository.arn,
            },
        ],
    }),
)

attachment = aws.iam.UserPolicyAttachment(
    "ci-policy-attachment",
    user=user.name,
    policy_arn=policy.arn,
)

# Stash both halves into GitHub Secrets. `secret` is auto-marked as a
# Pulumi secret, so it stays encrypted in the state file.
access_key = aws.iam.AccessKey("ci-access-key", user=user.name)
