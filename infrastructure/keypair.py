"""EC2 key pair, sourced from a locally-generated SSH public key."""
from pathlib import Path

import pulumi
import pulumi_aws as aws


config = pulumi.Config()
THIS_DIR = Path(__file__).resolve().parent

# Resolve relative to this file so `pulumi up` works regardless of cwd.
public_key_path = THIS_DIR / config.require("ssh_public_key_path")

# Errors clearly if I forgot to run ssh-keygen — file path is in the message.
public_key = public_key_path.read_text().strip()

key_pair = aws.ec2.KeyPair("modelserve", public_key=public_key)
