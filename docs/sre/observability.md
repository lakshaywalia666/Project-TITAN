# Metrics, logs and traces

Every API emits structured JSON logs, validates or creates a W3C `traceparent`,
returns the current trace context, and records bounded-cardinality Prometheus request
rate, status class and latency. Request IDs remain the human-facing correlation key;
trace IDs join work across boundaries.

Prometheus rules and the Grafana dashboard cover rate, errors, duration and target
health. The optional OpenTelemetry Collector and Tempo configurations provide the
next step for native OTLP instrumentation. Authorization headers and database
statements are removed before export. Never use user IDs, request IDs, document text
or resource IDs as metric labels.

