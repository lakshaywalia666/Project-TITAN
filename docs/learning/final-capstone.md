# Final capstone scenario

1. Build the container and portal from lockfiles.
2. Start control API, controller, AI API, Titan Shop and observability.
3. Create an organization-equivalent project through the API or portal.
4. Submit Titan Shop desired state and observe generation convergence.
5. Ingest an authorized support runbook and retrieve it with a citation.
6. Call the AI gateway in offline mode, then optionally switch to timed vLLM.
7. Place the same Shop order twice and prove one payment exists.
8. Introduce a controlled latency/error scenario and observe SLO burn.
9. Let the read-only investigator correlate deployment and telemetry.
10. Exercise an approval-gated remediation in the lab and verify rollback behavior.
11. Create and verify a backup, declare the lab lost, rebuild and restore it.
12. Produce an incident narrative based only on provable telemetry.

The automated `test_end_to_end.py` is the fast executable version of the central
path. The human capstone adds infrastructure, observability and recovery practice.

