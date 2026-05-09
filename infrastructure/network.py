"""VPC + subnet + IGW + route table + security group for the EC2 host."""
import pulumi_aws as aws


# DNS hostnames so EC2 instances get a public DNS name, not just an IP.
vpc = aws.ec2.Vpc(
    "modelserve",
    cidr_block="10.0.0.0/16",
    enable_dns_hostnames=True,
    enable_dns_support=True,
)

igw = aws.ec2.InternetGateway("modelserve-igw", vpc_id=vpc.id)

# map_public_ip_on_launch=True so instances get a public IP without an EIP.
public_subnet = aws.ec2.Subnet(
    "modelserve-public",
    vpc_id=vpc.id,
    cidr_block="10.0.1.0/24",
    map_public_ip_on_launch=True,
)

# Default route to IGW. Without this the subnet is effectively private.
route_table = aws.ec2.RouteTable(
    "modelserve-public-rt",
    vpc_id=vpc.id,
    routes=[{"cidr_block": "0.0.0.0/0", "gateway_id": igw.id}],
)

# Without the association the route is defined but unused.
aws.ec2.RouteTableAssociation(
    "modelserve-public-rta",
    subnet_id=public_subnet.id,
    route_table_id=route_table.id,
)

# All ports open. Sandbox only. In prod: scope SSH to a CIDR, put services
# behind an ALB with TLS.
security_group = aws.ec2.SecurityGroup(
    "modelserve-sg",
    description="ModelServe service ports",
    vpc_id=vpc.id,
    ingress=[
        {"protocol": "tcp", "from_port": 22,   "to_port": 22,   "cidr_blocks": ["0.0.0.0/0"], "description": "SSH"},
        {"protocol": "tcp", "from_port": 8000, "to_port": 8000, "cidr_blocks": ["0.0.0.0/0"], "description": "FastAPI"},
        {"protocol": "tcp", "from_port": 3000, "to_port": 3000, "cidr_blocks": ["0.0.0.0/0"], "description": "Grafana"},
        {"protocol": "tcp", "from_port": 5000, "to_port": 5000, "cidr_blocks": ["0.0.0.0/0"], "description": "MLflow UI"},
        {"protocol": "tcp", "from_port": 9090, "to_port": 9090, "cidr_blocks": ["0.0.0.0/0"], "description": "Prometheus"},
    ],
    egress=[{
        "protocol": "-1",   # -1 = all protocols
        "from_port": 0,
        "to_port": 0,
        "cidr_blocks": ["0.0.0.0/0"],
        "description": "all outbound (ECR pull, git clone, Kaggle)",
    }],
)
