# ADR-0001: Begin with a dependency-free Python API

- Status: Accepted
- Date: 2026-08-16
- Owners: Project Titan

## Context

Titan needs a real process that later infrastructure layers can run, observe, secure, break and recover. Beginning with Kubernetes, a database or a large application would obscure the mechanisms being learned.

## Problem

Create the smallest useful network service while keeping setup reproducible on a clean Linux machine and retaining enough structure for meaningful tests and later evolution.

## Constraints

- The learner has basic experience and limited hardware and budget.
- Phase 0 must not require Docker, Kubernetes, cloud services or a package download.
- The program must run on Linux and in WSL.
- The design must make later replacement of the HTTP adapter possible.

## Options considered

### A. Python standard library

No runtime dependencies and exposes the underlying HTTP mechanics. More validation and routing code must be maintained locally.

### B. FastAPI with Uvicorn

Excellent API ergonomics and schema generation, but introduces a framework, ASGI server and dependency installation before the learner understands the request path.

### C. Go standard library

Produces a simple static binary and is a strong long-term control-plane language, but creates a steeper first step for a learner without programming experience.

## Decision

Use Python 3.11+ and its standard library for Titan v0.001. Keep application behavior separate from the HTTP adapter so a later framework or Go service can replace the edge without rewriting the initial domain tests.

## Consequences

- A clean supported Python installation is sufficient.
- The learner can inspect every layer involved in routing and JSON serialization.
- OpenAPI generation, mature middleware and production-server features are intentionally absent.
- The local code must explicitly implement body limits, stable errors and request correlation.

## Security impact

The default listener is localhost. Input size, content type, JSON structure and request IDs are validated. There are no secrets or privileged operations.

## Reliability impact

The application has no durable state and a process restart loses tasks. That limitation is deliberate evidence for a later storage phase.

## Cost impact

None beyond the existing computer.

## Reversal plan

Replace `server.py` with a framework or Go adapter while retaining the route contract and application-level tests. Record that change in a superseding ADR.

