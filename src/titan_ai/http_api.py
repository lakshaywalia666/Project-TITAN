"""Authenticated HTTP boundary for Titan's model gateway and knowledge service."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Type
from urllib.parse import urlsplit

from titan_ai.gateway import (
    AIGateway,
    BackendUnavailable,
    BudgetLedger,
    DeterministicBackend,
    GatewayError,
    ModelAccessDenied,
    RequestRateExceeded,
    RequestRateLimiter,
    Route,
    TokenBudgetExceeded,
    VLLMBackend,
)
from titan_ai.knowledge import AccessControl, KnowledgeError, KnowledgeStore
from titan_ai.models import ChatMessage, GenerateRequest
from titan_api.server import select_request_id
from titan_control.auth import AuthenticationError, Authenticator
from titan_control.domain import Identity
from titan_observability.metrics import MetricsRegistry
from titan_observability.tracing import TraceContext

LOGGER = logging.getLogger("titan.ai.api")


@dataclass(frozen=True, slots=True)
class AIHTTPSettings:
    host: str = "127.0.0.1"
    port: int = 8100
    max_request_bytes: int = 1_048_576
    knowledge_database: str = "var/titan-knowledge.db"
    allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "AIHTTPSettings":
        source = os.environ if environ is None else environ
        host = source.get("TITAN_AI_HOST", "127.0.0.1").strip()
        knowledge_database = source.get(
            "TITAN_KNOWLEDGE_DATABASE", "var/titan-knowledge.db"
        ).strip()
        if not host or not knowledge_database:
            raise ValueError("AI host and knowledge database path must not be empty")
        return cls(
            host=host,
            port=_bounded_int(source.get("TITAN_AI_PORT", "8100"), 1, 65_535),
            max_request_bytes=_bounded_int(
                source.get("TITAN_AI_MAX_REQUEST_BYTES", "1048576"),
                1_024,
                8_388_608,
            ),
            knowledge_database=knowledge_database,
            allowed_origins=tuple(
                origin.strip()
                for origin in source.get(
                    "TITAN_CORS_ALLOWED_ORIGINS",
                    "http://localhost:3000,http://127.0.0.1:3000",
                ).split(",")
                if origin.strip()
            ),
        )


@dataclass(frozen=True, slots=True)
class AIRuntime:
    gateway: AIGateway
    knowledge: KnowledgeStore


def runtime_from_environ(
    settings: AIHTTPSettings, environ: Mapping[str, str] | None = None
) -> AIRuntime:
    source = os.environ if environ is None else environ
    offline_model = source.get("TITAN_OFFLINE_MODEL", "titan-offline")
    routes: list[Route] = [
        Route(
            name="offline",
            backend=DeterministicBackend(
                name="offline",
                model=offline_model,
                response_text=(
                    "Titan is running in offline learning mode. Configure TITAN_VLLM_URL "
                    "to use a GPU-backed model."
                ),
            ),
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
            complexity="simple",
        )
    ]
    vllm_url = source.get("TITAN_VLLM_URL", "").strip()
    vllm_model = source.get("TITAN_VLLM_MODEL", "").strip()
    if vllm_url and vllm_model:
        routes.insert(
            0,
            Route(
                name="vllm",
                backend=VLLMBackend(
                    name="vllm",
                    endpoint=vllm_url,
                    model=vllm_model,
                    api_key=source.get("TITAN_VLLM_API_KEY", "not-required"),
                    timeout_seconds=float(source.get("TITAN_VLLM_TIMEOUT_SECONDS", "30")),
                ),
                input_cost_per_million=float(
                    source.get("TITAN_VLLM_INPUT_COST_PER_MILLION", "0")
                ),
                output_cost_per_million=float(
                    source.get("TITAN_VLLM_OUTPUT_COST_PER_MILLION", "0")
                ),
                complexity="complex",
            ),
        )

    allowed = _json_mapping_of_string_lists(
        source.get(
            "TITAN_AI_ALLOWED_MODELS_JSON",
            json.dumps({"local": [route.backend.model for route in routes]}),
        ),
        "TITAN_AI_ALLOWED_MODELS_JSON",
    )
    budgets_document = _json_object(
        source.get("TITAN_AI_TOKEN_BUDGETS_JSON", '{"local":100000}'),
        "TITAN_AI_TOKEN_BUDGETS_JSON",
    )
    budgets = {str(key): int(value) for key, value in budgets_document.items()}
    request_limits_document = _json_object(
        source.get("TITAN_AI_REQUEST_LIMITS_JSON", "{}"),
        "TITAN_AI_REQUEST_LIMITS_JSON",
    )
    return AIRuntime(
        gateway=AIGateway(
            routes=tuple(routes),
            allowed_models=allowed,
            budget_ledger=BudgetLedger(budgets),
            rate_limiter=RequestRateLimiter(
                {str(key): int(value) for key, value in request_limits_document.items()},
                default_limit=int(source.get("TITAN_AI_DEFAULT_REQUESTS_PER_MINUTE", "60")),
            ),
        ),
        knowledge=KnowledgeStore(Path(settings.knowledge_database)),
    )


def create_handler(
    *,
    runtime: AIRuntime,
    authenticator: Authenticator,
    settings: AIHTTPSettings,
    metrics: MetricsRegistry | None = None,
) -> Type[BaseHTTPRequestHandler]:
    registry = metrics or MetricsRegistry()

    class AIRequestHandler(BaseHTTPRequestHandler):
        server_version = "Titan-AI"
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
                "Authorization, Content-Type, X-Request-ID",
            )
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _handle(self) -> None:
            started = time.monotonic()
            request_id = select_request_id(self.headers.get("X-Request-ID"))
            self._trace_context = TraceContext.from_header(self.headers.get("traceparent"))
            path = urlsplit(self.path).path
            if path == "/metrics" and self.command == "GET":
                self._send_bytes(
                    200,
                    registry.render_prometheus(),
                    "text/plain; version=0.0.4; charset=utf-8",
                    request_id,
                )
                return
            status = 500
            try:
                if path in {"/healthz", "/readyz"} and self.command == "GET":
                    status, document = 200, {"status": "ok", "mode": "ready"}
                else:
                    identity = authenticator.authenticate(
                        self.headers.get("Authorization")
                    )
                    body = self._read_json()
                    status, document = self._dispatch(
                        identity=identity,
                        path=path,
                        body=body,
                        request_id=request_id,
                    )
            except AuthenticationError as error:
                status, document = 401, _error("UNAUTHENTICATED", str(error), request_id)
            except ModelAccessDenied as error:
                status, document = 403, _error("MODEL_ACCESS_DENIED", str(error), request_id)
            except TokenBudgetExceeded as error:
                status, document = 429, _error("TOKEN_BUDGET_EXCEEDED", str(error), request_id)
            except RequestRateExceeded as error:
                status, document = 429, _error("REQUEST_RATE_EXCEEDED", str(error), request_id)
            except BackendUnavailable as error:
                status, document = 503, _error("MODEL_BACKEND_UNAVAILABLE", str(error), request_id)
            except (_RequestError, GatewayError, KnowledgeError, ValueError, TypeError) as error:
                status = error.status if isinstance(error, _RequestError) else 422
                code = error.code if isinstance(error, _RequestError) else "INVALID_REQUEST"
                status, document = status, _error(code, str(error), request_id)
            except Exception:
                LOGGER.exception("unhandled AI API error")
                status, document = 500, _error(
                    "INTERNAL_ERROR", "The AI service could not complete the request", request_id
                )
            self._send_json(status, document, request_id)
            registry.observe_http(
                service="ai-api",
                method=self.command,
                route=path,
                status=status,
                duration_seconds=time.monotonic() - started,
            )

        def _dispatch(
            self,
            *,
            identity: Identity,
            path: str,
            body: Mapping[str, Any] | None,
            request_id: str,
        ) -> tuple[int, object]:
            document = _require_body(body)
            if path == "/v1/chat/completions" and self.command == "POST":
                project_id = str(document.get("project_id", "local"))
                _authorize_project(identity, project_id)
                raw_messages = document.get("messages")
                if not isinstance(raw_messages, list):
                    raise _RequestError(422, "INVALID_MESSAGES", "messages must be an array")
                messages = tuple(
                    ChatMessage(role=str(item["role"]), content=str(item["content"]))
                    for item in raw_messages
                    if isinstance(item, dict)
                )
                if len(messages) != len(raw_messages):
                    raise _RequestError(422, "INVALID_MESSAGES", "every message must be an object")
                result = runtime.gateway.generate(
                    project_id=project_id,
                    request=GenerateRequest(
                        messages=messages,
                        max_output_tokens=int(document.get("max_tokens", 256)),
                        temperature=float(document.get("temperature", 0.0)),
                        requested_model=(
                            str(document["model"]) if document.get("model") else None
                        ),
                    ),
                    correlation_id=request_id,
                )
                return 200, {
                    "id": f"chatcmpl-{request_id}",
                    "object": "chat.completion",
                    "model": result.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": result.text},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": result.usage.input_tokens,
                        "completion_tokens": result.usage.output_tokens,
                        "total_tokens": result.usage.total_tokens,
                    },
                    "titan": result.to_dict(),
                }

            if path == "/v1/knowledge/documents" and self.command == "POST":
                project_id = str(document.get("project_id", "local"))
                _authorize_project(identity, project_id)
                acl_document = document.get("acl", {})
                if not isinstance(acl_document, dict):
                    raise _RequestError(422, "INVALID_ACL", "acl must be an object")
                result = runtime.knowledge.upsert_document(
                    knowledge_base_id=str(document.get("knowledge_base_id", "")),
                    source_id=str(document.get("source_id", "")),
                    content=str(document.get("content", "")),
                    acl=AccessControl(
                        public=bool(acl_document.get("public", False)),
                        subjects=tuple(str(value) for value in acl_document.get("subjects", [])),
                        projects=tuple(str(value) for value in acl_document.get("projects", [])),
                    ),
                    metadata=(
                        document.get("metadata")
                        if isinstance(document.get("metadata", {}), dict)
                        else {}
                    ),
                )
                return 201, result

            if path == "/v1/knowledge/search" and self.command == "POST":
                project_id = str(document.get("project_id", "local"))
                _authorize_project(identity, project_id)
                chunks = runtime.knowledge.retrieve(
                    knowledge_base_id=str(document.get("knowledge_base_id", "")),
                    query=str(document.get("query", "")),
                    subject=identity.subject,
                    project_id=project_id,
                    limit=int(document.get("limit", 5)),
                )
                return 200, {
                    "items": [
                        {
                            "content": chunk.content,
                            "score": chunk.score,
                            "metadata": dict(chunk.metadata),
                            "citation": chunk.citation(),
                        }
                        for chunk in chunks
                    ]
                }

            if path == "/v1/budgets" and self.command == "POST":
                project_id = str(document.get("project_id", "local"))
                _authorize_project(identity, project_id)
                return 200, runtime.gateway.budget_ledger.usage(project_id)

            raise _RequestError(404, "NOT_FOUND", "The requested endpoint does not exist")

        def _read_json(self) -> Mapping[str, Any] | None:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return None
            try:
                length = int(raw_length)
            except ValueError as error:
                raise _RequestError(400, "INVALID_CONTENT_LENGTH", "invalid Content-Length") from error
            if length < 0 or length > settings.max_request_bytes:
                raise _RequestError(413, "REQUEST_TOO_LARGE", "request body is too large")
            if length == 0:
                return None
            if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                raise _RequestError(415, "UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json")
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise _RequestError(400, "INVALID_JSON", "body must be valid UTF-8 JSON") from error
            if not isinstance(value, dict):
                raise _RequestError(422, "INVALID_REQUEST", "body must be a JSON object")
            return value

        def _send_json(self, status: int, document: object, request_id: str) -> None:
            self._send_bytes(
                status,
                json.dumps(document, separators=(",", ":")).encode("utf-8"),
                "application/json; charset=utf-8",
                request_id,
            )

        def _send_bytes(
            self, status: int, body: bytes, content_type: str, request_id: str
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            self.send_header("X-Request-ID", request_id)
            self.send_header("traceparent", self._trace_context.as_traceparent())
            origin = self.headers.get("Origin", "")
            if origin in settings.allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return AIRequestHandler


def build_http_server(
    *,
    settings: AIHTTPSettings,
    authenticator: Authenticator,
    runtime: AIRuntime | None = None,
    metrics: MetricsRegistry | None = None,
) -> ThreadingHTTPServer:
    selected_runtime = runtime or runtime_from_environ(settings)
    return ThreadingHTTPServer(
        (settings.host, settings.port),
        create_handler(
            runtime=selected_runtime,
            authenticator=authenticator,
            settings=settings,
            metrics=metrics,
        ),
    )


class _RequestError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _authorize_project(identity: Identity, project_id: str) -> None:
    if "admin" not in identity.roles and project_id not in identity.project_ids:
        raise ModelAccessDenied(f"identity cannot access project {project_id}")


def _require_body(body: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if body is None:
        raise _RequestError(400, "BODY_REQUIRED", "a JSON request body is required")
    return body


def _error(code: str, message: str, request_id: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def _json_object(raw_value: str, name: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} must contain valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value


def _json_mapping_of_string_lists(raw_value: str, name: str) -> dict[str, tuple[str, ...]]:
    value = _json_object(raw_value, name)
    result: dict[str, tuple[str, ...]] = {}
    for key, items in value.items():
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ValueError(f"{name} values must be arrays of strings")
        result[str(key)] = tuple(items)
    return result


def _bounded_int(raw_value: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError("configuration value must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"configuration value must be between {minimum} and {maximum}")
    return value
