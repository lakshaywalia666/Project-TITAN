# API and CLI reference

All protected endpoints require `Authorization: Bearer <token>`. Create operations
also require an `Idempotency-Key`. Resource updates require the numeric generation in
`If-Match`. Successful responses include `X-Request-ID`; errors use a stable code,
message and request ID.

## Control API (`:8090`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | liveness and readiness for the local store |
| GET | `/metrics` | Prometheus exposition |
| GET/POST | `/v1/projects` | list or create projects |
| GET/POST | `/v1/projects/{id}/resources` | list or create desired resources |
| GET/PATCH/DELETE | `/v1/resources/{id}` | observe, update or request deletion |
| POST | `/v1/reconcile` | operator-only bounded reconciliation batch |
| GET | `/v1/operations` | operator operation history |
| GET | `/v1/audit` | operator audit history |
| GET | `/v1/projects/{id}/usage` | aggregate metering |

Resource kinds are `service`, `database`, `model`, `knowledge_base`, `agent` and
`job`. Schemas enforce bounded, kind-specific desired state.

## AI API (`:8100`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz`, `/readyz`, `/metrics` | process signals and metrics |
| POST | `/v1/chat/completions` | OpenAI-shaped chat completion with Titan metadata |
| POST | `/v1/knowledge/documents` | idempotent versioned ingestion |
| POST | `/v1/knowledge/search` | ACL-aware hybrid retrieval |
| POST | `/v1/budgets` | project token usage and remaining budget |

## Titan Shop (`:8200`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz`, `/metrics` | service signals |
| GET | `/v1/catalog` | server-priced public catalog |
| POST | `/v1/orders` | authenticated, idempotent order/fraud/payment flow |
| GET | `/v1/orders/{id}` | project- and customer-authorized order read |

## Cloud Launchpad (`:8300`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz`, `/metrics` | planner health and Prometheus metrics |
| GET | `/v1/catalog` | public, versioned AWS/Azure/GCP service catalog with official links |
| GET | `/v1/example` | public safe workload example; intentionally not credential-ready |
| GET/POST | `/v1/assessments` | list owned assessments or create an idempotent comparison |
| GET | `/v1/assessments/{id}` | read an owned assessment |
| POST | `/v1/assessments/{id}/plans` | generate an idempotent provider dry-run plan |
| GET | `/v1/plans/{id}` | read an owned plan |

The supported input is one containerized HTTP application with optional PostgreSQL
and object storage. A plan always reports `cloud_mutation_performed: false`; it never
accepts cloud credentials or applies infrastructure. See the
[Cloud Launchpad architecture](../architecture/cloud-launchpad.md).

## CLI

```bash
PYTHONPATH=src python -m titan_control --help
PYTHONPATH=src python -m titan_ops --help
PYTHONPATH=src python -m titan_launchpad --help
```

The control CLI operates directly against a local state database for offline
administration and demonstrations. `titan_ops` creates, verifies and restores online
SQLite backups. Restore requires the exact confirmation `RESTORE_TITAN_DATA`.
