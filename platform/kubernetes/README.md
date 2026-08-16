# Kubernetes deployment

The base deployment runs the control API, reconciliation controller and AI API as
three containers in one Pod. This is deliberate while SQLite is the local persistence
layer: one Pod and a `Recreate` rollout avoid pretending that a shared file database
provides horizontally scalable control-plane persistence.

Before applying, create the API token Secret without committing the token:

```bash
kubectl create namespace titan-system --dry-run=client -o yaml | kubectl apply -f -
kubectl -n titan-system create secret generic titan-control-plane-secrets \
  --from-literal=TITAN_ADMIN_TOKEN="$(openssl rand -hex 32)"
kubectl apply -k platform/kubernetes/overlays/local
```

Production evolution replaces SQLite with PostgreSQL, separates API/controller scaling, enables workload identity and grants a narrowly scoped Kubernetes reconciliation role.
