"""Stable AI-domain request and response contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class GenerateRequest:
    messages: tuple[ChatMessage, ...]
    max_output_tokens: int = 256
    temperature: float = 0.0
    requested_model: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class GenerateResponse:
    text: str
    model: str
    backend: str
    usage: TokenUsage
    estimated_cost: float
    correlation_id: str
    fallback_used: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "backend": self.backend,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "total_tokens": self.usage.total_tokens,
            },
            "estimated_cost": self.estimated_cost,
            "correlation_id": self.correlation_id,
            "fallback_used": self.fallback_used,
        }


@dataclass(frozen=True, slots=True)
class BackendResponse:
    text: str
    model: str
    usage: TokenUsage

