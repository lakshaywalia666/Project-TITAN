"""HTTP API for the Titan Shop reference workload."""

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

from titan_api.server import select_request_id
from titan_control.auth import AuthenticationError, Authenticator
from titan_control.domain import Identity
from titan_observability.metrics import MetricsRegistry
from titan_observability.tracing import TraceContext
from titan_workloads.shop import OrderConflict, ProductNotFound, ShopError, ShopStore

LOGGER = logging.getLogger("titan.shop.api")


@dataclass(frozen=True, slots=True)
class ShopSettings:
    host: str = "127.0.0.1"
    port: int = 8200
    database_path: str = "var/titan-shop.db"
    max_request_bytes: int = 65_536
    allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "ShopSettings":
        source = os.environ if environ is None else environ
        host = source.get("TITAN_SHOP_HOST", "127.0.0.1").strip()
        database_path = source.get("TITAN_SHOP_DATABASE", "var/titan-shop.db").strip()
        if not host or not database_path:
            raise ValueError("shop host and database path must not be empty")
        return cls(
            host=host,
            port=_bounded_int(source.get("TITAN_SHOP_PORT", "8200"), 1, 65_535),
            database_path=database_path,
            max_request_bytes=_bounded_int(
                source.get("TITAN_SHOP_MAX_REQUEST_BYTES", "65536"),
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
    store: ShopStore,
    authenticator: Authenticator,
    settings: ShopSettings,
    metrics: MetricsRegistry | None = None,
) -> Type[BaseHTTPRequestHandler]:
    registry = metrics or MetricsRegistry()

    class ShopHandler(BaseHTTPRequestHandler):
        server_version = "Titan-Shop"
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
            self._trace_context = TraceContext.from_header(self.headers.get("traceparent"))
            path = urlsplit(self.path).path
            status = 500
            try:
                if path == "/healthz" and self.command == "GET":
                    status, document = 200, {"status": "ok"}
                elif path == "/metrics" and self.command == "GET":
                    body = registry.render_prometheus()
                    self._send(status=200, body=body, content_type="text/plain; version=0.0.4", request_id=request_id)
                    return
                elif path == "/v1/catalog" and self.command == "GET":
                    status, document = 200, {"items": store.list_products()}
                else:
                    identity = authenticator.authenticate(self.headers.get("Authorization"))
                    if path == "/v1/orders" and self.command == "POST":
                        body = self._read_json()
                        project_id = str(body.get("project_id", "local"))
                        _authorize_project(identity, project_id)
                        raw_items = body.get("items")
                        if not isinstance(raw_items, list) or not all(isinstance(item, dict) for item in raw_items):
                            raise ShopError("items must be an array of objects")
                        key = self.headers.get("Idempotency-Key", "")
                        document = store.create_order(
                            customer_id=identity.subject,
                            project_id=project_id,
                            items=tuple(raw_items),
                            idempotency_key=key,
                            account_age_days=int(body.get("account_age_days", 30)),
                            country_mismatch=bool(body.get("country_mismatch", False)),
                        )
                        status = 201
                    elif path.startswith("/v1/orders/") and self.command == "GET":
                        order = store.get_order(path.removeprefix("/v1/orders/"))
                        _authorize_project(identity, str(order["project_id"]))
                        if "admin" not in identity.roles and identity.subject != order["customer_id"]:
                            raise ProductNotFound("order not found")
                        status, document = 200, order
                    else:
                        status, document = 404, _error("NOT_FOUND", "endpoint does not exist", request_id)
            except AuthenticationError as exc:
                status, document = 401, _error("UNAUTHENTICATED", str(exc), request_id)
            except ProductNotFound as exc:
                status, document = 404, _error("NOT_FOUND", str(exc), request_id)
            except OrderConflict as exc:
                status, document = 409, _error("IDEMPOTENCY_CONFLICT", str(exc), request_id)
            except (ShopError, ValueError, TypeError, json.JSONDecodeError) as exc:
                status, document = 422, _error("INVALID_REQUEST", str(exc), request_id)
            except Exception:
                LOGGER.exception("unhandled Titan Shop request error")
                status, document = 500, _error(
                    "INTERNAL_ERROR", "The shop could not complete the request", request_id
                )
            self._send(
                status=status,
                body=json.dumps(document, separators=(",", ":")).encode("utf-8"),
                content_type="application/json; charset=utf-8",
                request_id=request_id,
            )
            registry.observe_http(
                service="titan-shop",
                method=self.command,
                route="/v1/orders/:id" if path.startswith("/v1/orders/") else path,
                status=status,
                duration_seconds=time.monotonic() - started,
            )

        def _read_json(self) -> Mapping[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > settings.max_request_bytes:
                raise ShopError("request body is absent or too large")
            if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                raise ShopError("Content-Type must be application/json")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ShopError("request body must be an object")
            return value

        def _send(self, *, status: int, body: bytes, content_type: str, request_id: str) -> None:
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

    return ShopHandler


def build_http_server(
    *, settings: ShopSettings, authenticator: Authenticator, store: ShopStore | None = None
) -> ThreadingHTTPServer:
    selected_store = store or ShopStore(Path(settings.database_path))
    return ThreadingHTTPServer(
        (settings.host, settings.port),
        create_handler(store=selected_store, authenticator=authenticator, settings=settings),
    )


def _authorize_project(identity: Identity, project_id: str) -> None:
    if "admin" not in identity.roles and project_id not in identity.project_ids:
        raise ProductNotFound("project not found")


def _error(code: str, message: str, request_id: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def _bounded_int(raw_value: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError("configuration value must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"configuration value must be between {minimum} and {maximum}")
    return value
