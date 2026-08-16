# Runbook: chaos and disaster recovery

Chaos is allowed only in an explicitly labeled lab target with a healthy baseline,
declared expected impact, measurable abort condition, short duration and tested
recovery action. Production requires a literal confirmation at execution time. The
Chaos Mesh examples are inert unless the CRDs are installed and the target is labeled
`chaos.titan.dev/allowed=true`.

For the disaster-recovery game day, declare the lab cluster lost, rebuild the host or
cloud resources from OpenTofu and Ansible, install Kubernetes dependencies, let Argo
CD reconstruct declared workloads, restore SQLite state from a verified backup,
rotate the bootstrap token, run reconciliation and test Titan Shop plus one authorized
knowledge query. Record recovery time and data-loss window against the declared RTO
and RPO.

Local target: RTO 60 minutes, RPO 24 hours. These objectives are learning targets,
not a claim of multi-region availability.

