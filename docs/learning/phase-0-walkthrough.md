# Phase 0 walkthrough

> This is the preserved first learning checkpoint. Follow `study-guide.md` for the
> complete sequence.

Read the implementation in this order:

1. `src/titan_api/__main__.py` - program entry point.
2. `src/titan_api/config.py` - environment input and startup validation.
3. `src/titan_api/server.py` - network-to-application adapter.
4. `src/titan_api/app.py` - routes, validation and response contracts.
5. `src/titan_api/models.py` - process-local state.
6. `tests/test_application.py` - behavior without a network.
7. `tests/test_server.py` - behavior across a real local TCP connection.

## Concepts to explain

- Why the service binds to `127.0.0.1` by default.
- Why a request body needs a maximum size.
- Why errors use stable codes as well as human-readable messages.
- Why the application and HTTP server are separate.
- Why `TaskStore` uses a lock.
- Why process-local task data disappears after restart.
- What a request correlation ID provides.

## Deliberate limitations

Do not add a database, Dockerfile, authentication, CI pipeline or Kubernetes manifest yet. Each belongs to a later problem-driven phase.
