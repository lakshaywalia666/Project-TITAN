# Project Titan study guide

This guide is for studying the finished repository from first principles. Do not try
to run every component at once. Complete one phase, write its completion record, then
move forward. The existing code is the answer key—not the first thing to copy.

## How to use the repository

For each phase:

1. Read only the linked files and draw the current architecture by hand.
2. Start the smallest relevant component and make one successful request.
3. Trigger the named failure deliberately in a disposable environment.
4. Predict the result before reading the implementation.
5. Inspect logs, state and metrics; explain why the result occurred.
6. Rebuild one small part yourself in a separate practice directory.
7. Fill in the phase completion record at the end of this document.

## Phase map

| Phase | Study outcome | Repository starting point | Required practical check |
|---:|---|---|---|
| 0 | Workstation, Git and engineering habits | root README, `titan_api`, ADR 0001 | clone into clean WSL, test, run, curl, explain one request |
| 1 | Linux processes, files, signals and services | `Containerfile`, Ansible systemd unit, lifecycle module | compare SIGTERM graceful drain with SIGKILL |
| 2 | DNS, TCP, routing, HTTP and TLS | `labs/networking` | run namespace/bridge lab in disposable Linux and capture packets |
| 3 | Manual production-style stateful stack | Titan Shop and backup manager | create order, restart, back up, alter lab data, restore, verify |
| 4 | Safe Bash/Python automation | control CLI, ops CLI, controller retry | rerun commands, interrupt once, prove idempotency and bounded retry |
| 5 | Git, tests and releases | Python/portal suites, `VERSION`, release workflow | create a disposable regression, find it, build prior/new artifact |
| 6 | OCI/container internals | `Containerfile`, Compose security anchor | inspect namespaces, read-only filesystem and intentional memory limit |
| 7 | Multi-service local architecture | `compose.yaml`, `compose.data.yaml` | restart one service and prove durable state plus cache independence |
| 8 | Reproducible CI | CI workflow and lockfiles | compare clean/warm builds and explain secret isolation on PRs |
| 9 | Delivery and progressive rollout | Argo Rollout and analysis template | render canary, explain 5% gate and simulate readiness failure |
| 10 | Configuration management | Ansible role | run twice on disposable VM, introduce drift, verify targeted repair |
| 11 | IaC and cloud foundations | OpenTofu AWS/Azure/GCP labs | plan one provider, explain every resource, apply/destroy only if budget allows |
| 12 | Kubernetes fundamentals | Kustomize base | apply locally, delete Pod, watch reconciliation and endpoints |
| 13 | Kubernetes internals | network policy, storage and deep-cluster exercises | trace Pod-to-Pod/Service path and restore disposable etcd snapshot |
| 14 | Production packaging/scaling | Helm and hardened overlay | render chart, break/fix value, test disruption and Shop HPA |
| 15 | GitOps | Argo CD Application | cause safe drift, observe correction, revert commit for rollback |
| 16 | Metrics, logs and traces | observability package and configs | follow request/trace ID, inspect metrics, identify cardinality mistake |
| 17 | SRE | SLO, alerts and runbooks | calculate budget; compare severe outage with slow burn |
| 18 | DevSecOps/supply chain | security/release workflows, SBOM, policy | detect fake secret, scan image, inspect SBOM, verify signature flow |
| 19 | Kubernetes zero trust | restricted namespace, RBAC boundary, network policy, Kyverno | add/remove one permission and prove success then denial |
| 20 | Data platform | optional PostgreSQL/Redis/Redpanda/MinIO profiles | restore relational data, remove cache, duplicate event safely |
| 21 | Titan control plane | `titan_control` API/CLI/store/controller | repeat create, restart controller, inject drift, send stale update |
| 22 | Kubernetes operator | CRD, pure planner and in-cluster adapter | delete child, update replicas, exercise finalizer and slow provider |
| 23 | Developer platform | Titan Command Center | time project/resource creation via raw API and then portal |
| 24 | GPU foundations | GPU smoke test | inspect device/VRAM on GPU host and diagnose unschedulable request |
| 25 | Inference platform | vLLM and KServe manifests | on timed A10 compare cold/warm, concurrency and context length |
| 26 | AI gateway | gateway, budgets, routes and circuit breaker | kill backend, observe permitted fallback, exhaust budget |
| 27 | RAG/knowledge plane | `knowledge.py` and AI API | ingest/update/delete, compare chunks, prove cross-ACL denial |
| 28 | LLMOps/evaluation | evaluation engine and 120-case suite | run two candidate behaviors through quality/cost release gates |
| 29 | Agent/tool runtime | capability gateway and approval store | read-only health call, prohibited call, timeout and exact approval |
| 30 | Agent security/red team | trust labels, egress policy and red-team tests | inject instructions in document/tool output and verify external denial |
| 31 | AI observability/SRE agent | read-only investigator | correlate deploy/metrics/traces; remove one source and see confidence fall |
| 32 | Autonomous remediation | remediation engine | safe worker recovery, rate-limit, stale precondition and rollback check |
| 33 | Training platform | Kueue flavor/queues/job | exceed GPU quota, observe queue, study checkpoint/preemption behavior |
| 34 | Multi-tenancy/FinOps/scheduling | capacity planner, quotas and usage ledgers | exhaust one tenant while another remains placeable; compare strategies |
| 35 | Chaos/DR/multi-cloud | chaos runner/manifests, IaC, GitOps, backup | declare lab lost and execute the documented restore game day |
| 36 | Final capstone/extreme systems | E2E test, edge balancer, microVM planner | rebuild Titan, deploy Shop through golden path, run incident narrative |

## Recommended order on the available machines

Use the 16 GB laptop/WSL for phases 0–12, 16–23 and 26–32. Use the GTX 1650
machine for a local Kubernetes cluster and small phase 24 exercises. Use one free-tier
cloud provider at a time for phases 10–15 and 35. Use a rented A10 only for a short
phase 25 benchmark after all offline gateway tests pass. Phases 33 and large-scale
parts of 35 are manifest/simulation studies unless temporary capacity is explicitly
budgeted.

## Phase completion record

Create one copy per phase under `docs/learning/completions/`:

```text
Phase and date:
Outcome in one sentence:
Architecture before and after:
Successful behavior demonstrated:
Failure deliberately triggered and diagnosed:
Security boundary added or verified:
Telemetry used to explain behavior:
Cost/resources consumed and cleanup performed:
Trade-off or ADR I can explain without notes:
Remaining limitation:
Next-phase entry criteria:
```

A phase is incomplete if a command happened to work but you cannot explain the data
flow, failure mode, trust boundary and cleanup.
