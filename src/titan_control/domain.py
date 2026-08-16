"""Domain types shared by the Titan control plane."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


class ResourceState(StrEnum):
    PENDING = "PENDING"
    PROVISIONING = "PROVISIONING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    UPDATING = "UPDATING"
    FAILED = "FAILED"
    DELETING = "DELETING"
    DELETED = "DELETED"


class OperationState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY = "RETRY"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Identity:
    subject: str
    roles: tuple[str, ...]
    project_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    quota: Mapping[str, int | float]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "quota": dict(self.quota),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    project_id: str
    kind: str
    name: str
    spec: Mapping[str, Any]
    status: Mapping[str, Any]
    state: ResourceState
    generation: int
    observed_generation: int
    deletion_requested: bool
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kind": self.kind,
            "name": self.name,
            "spec": dict(self.spec),
            "status": dict(self.status),
            "state": self.state.value,
            "generation": self.generation,
            "observed_generation": self.observed_generation,
            "deletion_requested": self.deletion_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class Operation:
    id: str
    resource_id: str
    action: str
    state: OperationState
    attempts: int
    next_attempt_at: str
    last_error: str | None
    created_at: str
    updated_at: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

