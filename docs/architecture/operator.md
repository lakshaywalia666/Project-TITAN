# Titan Kubernetes operator contract

`TitanService` owns one child Deployment. The pure planning module is tested without
a cluster; the dependency-free in-cluster adapter translates its actions through the
Kubernetes REST API. This separation keeps safety decisions deterministic and
reviewable while leaving the deployed controller executable.

The operator adds a finalizer before provisioning, repairs deleted or drifted child
Deployments, records `observedGeneration`, requeues slow external providers with a
bounded delay, and deletes children before removing the finalizer. It never accepts
`latest` images or copies arbitrary Pod fields from the custom resource.

The operator reconciles only its own namespace and its Role can touch only
`TitanService` objects/status and Deployments. It uses optimistic resource versions,
server-side apply with a dedicated field manager, owner references, per-resource
requeue deadlines and exponential API-failure backoff.

```bash
kubectl apply -k platform/operator
kubectl get titanservices -n titan-system --watch
```
