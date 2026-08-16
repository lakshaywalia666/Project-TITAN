"""Validated request models for the bounded Cloud Launchpad golden path."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit


class LaunchpadError(ValueError):
    """Base error for invalid or unsupported Launchpad requests."""


class NotFoundError(LaunchpadError):
    pass


class IdempotencyConflict(LaunchpadError):
    pass


NAME_PATTERN = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
IMAGE_PATTERN = re.compile(
    r"^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$"
)
HEALTH_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{0,255}$")


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    name: str
    repository_url: str
    image: str
    container_port: int
    health_path: str
    environment: str
    geography: str
    monthly_requests: int
    cpu_millicores: int
    memory_mb: int
    min_instances: int
    max_instances: int
    scale_to_zero: bool
    public_access: bool
    database: str
    object_storage: bool
    background_worker: bool
    availability: str
    data_classification: str
    budget_usd_month: float

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "WorkloadSpec":
        allowed = {
            "name",
            "repository_url",
            "image",
            "container_port",
            "health_path",
            "environment",
            "geography",
            "monthly_requests",
            "cpu_millicores",
            "memory_mb",
            "min_instances",
            "max_instances",
            "scale_to_zero",
            "public_access",
            "database",
            "object_storage",
            "background_worker",
            "availability",
            "data_classification",
            "budget_usd_month",
        }
        unknown = sorted(set(document) - allowed)
        if unknown:
            raise LaunchpadError(f"unknown workload fields: {', '.join(unknown)}")

        name = _required_string(document, "name", maximum=63)
        if not NAME_PATTERN.fullmatch(name):
            raise LaunchpadError("name must be a lowercase DNS label")

        repository_url = _required_string(document, "repository_url", maximum=300)
        _validate_repository_url(repository_url)

        image = _optional_string(document, "image", maximum=500)
        if image and not IMAGE_PATTERN.fullmatch(image):
            raise LaunchpadError(
                "image must be a public lowercase GHCR image pinned with @sha256"
            )

        health_path = _optional_string(
            document, "health_path", default="/healthz", maximum=256
        )
        if not HEALTH_PATH_PATTERN.fullmatch(health_path) or ".." in health_path:
            raise LaunchpadError("health_path must be one safe absolute HTTP path")

        environment = _choice(
            document, "environment", {"development", "staging", "production"}, "development"
        )
        geography = _choice(
            document, "geography", {"india", "us", "europe", "global"}, "india"
        )
        database = _choice(document, "database", {"none", "postgresql"}, "none")
        availability = _choice(
            document, "availability", {"standard", "high"}, "standard"
        )
        data_classification = _choice(
            document,
            "data_classification",
            {"public", "internal", "confidential", "restricted"},
            "internal",
        )

        min_instances = _bounded_int(document, "min_instances", 0, 20, 0)
        max_instances = _bounded_int(document, "max_instances", 1, 100, 3)
        if max_instances < min_instances:
            raise LaunchpadError("max_instances must be greater than or equal to min_instances")

        budget = _bounded_number(document, "budget_usd_month", 0, 1_000_000, 0)
        return cls(
            name=name,
            repository_url=repository_url,
            image=image,
            container_port=_bounded_int(document, "container_port", 1, 65_535, 8080),
            health_path=health_path,
            environment=environment,
            geography=geography,
            monthly_requests=_bounded_int(
                document, "monthly_requests", 0, 2_000_000_000, 10_000
            ),
            cpu_millicores=_bounded_int(document, "cpu_millicores", 100, 8_000, 500),
            memory_mb=_bounded_int(document, "memory_mb", 128, 32_768, 512),
            min_instances=min_instances,
            max_instances=max_instances,
            scale_to_zero=_boolean(document, "scale_to_zero", True),
            public_access=_boolean(document, "public_access", True),
            database=database,
            object_storage=_boolean(document, "object_storage", False),
            background_worker=_boolean(document, "background_worker", False),
            availability=availability,
            data_classification=data_classification,
            budget_usd_month=budget,
        )

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


def example_workload() -> dict[str, Any]:
    return {
        "name": "support-api",
        "repository_url": "https://github.com/example/support-api",
        "image": "",
        "container_port": 8080,
        "health_path": "/healthz",
        "environment": "development",
        "geography": "india",
        "monthly_requests": 10000,
        "cpu_millicores": 500,
        "memory_mb": 512,
        "min_instances": 0,
        "max_instances": 3,
        "scale_to_zero": True,
        "public_access": True,
        "database": "none",
        "object_storage": False,
        "background_worker": False,
        "availability": "standard",
        "data_classification": "internal",
        "budget_usd_month": 0,
    }


def _validate_repository_url(value: str) -> None:
    parsed = urlsplit(value)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or len(parts) != 2
        or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts)
    ):
        raise LaunchpadError(
            "repository_url must be a clean HTTPS GitHub OWNER/REPOSITORY URL"
        )


def _required_string(document: Mapping[str, Any], key: str, *, maximum: int) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LaunchpadError(f"{key} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise LaunchpadError(f"{key} must contain at most {maximum} characters")
    return value


def _optional_string(
    document: Mapping[str, Any], key: str, *, default: str = "", maximum: int
) -> str:
    value = document.get(key, default)
    if not isinstance(value, str):
        raise LaunchpadError(f"{key} must be a string")
    value = value.strip()
    if len(value) > maximum:
        raise LaunchpadError(f"{key} must contain at most {maximum} characters")
    return value


def _choice(
    document: Mapping[str, Any], key: str, choices: set[str], default: str
) -> str:
    value = document.get(key, default)
    if not isinstance(value, str) or value not in choices:
        raise LaunchpadError(f"{key} must be one of: {', '.join(sorted(choices))}")
    return value


def _bounded_int(
    document: Mapping[str, Any], key: str, minimum: int, maximum: int, default: int
) -> int:
    value = document.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LaunchpadError(f"{key} must be an integer")
    if not minimum <= value <= maximum:
        raise LaunchpadError(f"{key} must be between {minimum} and {maximum}")
    return value


def _bounded_number(
    document: Mapping[str, Any], key: str, minimum: float, maximum: float, default: float
) -> float:
    value = document.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LaunchpadError(f"{key} must be a number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise LaunchpadError(f"{key} must be between {minimum} and {maximum}")
    return round(result, 2)


def _boolean(document: Mapping[str, Any], key: str, default: bool) -> bool:
    value = document.get(key, default)
    if not isinstance(value, bool):
        raise LaunchpadError(f"{key} must be true or false")
    return value

