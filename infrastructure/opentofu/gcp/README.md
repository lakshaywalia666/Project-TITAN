# GCP disposable smoke VM

Creates one non-preemptible `e2-micro` VM with a 20 GB `pd-standard` boot disk, a
custom VPC, subnet and SSH-only firewall rule. The module accepts only the
Always-Free-eligible regions `us-west1`, `us-central1` and `us-east1`. Application
ports remain on VM loopback. No load balancer, Cloud NAT, database, GKE cluster or
GPU is created.

Free-program limits are monthly and shared with other usage; public IPv4, storage,
logs or outbound data can still create charges. The common image, bootstrap and
smoke flow are documented in the [three-cloud guide](../README.md).

Use Workload Identity Federation with a dedicated service account and narrowly
scoped permissions. After every run, confirm the instance, disk, firewall, subnet
and VPC were deleted in the Google Cloud console.
