# Disposable three-cloud smoke deployment

This directory deploys the same digest-pinned Titan container image to one small,
temporary VM on AWS, Azure or GCP. It is designed for a short learning smoke test,
not permanent hosting.

The VM automatically starts the control API, controller, offline AI API and Titan
Shop. Application ports bind to the VM's loopback interface only. The only inbound
firewall rule is SSH from the runner's current public IPv4 `/32`. An administrator
token is generated on the VM and never stored in OpenTofu state.

## Safest path: GitHub Actions

1. Push the repository and create a version tag such as `v0.1.0`.
2. Let `.github/workflows/release.yml` test, build, attest, sign and publish the
   image to GHCR. The smoke workflow verifies the keyless signature and accepts
   only images produced by this repository's tagged release workflow.
3. Make that GHCR package public and copy its immutable `sha256` digest.
4. Create a protected GitHub environment named `cloud-smoke`. Add a required
   reviewer and the OIDC variables below. Do not create long-lived access keys.
5. Manually run `disposable-cloud-smoke`, select exactly one provider, paste the
   public image as `ghcr.io/OWNER/titan@sha256:DIGEST`, and enter the exact
   confirmation shown by the workflow.
6. Require both `TITAN_CLOUD_SMOKE_OK` and a successful destroy in the log. Then
   confirm in the provider console that the VM, disk, address and network are gone.

The workflow generates an ephemeral SSH key, discovers the runner IP, applies one
module, performs authenticated health checks inside the VM, and executes
`tofu destroy` from an exit trap. A killed runner or provider outage can still
prevent cleanup, so the final console check is mandatory.

### GitHub environment variables

| Provider | Variables |
|---|---|
| All | `TITAN_OWNER` (lowercase letters, digits, hyphen or underscore) |
| AWS | `AWS_ROLE_ARN`, `AWS_REGION` |
| Azure | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_LOCATION` |
| GCP | `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_ZONE` |

The cloud identities need permission to create and delete only the resources in
the selected module. Prefer a separate learning account, subscription or project,
budget alerts, quotas and provider-native policy limits.

## Cost boundaries

No Terraform/OpenTofu module can promise a zero bill. Eligibility depends on the
account, creation date, region, quotas and resources already consumed that month.
Public IPv4 addresses, disks, images, logs and outbound traffic can be charged even
when VM compute is covered.

- AWS accounts created on or after 15 July 2025 use the newer six-month free-plan
  and credit model. Older eligible accounts use the legacy EC2 monthly limits.
  Check the current [AWS EC2 Free Tier documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html).
- Azure advertises eligible new-account monthly hours for selected burstable VM
  sizes, but related resources can still incur charges. Check
  [Azure Free](https://azure.microsoft.com/free/).
- GCP's always-free Compute Engine allowance is restricted to one eligible
  `e2-micro` in specified US regions, with storage and outbound-data limits. GPUs
  are not included. Check the
  [Google Cloud Free Program](https://cloud.google.com/free/docs/free-cloud-features).

This implementation deliberately avoids managed Kubernetes, NAT gateways, load
balancers, managed databases, premium disks, GPUs and public application ports.

## Manual path

The automated script is the preferred disposable path:

```bash
export TITAN_IMAGE='ghcr.io/OWNER/titan@sha256:64_HEX_DIGEST'
export TITAN_OWNER='your-lowercase-name'
export TITAN_PROVIDER='aws'
export TITAN_CONFIRM='DEPLOY_AND_DESTROY_TITAN'
bash infrastructure/opentofu/scripts/cloud-smoke.sh
```

Use `azure` or `gcp` as `TITAN_PROVIDER` after authenticating OpenTofu with short-lived
provider credentials. The script requires `tofu`, `curl`, `ssh`, `ssh-keygen` and
GNU `date`.

For direct module use, copy `terraform.tfvars.example` to the ignored
`terraform.tfvars`, replace every placeholder, and run:

```bash
tofu init
tofu fmt -check
tofu validate
tofu plan -out=titan.plan
tofu apply titan.plan
tofu output smoke_check_command
tofu output portal_tunnel_command
tofu destroy
```

The tunnel maps local ports 8090, 8100 and 8200 to the VM. Retrieve the token only
over SSH with the module's `token_command`. Never paste the token into state,
workflow variables or logs.

Real `terraform.tfvars`, state, plans and generated SSH keys are ignored. Apply
only one provider at a time and destroy it the same day.
