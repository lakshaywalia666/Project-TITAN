"""W3C Trace Context parsing and structured span events without runtime dependencies."""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Mapping

TRACEPARENT = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    span_id: str
    flags: str = "01"

    @classmethod
    def from_header(cls, value: str | None) -> "TraceContext":
        if value:
            match = TRACEPARENT.fullmatch(value.strip().lower())
            if match and match.group(1) != "0" * 32 and match.group(2) != "0" * 16:
                return cls(match.group(1), _nonzero_hex(8), match.group(3))
        return cls(_nonzero_hex(16), _nonzero_hex(8))

    def child(self) -> "TraceContext":
        return TraceContext(self.trace_id, _nonzero_hex(8), self.flags)

    def as_traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.flags}"


class StructuredSpan:
    def __init__(
        self,
        *,
        logger: logging.Logger,
        context: TraceContext,
        name: str,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        self.logger = logger
        self.context = context
        self.name = name
        self.attributes = dict(attributes or {})
        self.started = 0.0

    def __enter__(self) -> "StructuredSpan":
        self.started = time.monotonic()
        return self

    def __exit__(self, error_type: object, error: object, traceback: object) -> None:
        self.logger.info(
            json.dumps(
                {
                    "event": "span",
                    "name": self.name,
                    "trace_id": self.context.trace_id,
                    "span_id": self.context.span_id,
                    "status": "error" if error is not None else "ok",
                    "duration_ms": round((time.monotonic() - self.started) * 1000, 3),
                    "attributes": self.attributes,
                },
                separators=(",", ":"),
            )
        )


def _nonzero_hex(byte_count: int) -> str:
    value = "0" * (byte_count * 2)
    while set(value) == {"0"}:
        value = secrets.token_hex(byte_count)
    return value

