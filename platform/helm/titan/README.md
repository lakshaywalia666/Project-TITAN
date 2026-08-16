# Titan Helm chart

Create the target namespace with Restricted Pod Security labels and create the
`titan-control-plane-secrets` Secret out of band. Render and review before install:

```bash
helm template titan platform/helm/titan --namespace titan-system
helm upgrade --install titan platform/helm/titan --namespace titan-system
```

The chart keeps one replica because its default store is SQLite. It includes
resource bounds, probes, restricted containers, persistent state and default-deny
network policy.

