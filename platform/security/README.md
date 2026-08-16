# Kubernetes security controls

The base manifests enforce the Restricted Pod Security Standard, disable automatic
service-account token mounting, run as a numeric non-root identity, remove Linux
capabilities, use a read-only root filesystem, and default-deny service traffic.

The optional Kyverno policy is installed separately because a policy engine is not
assumed on a free local cluster:

```bash
kubectl apply -f platform/security/kyverno/baseline-policy.yaml
```

Test policies in audit mode before enforcing them in an existing shared cluster.

