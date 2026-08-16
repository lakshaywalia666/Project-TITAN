# Runbook: high HTTP error rate

1. Confirm which `job`, `route`, and status class are burning budget in Grafana.
2. Correlate the first failing request with the structured service log by request ID.
3. Check `/healthz`, then `/metrics`, disk space, and the newest operation failures.
4. If a release caused the change, stop rollout and restore the last verified image.
5. If a dependency failed, keep the AI gateway fallback enabled and reduce traffic.
6. Record the incident timeline and do not reset metrics to make the alert disappear.

