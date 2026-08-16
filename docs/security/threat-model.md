# Titan threat model

## Assets and trust boundaries

Titan protects cloud credentials, API bearer tokens, desired resource state, audit
history, knowledge documents, model budgets, tool approvals and recovery artifacts.
The browser portal, control API, AI API, reconciliation provider, model backend,
Kubernetes API and CI runner are separate trust boundaries.

```text
operator browser -> authenticated APIs -> SQLite state
                                  |-> provider / Kubernetes boundary
                                  |-> model backend boundary
CI identity -> registry -> admission policy -> runtime
```

## Highest-risk abuse cases

| Threat | Control | Residual risk |
|---|---|---|
| Stolen bootstrap token | hashed comparison, localhost bind, environment-only secret, RBAC | static tokens still require planned rotation |
| Cross-project access | project-scoped identity checks before state or retrieval | administrator role remains high impact |
| Prompt requests a dangerous action | external capability policy, typed arguments, risk tiers, single-use exact approvals | tool implementation bugs |
| Document leaks through retrieval | ACL filter before scoring and return | incorrectly assigned source ACL |
| Duplicate or replayed mutation | scoped idempotency keys and request fingerprint | deliberate replay inside retention window |
| Lost update | generation precondition (`If-Match`) | poorly behaved clients can retry stale intent |
| Provider outage | bounded retry, backoff, observed generation, circuit breaker | prolonged partial availability |
| Malicious image or dependency | lockfiles, scanning, SBOM, provenance, keyless signing, admission policy | compromised upstream maintainer before detection |
| Database loss or tampering | online backup, checksum, SQLite integrity check, guarded atomic restore | backup directory must be separately protected |
| Portal token persistence | token kept only in component memory | malicious same-origin JavaScript could still read it |

## Security invariants

1. User input never directly grants roles, model access, tools or approvals.
2. Retrieval filters authorization before returning content.
3. Reconciliation changes observed state; API writes change desired state only.
4. Every accepted or denied control-plane mutation produces an audit event.
5. Automatic remediation is disabled by a global kill switch and constrained by
   risk, rate and rollback verification.
6. Secrets are never stored in Git, logs, portal storage, backup manifests or SBOMs.

