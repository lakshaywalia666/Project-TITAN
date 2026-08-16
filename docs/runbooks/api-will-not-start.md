# Runbook: Titan API will not start

## User impact

Local API requests fail because no process is listening on the configured address.

## Immediate checks

1. Read the final structured log entry instead of repeatedly restarting.
2. Confirm Python is version 3.11 or newer.
3. Confirm the command is running from the repository root.
4. Inspect `TITAN_HOST`, `TITAN_PORT` and `TITAN_MAX_REQUEST_BYTES`.
5. Determine whether another process already owns the port.

## Diagnostic commands

```bash
python3 --version
printf 'host=%s port=%s max_bytes=%s\n' \
  "${TITAN_HOST:-127.0.0.1}" \
  "${TITAN_PORT:-8080}" \
  "${TITAN_MAX_REQUEST_BYTES:-16384}"
ss -ltnp | grep ':8080'
PYTHONPATH=src python3 -m titan_api
```

## Decision points

- `configuration_error`: correct the named environment variable.
- `Address already in use`: stop the unexpected listener or deliberately choose another unprivileged port.
- `Permission denied`: do not use root; select a port above 1024 and check repository permissions.
- `No module named titan_api`: set `PYTHONPATH=src` or use `make run` from the repository root.

## Validation

```bash
curl --fail --show-error http://127.0.0.1:8080/healthz
```

Expected result:

```json
{"status":"ok"}
```

