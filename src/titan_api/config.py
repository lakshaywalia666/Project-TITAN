"""Environment-driven configuration with explicit validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_MAX_REQUEST_BYTES = 16_384


class ConfigurationError(ValueError):
    """Raised when Titan cannot safely start with the supplied configuration."""


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        host = source.get("TITAN_HOST", DEFAULT_HOST).strip()

        if not host:
            raise ConfigurationError("TITAN_HOST must not be empty")

        port = _bounded_integer(
            name="TITAN_PORT",
            raw_value=source.get("TITAN_PORT", str(DEFAULT_PORT)),
            minimum=1,
            maximum=65_535,
        )
        max_request_bytes = _bounded_integer(
            name="TITAN_MAX_REQUEST_BYTES",
            raw_value=source.get(
                "TITAN_MAX_REQUEST_BYTES", str(DEFAULT_MAX_REQUEST_BYTES)
            ),
            minimum=1_024,
            maximum=1_048_576,
        )

        return cls(
            host=host,
            port=port,
            max_request_bytes=max_request_bytes,
        )


def _bounded_integer(
    *, name: str, raw_value: str, minimum: int, maximum: int
) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error

    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{name} must be between {minimum} and {maximum}")

    return value
