"""HTTP API for projects, resources, operations, audit and reconciliation."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Type
from urllib.parse import parse_qs, urlsplit

from titan_api.server import select_request_id
from titan_control.auth import AuthenticationError, Authenticator
from titan_control.domain import Identity
from titan_control.reconciler import LocalResourceProvider, Reconciler
from titan_control.service import (
    AuthorizationError,
    ControlPlane,
    QuotaExceededError,
    ValidationError,
)
from titan_control.store import (
    ConflictError,
    GenerationConflictError,
    IdempotencyConflictError,
    NotFoundError,
    SQLiteStore,
)
from titan_observability.metrics import MetricsRegistry
from titan_observability.tracing import TraceContext

LOGGER = logging.getLogger("titan.control.api")


@dataclass(frozen=True, slots=True)
class HTTPSettings:
    host: str = "127.0.0.1"
    port: int = 8090
    max_request_bytes: int = 65_536
    database_path: str = "var/titan-control.db"
    allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "HTTPSettings":
        source = os.environ if environ is None else environ
        host = source.get("TITAN_CONTROL_HOST", "127.0.0.1").strip()
        database_path = source.get(
            "TITAN_DATABASE", "var/titan-control.db"
        ).strip()
        if not host or not database_path:
            raise ValueError("control-plane host and database path must not be empty")
        return cls(
            host=host,
            port=_bounded_int(source.get("TITAN_CONTROL_PORT", "8090"), 1, 65_535),
            max_request_bytes=_bounded_int(
                source.get("TITAN_CONTROL_MAX_REQUEST_BYTES", "65536"),
                1_024,
                1_048_576,
            ),
            database_path=database_path,
            allowed_origins=tuple(
                origin.strip()
                for origin in source.get(
                    "TITAN_CORS_ALLOWED_ORIGINS",
                    "http://localhost:3000,http://127.0.0.1:3000",
                ).split(",")
                if origin.strip()
            ),
        )


def create_handler(
    *,
    control_plane: ControlPlane,
    store: SQLiteStore,
    authenticator: Authenticator,
    settings: HTTPSettings,
    metrics: MetricsRegistry | None = None,
) -> Type[BaseHTTPRequestHandler]:
    metric_registry = metrics or MetricsRegistry()

    class ControlPlaneRequestHandler(BaseHTTPRequestHandler):
        server_version = "Titan-Control"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802
            self._handle_request()

        def do_POST(self) -> None:  # noqa: N802
            self._handle_request()

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle_request()

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle_request()

        def do_OPTIONS(self) -> None:  # noqa: N802
            origin = self.headers.get("Origin", "")
            if origin not in settings.allowed_origins:
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                "Authorization, Content-Type, Idempotency-Key, If-Match, X-Request-ID",
            )
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _handle_request(self) -> None:
            started = time.monotonic()
            request_id = select_request_id(self.headers.get("X-Request-ID"))
            trace = TraceContext.from_header(self.headers.get("traceparent"))
            self._trace_context = trace
            status = 500
            request_path = urlsplit(self.path).path
            if request_path == "/metrics" and self.command == "GET":
                body = metric_registry.render_prometheus()
                self.send_response(200)
                self.send_header(
                    "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Request-ID", request_id)
                self.end_headers()
                self.wfile.write(body)
                return
            try:
                path = request_path
                if path == "/healthz" and self.command == "GET":
                    status, document, extra_headers = 200, {"status": "ok"}, {}
                else:
                    identity = authenticator.authenticate(
                        self.headers.get("Authorization")
                    )
                    body = self._read_json_body(request_id)
                    status, document, extra_headers = self._dispatch(
                        identity=identity,
                        path=path,
                        body=body,
                        request_id=request_id,
                    )
            except _HTTPError as error:
                status = error.status
                document = {
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "request_id": request_id,
                        "trace_id": trace.trace_id,
                        "span_id": trace.span_id,
                    }
                }
                extra_headers = error.headers
            except AuthenticationError as error:
                status = 401
                document = {
                    "error": {
                        "code": "UNAUTHENTICATED",
                        "message": str(error),
                        "request_id": request_id,
                    }
                }
                extra_headers = {"WWW-Authenticate": "Bearer"}
            except AuthorizationError as error:
                status, document, extra_headers = self._error_document(
                    403, "FORBIDDEN", str(error), request_id
                )
            except NotFoundError as error:
                status, document, extra_headers = self._error_document(
                    404, "NOT_FOUND", str(error), request_id
                )
            except IdempotencyConflictError as error:
                status, document, extra_headers = self._error_document(
                    409, "IDEMPOTENCY_CONFLICT", str(error), request_id
                )
            except GenerationConflictError as error:
                status, document, extra_headers = self._error_document(
                    409, "GENERATION_CONFLICT", str(error), request_id
                )
            except ConflictError as error:
                status, document, extra_headers = self._error_document(
                    409, "CONFLICT", str(error), request_id
                )
            except QuotaExceededError as error:
                status, document, extra_headers = self._error_document(
                    409, "QUOTA_EXCEEDED", str(error), request_id
                )
            except (ValidationError, ValueError, json.JSONDecodeError) as error:
                status, document, extra_headers = self._error_document(
                    422, "INVALID_REQUEST", str(error), request_id
                )
            except Exception:
                LOGGER.exception("unhandled control-plane request error")
                status, document, extra_headers = self._error_document(
                    500,
                    "INTERNAL_ERROR",
                    "The control plane could not complete the request",
                    request_id,
                )

            self._send_json(status, document, request_id, extra_headers)
            metric_registry.observe_http(
                service="control-api",
                method=self.command,
                route=_normalized_route(request_path),
                status=status,
                duration_seconds=time.monotonic() - started,
            )
            LOGGER.info(
                json.dumps(
                    {
                        "event": "control_http_request",
                        "request_id": request_id,
                        "method": self.command,
                        "path": self.path,
                        "status": status,
                        "duration_ms": round(
                            (time.monotonic() - started) * 1_000, 3
                        ),
                    },
                    separators=(",", ":"),
                )
            )

        def _dispatch(
            self,
            *,
            identity: Identity,
            path: str,
            body: Mapping[str, Any] | None,
            request_id: str,
        ) -> tuple[int, object, Mapping[str, str]]:
            segments = [segment for segment in path.split("/") if segment]

            if segments == ["v1", "projects"]:
                if self.command == "GET":
                    projects = control_plane.list_projects(identity=identity)
                    return 200, {"items": [item.to_dict() for item in projects]}, {}
                if self.command == "POST":
                    document = self._require_body(body)
                    project = control_plane.create_project(
                        identity=identity,
                        name=str(document.get("name", "")),
                        quota=document.get("quota"),
                        idempotency_key=self._idempotency_key(),
                    )
                    return 201, project.to_dict(), {"Location": f"/v1/projects/{project.id}"}
                raise _HTTPError(405, "METHOD_NOT_ALLOWED", "Use GET or POST")

            if len(segments) == 4 and segments[:2] == ["v1", "projects"] and segments[3] == "resources":
                project_id = segments[2]
                if self.command == "GET":
                    resources = control_plane.list_resources(
                        identity=identity, project_id=project_id
                    )
                    return 200, {"items": [item.to_dict() for item in resources]}, {}
                if self.command == "POST":
                    document = self._require_body(body)
                    resource = control_plane.create_resource(
                        identity=identity,
                        project_id=project_id,
                        kind=str(document.get("kind", "")),
                        name=str(document.get("name", "")),
                        spec=document.get("spec", {}),
                        idempotency_key=self._idempotency_key(),
                    )
                    return 202, resource.to_dict(), {"Location": f"/v1/resources/{resource.id}"}
                raise _HTTPError(405, "METHOD_NOT_ALLOWED", "Use GET or POST")

            if len(segments) == 3 and segments[:2] == ["v1", "resources"]:
                resource_id = segments[2]
                if self.command == "GET":
                    resource = control_plane.get_resource(
                        identity=identity, resource_id=resource_id
                    )
                    return 200, resource.to_dict(), {"ETag": str(resource.generation)}
                if self.command == "PATCH":
                    document = self._require_body(body)
                    generation = self._expected_generation()
                    resource = control_plane.update_resource(
                        identity=identity,
                        resource_id=resource_id,
                        spec=document.get("spec", {}),
                        expected_generation=generation,
                    )
                    return 202, resource.to_dict(), {"ETag": str(resource.generation)}
                if self.command == "DELETE":
                    resource = control_plane.delete_resource(
                        identity=identity, resource_id=resource_id
                    )
                    return 202, resource.to_dict(), {}
                raise _HTTPError(405, "METHOD_NOT_ALLOWED", "Use GET, PATCH or DELETE")

            if segments == ["v1", "reconcile"] and self.command == "POST":
                self._require_operator(identity)
                document = body or {}
                limit = int(document.get("limit", 20))
                if not 1 <= limit <= 100:
                    raise ValidationError("reconcile limit must be between 1 and 100")
                summary = Reconciler(store, LocalResourceProvider()).run_once(limit)
                return 200, {
                    "claimed": summary.claimed,
                    "succeeded": summary.succeeded,
                    "failed": summary.failed,
                }, {}

            if segments == ["v1", "audit"] and self.command == "GET":
                self._require_operator(identity)
                query = parse_qs(urlsplit(self.path).query)
                limit = int(query.get("limit", ["100"])[0])
                if not 1 <= limit <= 500:
                    raise ValidationError("audit limit must be between 1 and 500")
                return 200, {"items": store.list_audit_events(limit)}, {}

            if segments == ["v1", "operations"] and self.command == "GET":
                self._require_operator(identity)
                query = parse_qs(urlsplit(self.path).query)
                resource_id = query.get("resource_id", [None])[0]
                limit = int(query.get("limit", ["100"])[0])
                if not 1 <= limit <= 500:
                    raise ValidationError("operation limit must be between 1 and 500")
                return 200, {"items": store.list_operations(resource_id, limit=limit)}, {}

            if len(segments) == 4 and segments[:2] == ["v1", "projects"] and segments[3] == "usage" and self.command == "GET":
                project_id = segments[2]
                control_plane.list_resources(identity=identity, project_id=project_id)
                return 200, {"items": store.usage_summary(project_id)}, {}

            raise _HTTPError(404, "NOT_FOUND", "The requested endpoint does not exist")

        def _read_json_body(self, request_id: str) -> Mapping[str, Any] | None:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return None
            try:
                length = int(raw_length)
            except ValueError as error:
                raise _HTTPError(
                    400, "INVALID_CONTENT_LENGTH", "Content-Length must be an integer"
                ) from error
            if length < 0:
                raise _HTTPError(
                    400,
                    "INVALID_CONTENT_LENGTH",
                    "Content-Length must be non-negative",
                )
            if length > settings.max_request_bytes:
                self.close_connection = True
                raise _HTTPError(
                    413,
                    "REQUEST_TOO_LARGE",
                    f"Request exceeds {settings.max_request_bytes} bytes",
                )
            if length == 0:
                return None
            content_type = self.headers.get("Content-Type", "")
            if not content_type.lower().startswith("application/json"):
                raise _HTTPError(
                    415,
                    "UNSUPPORTED_MEDIA_TYPE",
                    "Content-Type must be application/json",
                )
            try:
                document = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise _HTTPError(400, "INVALID_JSON", "Body must be valid UTF-8 JSON") from error
            if not isinstance(document, dict):
                raise _HTTPError(422, "INVALID_REQUEST", "Body must be a JSON object")
            return document

        def _idempotency_key(self) -> str:
            value = self.headers.get("Idempotency-Key", "")
            if not value:
                raise _HTTPError(
                    400,
                    "IDEMPOTENCY_KEY_REQUIRED",
                    "Idempotency-Key header is required",
                )
            return value

        def _expected_generation(self) -> int:
            raw_value = self.headers.get("If-Match", "")
            try:
                return int(raw_value)
            except ValueError as error:
                raise _HTTPError(
                    428,
                    "GENERATION_REQUIRED",
                    "If-Match must contain the expected numeric generation",
                ) from error

        @staticmethod
        def _require_body(body: Mapping[str, Any] | None) -> Mapping[str, Any]:
            if body is None:
                raise _HTTPError(400, "BODY_REQUIRED", "A JSON request body is required")
            return body

        @staticmethod
        def _require_operator(identity: Identity) -> None:
            if not ({"admin", "platform_operator"} & set(identity.roles)):
                raise AuthorizationError("operation requires admin or platform_operator role")

        @staticmethod
        def _error_document(
            status: int, code: str, message: str, request_id: str
        ) -> tuple[int, object, Mapping[str, str]]:
            return status, {
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request_id,
                }
            }, {}

        def _send_json(
            self,
            status: int,
            document: object,
            request_id: str,
            headers: Mapping[str, str],
        ) -> None:
            body = json.dumps(
                document, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Request-ID", request_id)
            self.send_header("traceparent", self._trace_context.as_traceparent())
            for key, value in headers.items():
                self.send_header(key, value)
            origin = self.headers.get("Origin", "")
            if origin in settings.allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ControlPlaneRequestHandler


class _HTTPError(RuntimeError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def build_http_server(
    *,
    settings: HTTPSettings,
    authenticator: Authenticator,
    store: SQLiteStore | None = None,
    metrics: MetricsRegistry | None = None,
) -> ThreadingHTTPServer:
    persistence = store or SQLiteStore(Path(settings.database_path))
    control_plane = ControlPlane(persistence)
    handler = create_handler(
        control_plane=control_plane,
        store=persistence,
        authenticator=authenticator,
        settings=settings,
        metrics=metrics,
    )
    return ThreadingHTTPServer((settings.host, settings.port), handler)


def _bounded_int(raw_value: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError("configuration value must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"configuration value must be between {minimum} and {maximum}")
    return value


def _normalized_route(path: str) -> str:
    """Return a bounded-cardinality route label for telemetry."""

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 3 and segments[:2] == ["v1", "projects"]:
        segments[2] = ":project_id"
    if len(segments) >= 3 and segments[:2] == ["v1", "resources"]:
        segments[2] = ":resource_id"
    return "/" + "/".join(segments) if segments else "/"
