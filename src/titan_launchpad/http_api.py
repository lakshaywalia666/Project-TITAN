"""Authenticated HTTP boundary for Cloud Launchpad planning."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Type
from urllib.parse import parse_qs, urlsplit

from titan_api.server import select_request_id
from titan_control.auth import AuthenticationError, Authenticator
from titan_control.domain import Identity
from titan_launchpad.catalog import catalog_document
from titan_launchpad.engine import RecommendationEngine
from titan_launchpad.models import (
    IdempotencyConflict,
    LaunchpadError,
    NotFoundError,
    WorkloadSpec,
    example_workload,
)
from titan_launchpad.store import LaunchpadStore
from titan_observability.metrics import MetricsRegistry
from titan_observability.tracing import TraceContext

LOGGER = logging.getLogger("titan.launchpad.api")
ID_PATTERN = re.compile(r"^(asm|pln)_[0-9a-f]{32}$")
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True, slots=True)
class LaunchpadSettings:
    host: str = "127.0.0.1"
    port: int = 8300
    database_path: str = "var/titan-launchpad.db"
    max_request_bytes: int = 262_144
    allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "LaunchpadSettings":
        source = os.environ if environ is None else environ
        host = source.get("TITAN_LAUNCHPAD_HOST", "127.0.0.1").strip()
        database_path = source.get(
            "TITAN_LAUNCHPAD_DATABASE", "var/titan-launchpad.db"
        ).strip()
        if not host or not database_path:
            raise ValueError("Launchpad host and database path must not be empty")
        return cls(
            host=host,
            port=_bounded_int(source.get("TITAN_LAUNCHPAD_PORT", "8300"), 1, 65_535),
            database_path=database_path,
            max_request_bytes=_bounded_int(
                source.get("TITAN_LAUNCHPAD_MAX_REQUEST_BYTES", "262144"),
                1_024,
                1_048_576,
            ),
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
    store: LaunchpadStore,
    authenticator: Authenticator,
    settings: LaunchpadSettings,
    engine: RecommendationEngine | None = None,
    metrics: MetricsRegistry | None = None,
) -> Type[BaseHTTPRequestHandler]:
    selected_engine = engine or RecommendationEngine()
    registry = metrics or MetricsRegistry()

    class LaunchpadHandler(BaseHTTPRequestHandler):
        server_version = "Titan-Launchpad"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Authorization, Content-Type, Idempotency-Key, X-Request-ID, traceparent",
            )
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _handle(self) -> None:
            started = time.monotonic()
            request_id = select_request_id(self.headers.get("X-Request-ID"))
            self._trace_context = TraceContext.from_header(
                self.headers.get("traceparent")
            )
            parsed = urlsplit(self.path)
            path = parsed.path
            status = 500
            try:
                if path == "/healthz" and self.command == "GET":
                    status, document = 200, {
                        "status": "ok",
                        "mode": "dry-run-planning",
                    }
                elif path == "/metrics" and self.command == "GET":
                    self._send_bytes(
                        200,
                        registry.render_prometheus(),
                        "text/plain; version=0.0.4; charset=utf-8",
                        request_id,
                    )
                    return
                elif path == "/v1/catalog" and self.command == "GET":
                    status, document = 200, catalog_document()
                elif path == "/v1/example" and self.command == "GET":
                    status, document = 200, example_workload()
                else:
                    identity = authenticator.authenticate(
                        self.headers.get("Authorization")
                    )
                    status, document = self._dispatch(
                        path, parse_qs(parsed.query), identity, request_id
                    )
            except AuthenticationError as error:
                status, document = 401, _error(
                    "UNAUTHENTICATED", str(error), request_id
                )
            except PermissionError as error:
                status, document = 403, _error("FORBIDDEN", str(error), request_id)
            except NotFoundError as error:
                status, document = 404, _error("NOT_FOUND", str(error), request_id)
            except IdempotencyConflict as error:
                status, document = 409, _error(
                    "IDEMPOTENCY_CONFLICT", str(error), request_id
                )
            except (LaunchpadError, ValueError, TypeError, json.JSONDecodeError) as error:
                status, document = 422, _error(
                    "INVALID_REQUEST", str(error), request_id
                )
            except Exception:
                LOGGER.exception("unhandled Launchpad request error")
                status, document = 500, _error(
                    "INTERNAL_ERROR",
                    "Launchpad could not complete the request",
                    request_id,
                )
            self._send_json(status, document, request_id)
            registry.observe_http(
                service="titan-launchpad",
                method=self.command,
                route=_normalized_route(path),
                status=status,
                duration_seconds=time.monotonic() - started,
            )

        def _dispatch(
            self,
            path: str,
            query: Mapping[str, list[str]],
            identity: Identity,
            request_id: str,
        ) -> tuple[int, dict[str, Any]]:
            is_admin = bool({"admin", "platform_operator"} & set(identity.roles))
            if path == "/v1/assessments" and self.command == "POST":
                body = self._read_json()
                key = self._idempotency_key()
                assessment, replayed = store.create_assessment(
                    spec=WorkloadSpec.from_document(body),
                    actor=identity.subject,
                    idempotency_key=key,
                    engine=selected_engine,
                )
                assessment["idempotently_replayed"] = replayed
                return (200 if replayed else 201), assessment
            if path == "/v1/assessments" and self.command == "GET":
                limit = _query_limit(query)
                return 200, {
                    "items": store.list_assessments(
                        actor=None if is_admin else identity.subject, limit=limit
                    )
                }
            if path.startswith("/v1/assessments/"):
                suffix = path.removeprefix("/v1/assessments/")
                if suffix.endswith("/plans") and self.command == "POST":
                    assessment_id = suffix.removesuffix("/plans")
                    _validate_id(assessment_id, "asm")
                    assessment = store.get_assessment(assessment_id)
                    _authorize_owner(identity, assessment)
                    body = self._read_json()
                    if set(body) != {"provider"}:
                        raise LaunchpadError("plan request must contain only provider")
                    provider = body.get("provider")
                    if not isinstance(provider, str):
                        raise LaunchpadError("provider must be a string")
                    plan, replayed = store.create_plan(
                        assessment_id=assessment_id,
                        provider=provider,
                        actor=identity.subject,
                        idempotency_key=self._idempotency_key(),
                        engine=selected_engine,
                    )
                    plan["idempotently_replayed"] = replayed
                    return (200 if replayed else 201), plan
                if self.command == "GET":
                    _validate_id(suffix, "asm")
                    assessment = store.get_assessment(suffix)
                    _authorize_owner(identity, assessment)
                    return 200, assessment
            if path.startswith("/v1/plans/") and self.command == "GET":
                plan_id = path.removeprefix("/v1/plans/")
                _validate_id(plan_id, "pln")
                plan = store.get_plan(plan_id)
                _authorize_owner(identity, plan)
                return 200, plan
            return 404, _error("NOT_FOUND", "endpoint does not exist", request_id)

        def _idempotency_key(self) -> str:
            key = self.headers.get("Idempotency-Key", "")
            if not KEY_PATTERN.fullmatch(key):
                raise LaunchpadError(
                    "Idempotency-Key must contain 1-128 safe characters"
                )
            return key

        def _read_json(self) -> Mapping[str, Any]:
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError as error:
                raise LaunchpadError("Content-Length must be an integer") from error
            if length <= 0 or length > settings.max_request_bytes:
                raise LaunchpadError("request body is absent or too large")
            if not self.headers.get("Content-Type", "").lower().startswith(
                "application/json"
            ):
                raise LaunchpadError("Content-Type must be application/json")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise LaunchpadError("request body must be an object")
            return value

        def _send_json(
            self, status: int, document: Mapping[str, Any], request_id: str
        ) -> None:
            body = json.dumps(document, separators=(",", ":")).encode("utf-8")
            self._send_bytes(
                status,
                body,
                "application/json; charset=utf-8",
                request_id,
            )

        def _send_bytes(
            self,
            status: int,
            body: bytes,
            content_type: str,
            request_id: str,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Request-ID", request_id)
            self.send_header("traceparent", self._trace_context.as_traceparent())
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            origin = self.headers.get("Origin", "")
            if origin in settings.allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return LaunchpadHandler


def build_http_server(
    *,
    settings: LaunchpadSettings,
    authenticator: Authenticator,
    store: LaunchpadStore | None = None,
) -> ThreadingHTTPServer:
    selected_store = store or LaunchpadStore(Path(settings.database_path))
    return ThreadingHTTPServer(
        (settings.host, settings.port),
        create_handler(
            store=selected_store,
            authenticator=authenticator,
            settings=settings,
        ),
    )


def _authorize_owner(identity: Identity, document: Mapping[str, Any]) -> None:
    if (
        document.get("actor") != identity.subject
        and not {"admin", "platform_operator"} & set(identity.roles)
    ):
        raise PermissionError("assessment or plan belongs to another identity")


def _validate_id(value: str, prefix: str) -> None:
    if not ID_PATTERN.fullmatch(value) or not value.startswith(f"{prefix}_"):
        raise LaunchpadError(f"invalid {prefix} identifier")


def _query_limit(query: Mapping[str, list[str]]) -> int:
    raw = query.get("limit", ["50"])[0]
    return _bounded_int(raw, 1, 100)


def _bounded_int(raw_value: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError("configuration value must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"configuration value must be between {minimum} and {maximum}")
    return value


def _normalized_route(path: str) -> str:
    if path.startswith("/v1/assessments/") and path.endswith("/plans"):
        return "/v1/assessments/:id/plans"
    if path.startswith("/v1/assessments/"):
        return "/v1/assessments/:id"
    if path.startswith("/v1/plans/"):
        return "/v1/plans/:id"
    return path


def _error(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "request_id": request_id}}

