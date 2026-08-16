"""Health-aware round-robin routing with conservative retry semantics."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Mapping


class NoHealthyBackend(RuntimeError):
    pass


@dataclass(slots=True)
class Backend:
    name: str
    endpoint: str
    healthy: bool = True
    consecutive_failures: int = 0


@dataclass(frozen=True, slots=True)
class ProxyResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    backend: str
    attempts: int


Transport = Callable[[Backend, str, str, bytes, float, str], tuple[int, Mapping[str, str], bytes]]


class LayerSevenBalancer:
    def __init__(
        self,
        backends: tuple[Backend, ...],
        *,
        request_timeout_seconds: float = 2.0,
        failure_threshold: int = 2,
    ) -> None:
        if not backends or len({backend.name for backend in backends}) != len(backends):
            raise ValueError("at least one uniquely named backend is required")
        self.backends = list(backends)
        self.request_timeout_seconds = request_timeout_seconds
        self.failure_threshold = failure_threshold
        self._cursor = 0
        self._lock = threading.Lock()

    def forward(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        request_id: str,
        transport: Transport,
    ) -> ProxyResponse:
        safe_retry = method.upper() in {"GET", "HEAD", "OPTIONS"}
        maximum_attempts = min(2 if safe_retry else 1, len(self.backends))
        attempted: set[str] = set()
        last_error: OSError | None = None
        for attempt in range(1, maximum_attempts + 1):
            backend = self._next_backend(exclude=attempted)
            attempted.add(backend.name)
            try:
                status, headers, response_body = transport(
                    backend,
                    method.upper(),
                    path,
                    body,
                    self.request_timeout_seconds,
                    request_id,
                )
                self._record_success(backend)
                return ProxyResponse(status, headers, response_body, backend.name, attempt)
            except (ConnectionError, TimeoutError, OSError) as error:
                last_error = OSError(str(error))
                self._record_failure(backend)
        raise NoHealthyBackend(f"request could not reach a healthy backend: {last_error}")

    def run_health_checks(self, probe: Callable[[Backend, float], bool]) -> None:
        for backend in self.backends:
            try:
                healthy = bool(probe(backend, self.request_timeout_seconds))
            except (ConnectionError, TimeoutError, OSError):
                healthy = False
            with self._lock:
                backend.healthy = healthy
                backend.consecutive_failures = 0 if healthy else self.failure_threshold

    def _next_backend(self, *, exclude: set[str]) -> Backend:
        with self._lock:
            for offset in range(len(self.backends)):
                index = (self._cursor + offset) % len(self.backends)
                backend = self.backends[index]
                if backend.healthy and backend.name not in exclude:
                    self._cursor = (index + 1) % len(self.backends)
                    return backend
        raise NoHealthyBackend("no untried healthy backend is available")

    def _record_success(self, backend: Backend) -> None:
        with self._lock:
            backend.healthy = True
            backend.consecutive_failures = 0

    def _record_failure(self, backend: Backend) -> None:
        with self._lock:
            backend.consecutive_failures += 1
            if backend.consecutive_failures >= self.failure_threshold:
                backend.healthy = False

