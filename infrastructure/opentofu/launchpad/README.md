# Cloud Launchpad OpenTofu planners

These three modules turn an approved Launchpad workload into a reviewable provider
architecture contract. They deliberately contain no cloud provider configuration and
no mutable resources, so `tofu init`, `validate`, and `plan` require no credentials and
cannot create a bill.

```powershell
tofu -chdir=infrastructure/opentofu/launchpad/aws init -backend=false
tofu -chdir=infrastructure/opentofu/launchpad/aws validate
tofu -chdir=infrastructure/opentofu/launchpad/aws plan -var-file=example.tfvars
```

Repeat with `azure` or `gcp`. The outputs show the managed services, public inputs,
security controls, and cost-review URL. A later credentialed phase must implement and
review the actual provider resources; the prototype must never be mistaken for an
applied deployment.
