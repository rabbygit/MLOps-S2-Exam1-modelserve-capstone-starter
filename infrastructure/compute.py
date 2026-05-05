"""EC2 instance running the modelserve compose stack."""
from pathlib import Path

import pulumi
import pulumi_aws as aws

import network
import keypair
import instance_role
import storage


config = pulumi.Config()
aws_config = pulumi.Config("aws")
THIS_DIR = Path(__file__).resolve().parent

# Latest Amazon Linux 2023 AMI ID, published by AWS via SSM. Re-resolved on
# every `pulumi up`, so we never pin to a stale AMI.
ami = aws.ssm.get_parameter(
    name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64",
)

# user_data has the S3 bucket name to substitute — it doesn't exist until
# the bucket is created. Output.apply waits for the name, then runs the
# str.replace pipeline against the template.
user_data_template = (THIS_DIR / "user_data.sh").read_text()

user_data = storage.bucket.id.apply(
    lambda bucket: user_data_template
        .replace("__REPO_URL__", config.require("repo_url"))
        .replace("__AWS_REGION__", aws_config.require("region"))
        .replace("__S3_BUCKET__", bucket)
)

instance = aws.ec2.Instance(
    "modelserve-host",
    ami=ami.value,
    instance_type=config.require("instance_type"),
    subnet_id=network.public_subnet.id,
    vpc_security_group_ids=[network.security_group.id],
    iam_instance_profile=instance_role.instance_profile.name,
    key_name=keypair.key_pair.key_name,
    user_data=user_data,
    # Without this, editing user_data.sh just updates metadata — the OS already
    # booted with the old script. This flag forces a full replace so the new
    # bootstrap actually runs.
    user_data_replace_on_change=True,
    # IMDSv2 with hop_limit=2 — Docker containers (e.g. mlflow) are 2 hops from
    # IMDS, so the default of 1 cuts them off. Required for boto3 inside the
    # mlflow container to fetch the EC2 IAM role for S3 uploads.
    metadata_options={
        "http_endpoint": "enabled",
        "http_tokens": "required",
        "http_put_response_hop_limit": 2,
    },
    # Default 8 GB is tight: dataset (500 MB) + docker images (~2 GB) +
    # python venv (~2 GB) + system overhead leaves no headroom.
    root_block_device={
        "volume_size": 30,
        "volume_type": "gp3",
    },
    # Adds a "Name" column in the AWS Console. defaultTags handles the rest.
    tags={"Name": "modelserve-host"},
)
