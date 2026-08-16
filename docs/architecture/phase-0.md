# Phase 0 architecture: one process

> Historical checkpoint: this describes the initial reference API, not the current
> whole-platform release. See `master-architecture.md` for current state.

## System boundary

```text
curl / browser / test client
          |
          | HTTP + JSON on localhost:8080
          v
  Python ThreadingHTTPServer
          |
          v
    TitanApplication
          |
          v
  in-memory TaskStore
```

The operating system starts one Python process. That process owns the HTTP listener, request routing, validation, task data and logs.

## Request lifecycle

1. The HTTP adapter accepts a connection.
2. It validates the request ID and body length.
3. It converts the network request into a protocol-independent `Request`.
4. `TitanApplication` selects a route and validates input.
5. `TaskStore` reads or changes process-local state.
6. The application returns a structured `Response`.
7. The HTTP adapter serializes JSON and emits a structured access log.

## Trust boundaries

- The caller is untrusted.
- Headers, paths and JSON bodies are untrusted input.
- The API binds to localhost by default, reducing accidental network exposure.
- Request bodies are limited to prevent trivial memory exhaustion.
- Incoming request IDs are accepted only when they use a restricted character set.
- No credentials are required or stored in this phase.

## Known limitations

- Tasks disappear whenever the process restarts.
- There is no authentication or multi-user authorization.
- There is no TLS, reverse proxy, database or background worker.
- The standard-library HTTP server is an educational adapter, not the final production serving stack.
- Process supervision and graceful signal handling belong to Phase 1.
