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

ami = aws.ec2.get_ami(
    most_recent=True,
    owners=["amazon"],
    filters=[
        {"name": "name", "values": ["al2023-ami-ecs-hvm-*-x86_64"]},
        {"name": "architecture", "values": ["x86_64"]},
        {"name": "virtualization-type", "values": ["hvm"]},
    ],
)

# Substitute placeholders in user_data.sh. S3 bucket name is an Output
# (not known until the bucket exists), so wrap with apply().
user_data_template = (THIS_DIR / "user_data.sh").read_text()

user_data = storage.bucket.id.apply(
    lambda bucket: user_data_template
        .replace("__REPO_URL__", config.require("repo_url"))
        .replace("__AWS_REGION__", aws_config.require("region"))
        .replace("__S3_BUCKET__", bucket)
)

instance = aws.ec2.Instance(
    "modelserve-host",
    ami=ami.id,
    instance_type=config.require("instance_type"),
    subnet_id=network.public_subnet.id,
    vpc_security_group_ids=[network.security_group.id],
    iam_instance_profile=instance_role.instance_profile.name,
    key_name=keypair.key_pair.key_name,
    user_data=user_data,
    # Without this, editing user_data.sh just updates metadata. OS already
    # booted with the old script. Force a full replace so the new bootstrap
    # actually runs.
    user_data_replace_on_change=True,
    # hop_limit=2 so docker containers can reach IMDS. Default of 1 blocks
    # boto3 inside the mlflow container from finding the EC2 IAM role.
    metadata_options={
        "http_endpoint": "enabled",
        "http_tokens": "required",
        "http_put_response_hop_limit": 2,
    },
    # Default 8 GB is tight: dataset (500 MB) + docker images (~2 GB) +
    # python venv (~2 GB) leaves no headroom.
    root_block_device={
        "volume_size": 30,
        "volume_type": "gp3",
    },
    # Inline tags. defaultTags is off in the sandbox (iam:Tag* denied).
    tags={
        "Name": "modelserve-host",
        "Project": "modelserve",
        "Environment": "dev",
        "ManagedBy": "pulumi",
    },
)
