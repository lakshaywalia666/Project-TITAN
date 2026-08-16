"""Standard-library HTTP adapter for the Titan application."""

from __future__ import annotations

import json
import logging
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Type
from uuid import uuid4

from titan_api import __version__
from titan_api.app import Request, Response, TitanApplication
from titan_api.config import Settings
from titan_ops.lifecycle import serve_with_signals

LOGGER = logging.getLogger("titan.api")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
BODY_METHODS = {"POST", "PUT", "PATCH"}


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def select_request_id(candidate: str | None) -> str:
    if candidate and SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid4().hex


def create_handler(
    application: TitanApplication, settings: Settings
) -> Type[BaseHTTPRequestHandler]:
    class TitanRequestHandler(BaseHTTPRequestHandler):
        server_version = "Titan"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            self._handle_request()

        def do_POST(self) -> None:  # noqa: N802
            self._handle_request()

        def do_PUT(self) -> None:  # noqa: N802
            self._handle_request()

        def do_PATCH(self) -> None:  # noqa: N802
            self._handle_request()

        def do_DELETE(self) -> None:  # noqa: N802
            self._handle_request()

        def _handle_request(self) -> None:
            started = time.monotonic()
            request_id = select_request_id(self.headers.get("X-Request-ID"))
            status = 500

            try:
                body, read_error = self._read_body(request_id)
                if read_error is not None:
                    response = read_error
                else:
                    response = application.handle(
                        Request(
                            method=self.command,
                            target=self.path,
                            headers={
                                key.lower(): value for key, value in self.headers.items()
                            },
                            body=body,
                            request_id=request_id,
                        )
                    )
                status = response.status
                self._send_json(response)
            except (BrokenPipeError, ConnectionResetError):
                status = 499
            except Exception:
                LOGGER.exception(
                    json.dumps(
                        {
                            "event": "unhandled_request_error",
                            "request_id": request_id,
                        },
                        separators=(",", ":"),
                    )
                )
                response = application.error(
                    status=500,
                    code="INTERNAL_ERROR",
                    message="The server could not complete the request",
                    request_id=request_id,
                )
                status = response.status
                self._send_json(response)
            finally:
                duration_ms = round((time.monotonic() - started) * 1_000, 3)
                LOGGER.info(
                    json.dumps(
                        {
                            "event": "http_request",
                            "request_id": request_id,
                            "method": self.command,
                            "path": self.path,
                            "status": status,
                            "duration_ms": duration_ms,
                        },
                        separators=(",", ":"),
                    )
                )

        def _read_body(self, request_id: str) -> tuple[bytes, Response | None]:
            if self.headers.get("Transfer-Encoding"):
                self.close_connection = True
                return b"", application.error(
                    status=400,
                    code="UNSUPPORTED_TRANSFER_ENCODING",
                    message="Chunked request bodies are not supported",
                    request_id=request_id,
                )

            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return b"", None

            try:
                content_length = int(raw_length)
            except ValueError:
                self.close_connection = True
                return b"", application.error(
                    status=400,
                    code="INVALID_CONTENT_LENGTH",
                    message="Content-Length must be a non-negative integer",
                    request_id=request_id,
                )

            if content_length < 0:
                self.close_connection = True
                return b"", application.error(
                    status=400,
                    code="INVALID_CONTENT_LENGTH",
                    message="Content-Length must be a non-negative integer",
                    request_id=request_id,
                )

            if content_length > settings.max_request_bytes:
                self.close_connection = True
                return b"", application.error(
                    status=413,
                    code="REQUEST_TOO_LARGE",
                    message=(
                        "Request body exceeds the configured maximum of "
                        f"{settings.max_request_bytes} bytes"
                    ),
                    request_id=request_id,
                )

            if self.command not in BODY_METHODS and content_length:
                self.close_connection = True
                return b"", application.error(
                    status=400,
                    code="UNEXPECTED_REQUEST_BODY",
                    message=f"{self.command} requests must not contain a body",
                    request_id=request_id,
                )

            return self.rfile.read(content_length), None

        def _send_json(self, response: Response) -> None:
            body = response.body()
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            # Access logging is emitted once in _handle_request as structured JSON.
            return

    return TitanRequestHandler


def build_server(
    settings: Settings, application: TitanApplication | None = None
) -> ThreadingHTTPServer:
    app = application or TitanApplication()
    handler = create_handler(app, settings)
    return ThreadingHTTPServer((settings.host, settings.port), handler)


def run(settings: Settings) -> None:
    server = build_server(settings)
    actual_host, actual_port = server.server_address[:2]
    LOGGER.info(
        json.dumps(
            {
                "event": "server_started",
                "host": actual_host,
                "port": actual_port,
                "version": __version__,
            },
            separators=(",", ":"),
        )
    )
    serve_with_signals(server, service="titan.api")
