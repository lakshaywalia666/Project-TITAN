# Service-level objectives

Titan's local production profile uses the same operational contract as a larger
deployment, while keeping the tooling free and runnable on one machine.

| Service | Indicator | Objective | Window |
|---|---|---:|---:|
| Control API | non-5xx responses / all responses | 99.9% | 30 days |
| AI API | non-5xx responses / all responses | 99.5% | 30 days |
| Control API | p95 request latency | under 500 ms | rolling 5 min |
| AI API | p95 gateway latency, excluding model queue time | under 1 s | rolling 5 min |

The alerts use multi-window-style burn thresholds rather than alerting on every
isolated failure. A fast burn pages; a slow burn creates work. Planned local
shutdowns are outside the SLO window because a learning laptop is not a 24/7
production site.

Run the observability profile with:

```bash
docker compose --profile observability up --build
```

Prometheus binds to `127.0.0.1:9090`; Grafana binds to `127.0.0.1:3001`.

