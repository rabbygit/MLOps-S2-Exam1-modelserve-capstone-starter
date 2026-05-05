"""IAM role + instance profile for the EC2 host."""
import json

import pulumi
import pulumi_aws as aws

from registry import repository
from storage import bucket


# Only the EC2 service can assume this role.
trust_policy = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "ec2.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }],
})

role = aws.iam.Role("ec2-host-role", assume_role_policy=trust_policy)

# ECR pull (scoped to our repo + the global token call) and S3 r/w to the
# MLflow artifact bucket. Inline policy so it auto-deletes with the role.
policy = aws.iam.RolePolicy(
    "ec2-host-policy",
    role=role.id,
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
                ],
                "Resource": repository.arn,
            },
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": bucket.arn,
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": pulumi.Output.concat(bucket.arn, "/*"),
            },
        ],
    }),
)

# Wraps the role so EC2 can attach it via iam_instance_profile.
instance_profile = aws.iam.InstanceProfile("ec2-host-profile", role=role.name)
