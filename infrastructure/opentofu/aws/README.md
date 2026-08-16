# AWS disposable smoke VM

Creates one `t2.micro` or `t3.micro` Ubuntu 22.04 VM, an encrypted 12 GB `gp3`
root disk, a VPC, public subnet, internet gateway and SSH-only security group.
IMDSv2 is required and burst credits use standard mode. No Elastic IP, load
balancer, NAT gateway, database or managed Kubernetes service is created.

The image must be a public GHCR digest. The VM bootstrap and smoke commands are
described in the [three-cloud guide](../README.md). AWS Free Tier eligibility varies
by account creation date and public IPv4 or other resources may be charged.

The caller needs EC2 resource permissions plus permission to read Canonical's
public Ubuntu AMI parameter from SSM. Use OIDC and a dedicated learning role.

After every run, verify in the AWS console that the instance, volume, security
group, subnet, route table, internet gateway and VPC were deleted.
