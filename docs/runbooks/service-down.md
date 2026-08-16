# Runbook: service target down

1. Confirm the container or Pod exists and is not repeatedly restarting.
2. Read its last termination reason and current logs.
3. Check the read-only filesystem, writable data volume, token configuration, and port.
4. Run the health command from inside the same network namespace.
5. Restart only after preserving failure evidence; restore data first if integrity failed.

