# Scaling boundary

The default control plane is a single-writer SQLite deployment. It must remain at one
replica and uses `Recreate` during upgrades. Scaling it horizontally against a shared
SQLite file would risk lock contention, storage attachment failures and misleading
availability claims.

The stateless Titan Shop reference workload may use the included HPA laboratory. A
future HA control-plane release must first introduce a PostgreSQL store, leader
election for controllers, independent AI/portal Deployments and a migration/rollback
plan. Until those gates pass, the single-node constraint is an explicit safety
property rather than a hidden limitation.

