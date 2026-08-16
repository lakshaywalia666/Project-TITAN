# Runbook: backup and restore

Back up both state stores while the services are live:

```bash
python -m titan_ops backup \
  --control var/titan-control.db \
  --knowledge var/titan-knowledge.db \
  --destination backups/2026-08-16
python -m titan_ops verify backups/2026-08-16
```

The command uses SQLite's online backup API, runs an integrity check and records
size and SHA-256 for every artifact. Tokens and environment files are intentionally
excluded.

Stop all Titan writers before restore. Restore refuses to run without the literal
confirmation and verifies the backup before replacing either destination:

```bash
python -m titan_ops restore backups/2026-08-16 \
  --control var/titan-control.db \
  --knowledge var/titan-knowledge.db \
  --confirm RESTORE_TITAN_DATA
```

After restoration, start the APIs, check both health endpoints, reconcile pending
operations, and run one knowledge query. A backup that has never passed a restore
drill is not considered a reliable backup.

