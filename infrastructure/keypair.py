"""EC2 key pair, sourced from a locally-generated SSH public key."""
from pathlib import Path

import pulumi
import pulumi_aws as aws


config = pulumi.Config()
THIS_DIR = Path(__file__).resolve().parent

# Anchor to this file's path so `pulumi up` works from any cwd.
public_key_path = THIS_DIR / config.require("ssh_public_key_path")

# FileNotFoundError here means I forgot to run ssh-keygen.
public_key = public_key_path.read_text().strip()

key_pair = aws.ec2.KeyPair("modelserve", public_key=public_key)
