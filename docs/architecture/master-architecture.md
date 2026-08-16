# Master architecture

## Design principles

Titan keeps one source of truth per state class, separates desired and observed
state, assumes every request can be retried, bounds every retry and budget, and keeps
model output outside the authorization boundary. The free local shape is small on
purpose; optional profiles reveal the same boundaries used by larger platforms.

## Request and reconciliation path

```text
operator -> portal / CLI -> bearer authentication -> RBAC + project membership
                    -> schema + quota + idempotency validation
                    -> SQLite desired state + audit + pending operation
                    -> controller claims operation
                    -> provider applies or deletes actual resource
                    -> status + observed generation + audit result
```

API mutations never claim that provisioning is complete. A `202` resource may be
pending, updating, deleting or failed. The controller is restart-safe because desired
state and operations are durable. Stale writers are rejected by generation checks.

## AI path

```text
caller -> model authorization -> token reservation -> complexity route
       -> circuit / timeout -> vLLM or offline backend -> usage + cost ledger
       -> fallback only to another permitted model
```

Knowledge ingestion versions source documents and chunks them deterministically.
Retrieval checks ACLs before returning content, combines lexical and hash-vector
scores, and emits stable citations. Untrusted content is labeled; capabilities,
approvals and egress decisions remain external to the model.

## Runtime boundaries

| Boundary | Source of truth | Failure behavior |
|---|---|---|
| Control plane | `titan-control.db` | API remains explicit; controller retries up to its budget |
| Knowledge plane | `titan-knowledge.db` | model requests continue without unauthorized retrieval |
| Shop | `titan-shop.db` | idempotency prevents duplicate order/payment |
| Portal | none | demo or reconnect; workloads continue |
| Offline model | process memory | zero-cost deterministic response |
| vLLM | external GPU endpoint | circuit opens and permitted fallback is attempted |

## Deployment and trust

Containers run as UID 10001 with no capabilities and a read-only root filesystem.
Kubernetes disables service-account token mounting, applies the Restricted Pod
Security Standard and default-deny network policy. GitOps owns declared manifests;
the Titan controller owns Titan resource state; neither should mutate the other's
fields.

CI tests source and rendered manifests. The security pipeline scans secrets and
images and emits an SBOM. Version tags publish an attested, keyless-signed image.
Backups use SQLite's online API, cryptographic checksums, integrity checks and guarded
atomic restore.

## Deliberate limitations

- The control plane is single-replica until a PostgreSQL store and controller leader
  election exist.
- Static bootstrap tokens and local HMAC JWTs are not enterprise identity federation.
- Hash embeddings and offline model responses support learning and tests, not model
  quality claims.
- Multi-region, KServe, Kueue, Chaos Mesh and GPU manifests are opt-in laboratories
  requiring their respective controllers and hardware.
