"""Protocol-independent request routing and application behavior."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Mapping
from urllib.parse import urlsplit

from titan_api import __version__
from titan_api.models import TaskStore


@dataclass(frozen=True, slots=True)
class Request:
    method: str
    target: str
    headers: Mapping[str, str]
    body: bytes
    request_id: str


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    payload: Mapping[str, object]
    headers: Mapping[str, str] = field(default_factory=dict)

    def body(self) -> bytes:
        return json.dumps(
            self.payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")


class TitanApplication:
    def __init__(self, task_store: TaskStore | None = None) -> None:
        self.task_store = task_store or TaskStore()

    def handle(self, request: Request) -> Response:
        path = urlsplit(request.target).path

        if path == "/healthz":
            if request.method != "GET":
                return self.error(
                    status=405,
                    code="METHOD_NOT_ALLOWED",
                    message="Only GET is allowed for this resource",
                    request_id=request.request_id,
                    headers={"Allow": "GET"},
                )
            return self.success(
                status=200,
                payload={"status": "ok"},
                request_id=request.request_id,
            )

        if path == "/version":
            if request.method != "GET":
                return self.error(
                    status=405,
                    code="METHOD_NOT_ALLOWED",
                    message="Only GET is allowed for this resource",
                    request_id=request.request_id,
                    headers={"Allow": "GET"},
                )
            return self.success(
                status=200,
                payload={"name": "titan-reference-api", "version": __version__},
                request_id=request.request_id,
            )

        if path == "/api/tasks":
            if request.method == "GET":
                tasks = [task.to_dict() for task in self.task_store.list_all()]
                return self.success(
                    status=200,
                    payload={"items": tasks, "count": len(tasks)},
                    request_id=request.request_id,
                )
            if request.method == "POST":
                return self._create_task(request)
            return self.error(
                status=405,
                code="METHOD_NOT_ALLOWED",
                message="Only GET and POST are allowed for this resource",
                request_id=request.request_id,
                headers={"Allow": "GET, POST"},
            )

        return self.error(
            status=404,
            code="RESOURCE_NOT_FOUND",
            message="The requested resource does not exist",
            request_id=request.request_id,
        )

    def _create_task(self, request: Request) -> Response:
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("application/json"):
            return self.error(
                status=415,
                code="UNSUPPORTED_MEDIA_TYPE",
                message="Content-Type must be application/json",
                request_id=request.request_id,
            )

        try:
            decoded_body = request.body.decode("utf-8")
            document = json.loads(decoded_body)
        except (UnicodeDecodeError, JSONDecodeError):
            return self.error(
                status=400,
                code="INVALID_JSON",
                message="Request body must contain valid UTF-8 JSON",
                request_id=request.request_id,
            )

        if not isinstance(document, dict):
            return self.error(
                status=422,
                code="INVALID_REQUEST",
                message="Request body must be a JSON object",
                request_id=request.request_id,
            )

        allowed_fields = {"title", "description"}
        unknown_fields = sorted(set(document) - allowed_fields)
        if unknown_fields:
            return self.error(
                status=422,
                code="UNKNOWN_FIELDS",
                message=f"Unknown fields: {', '.join(unknown_fields)}",
                request_id=request.request_id,
            )

        title = document.get("title")
        if not isinstance(title, str) or not title.strip():
            return self.error(
                status=422,
                code="INVALID_TITLE",
                message="title must be a non-empty string",
                request_id=request.request_id,
            )
        title = title.strip()
        if len(title) > 200:
            return self.error(
                status=422,
                code="INVALID_TITLE",
                message="title must contain at most 200 characters",
                request_id=request.request_id,
            )

        description = document.get("description", "")
        if not isinstance(description, str):
            return self.error(
                status=422,
                code="INVALID_DESCRIPTION",
                message="description must be a string",
                request_id=request.request_id,
            )
        if len(description) > 2_000:
            return self.error(
                status=422,
                code="INVALID_DESCRIPTION",
                message="description must contain at most 2000 characters",
                request_id=request.request_id,
            )

        task = self.task_store.create(title=title, description=description)
        return self.success(
            status=201,
            payload={"task": task.to_dict()},
            request_id=request.request_id,
            headers={"Location": f"/api/tasks/{task.id}"},
        )

    @staticmethod
    def success(
        *,
        status: int,
        payload: Mapping[str, object],
        request_id: str,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        response_headers = {"X-Request-ID": request_id}
        response_headers.update(headers or {})
        return Response(status=status, payload=payload, headers=response_headers)

    @staticmethod
    def error(
        *,
        status: int,
        code: str,
        message: str,
        request_id: str,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        response_headers = {"X-Request-ID": request_id}
        response_headers.update(headers or {})
        return Response(
            status=status,
            payload={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request_id,
                }
            },
            headers=response_headers,
        )

