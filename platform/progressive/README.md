# Progressive delivery laboratory

Requires Argo Rollouts, Prometheus and Metrics Server. Replace the image digest and
apply the services, analysis template, Rollout and HPA. The rollout sends 5% traffic,
pauses, evaluates the 99.9% error-ratio threshold, then proceeds to 25% and 100% only
when analysis succeeds. A failed analysis stops promotion.

This is a lab manifest, not part of the SQLite control-plane install.

