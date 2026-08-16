"""Use-case layer enforcing policy, validation, quota and concurrency."""

from __future__ import annotations

import re
from typing import Any, Mapping

from titan_control.domain import Identity, Project, Resource, fingerprint
from titan_control.policy import PolicyEngine
from titan_control.store import SQLiteStore

NAME_PATTERN = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
SUPPORTED_KINDS = {
    "service",
    "database",
    "model",
    "knowledge_base",
    "agent",
    "job",
}
DEFAULT_QUOTA: dict[str, int | float] = {
    "resources": 50,
    "cpu": 32,
    "memory_mb": 65_536,
    "gpu": 1,
}


class ControlPlaneError(RuntimeError):
    pass


class ValidationError(ControlPlaneError):
    pass


class AuthorizationError(ControlPlaneError):
    pass


class QuotaExceededError(ControlPlaneError):
    pass


class ControlPlane:
    def __init__(self, store: SQLiteStore, policy: PolicyEngine | None = None) -> None:
        self.store = store
        self.policy = policy or PolicyEngine()

    def create_project(
        self,
        *,
        identity: Identity,
        name: str,
        idempotency_key: str,
        quota: Mapping[str, int | float] | None = None,
    ) -> Project:
        self._authorize(identity, "project:create", None, "project", None)
        normalized_name = self._validate_name(name)
        normalized_quota = self._validate_quota(quota or DEFAULT_QUOTA)
        request = {"name": normalized_name, "quota": normalized_quota}
        return self.store.create_project(
            name=normalized_name,
            quota=normalized_quota,
            actor=identity.subject,
            idempotency_key=self._validate_idempotency_key(idempotency_key),
            request_fingerprint=fingerprint(request),
        )

    def list_projects(self, *, identity: Identity) -> list[Project]:
        if "admin" in identity.roles or "platform_operator" in identity.roles:
            return self.store.list_projects()
        projects: list[Project] = []
        for project_id in identity.project_ids:
            self._authorize(identity, "project:get", project_id, "project", project_id)
            projects.append(self.store.get_project(project_id))
        return projects

    def create_resource(
        self,
        *,
        identity: Identity,
        project_id: str,
        kind: str,
        name: str,
        spec: Mapping[str, Any],
        idempotency_key: str,
    ) -> Resource:
        self._authorize(
            identity, "resource:create", project_id, kind, f"{project_id}/{name}"
        )
        normalized_kind = kind.strip().lower()
        if normalized_kind not in SUPPORTED_KINDS:
            raise ValidationError(
                f"kind must be one of: {', '.join(sorted(SUPPORTED_KINDS))}"
            )
        normalized_name = self._validate_name(name)
        normalized_spec = self._validate_spec(normalized_kind, spec)
        self._enforce_quota(project_id, normalized_spec)
        request = {
            "project_id": project_id,
            "kind": normalized_kind,
            "name": normalized_name,
            "spec": normalized_spec,
        }
        return self.store.create_resource(
            project_id=project_id,
            kind=normalized_kind,
            name=normalized_name,
            spec=normalized_spec,
            actor=identity.subject,
            idempotency_key=self._validate_idempotency_key(idempotency_key),
            request_fingerprint=fingerprint(request),
        )

    def list_resources(
        self, *, identity: Identity, project_id: str
    ) -> list[Resource]:
        self._authorize(identity, "resource:list", project_id, "project", project_id)
        return self.store.list_resources(project_id)

    def get_resource(self, *, identity: Identity, resource_id: str) -> Resource:
        resource = self.store.get_resource(resource_id)
        self._authorize(
            identity, "resource:get", resource.project_id, resource.kind, resource.id
        )
        return resource

    def update_resource(
        self,
        *,
        identity: Identity,
        resource_id: str,
        spec: Mapping[str, Any],
        expected_generation: int,
    ) -> Resource:
        current = self.store.get_resource(resource_id)
        self._authorize(
            identity,
            "resource:update",
            current.project_id,
            current.kind,
            current.id,
        )
        normalized_spec = self._validate_spec(current.kind, spec)
        self._enforce_quota(current.project_id, normalized_spec, replacing=current)
        return self.store.update_resource(
            resource_id=resource_id,
            spec=normalized_spec,
            expected_generation=expected_generation,
            actor=identity.subject,
        )

    def delete_resource(
        self, *, identity: Identity, resource_id: str
    ) -> Resource:
        current = self.store.get_resource(resource_id)
        self._authorize(
            identity,
            "resource:delete",
            current.project_id,
            current.kind,
            current.id,
        )
        return self.store.request_deletion(
            resource_id=resource_id, actor=identity.subject
        )

    def _authorize(
        self,
        identity: Identity,
        action: str,
        project_id: str | None,
        target_type: str,
        target_id: str | None,
    ) -> None:
        decision = self.policy.decide(identity, action, project_id)
        if decision.allowed:
            return
        self.store.record_denial(
            actor=identity.subject,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=decision.reason,
        )
        raise AuthorizationError(decision.reason)

    def _enforce_quota(
        self,
        project_id: str,
        candidate_spec: Mapping[str, Any],
        *,
        replacing: Resource | None = None,
    ) -> None:
        project = self.store.get_project(project_id)
        allocation = self.store.project_allocation(project_id)
        if replacing is not None:
            allocation["resources"] -= 1
            current_requested = replacing.spec.get("resources", {})
            for metric in ("cpu", "memory_mb", "gpu"):
                allocation[metric] -= float(current_requested.get(metric, 0))

        requested = candidate_spec.get("resources", {})
        projected = dict(allocation)
        projected["resources"] += 1
        for metric in ("cpu", "memory_mb", "gpu"):
            projected[metric] += float(requested.get(metric, 0))

        exceeded = [
            metric
            for metric, limit in project.quota.items()
            if metric in projected and projected[metric] > float(limit)
        ]
        if exceeded:
            summary = ", ".join(
                f"{metric}={projected[metric]}>{project.quota[metric]}"
                for metric in exceeded
            )
            raise QuotaExceededError(f"project quota exceeded: {summary}")

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = name.strip().lower()
        if not NAME_PATTERN.fullmatch(normalized):
            raise ValidationError(
                "name must start with a letter and contain only lowercase letters, "
                "digits or internal hyphens (maximum 63 characters)"
            )
        return normalized

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        normalized = value.strip()
        if not 8 <= len(normalized) <= 128:
            raise ValidationError("idempotency key must contain 8 to 128 characters")
        return normalized

    @staticmethod
    def _validate_quota(
        value: Mapping[str, int | float]
    ) -> dict[str, int | float]:
        required = set(DEFAULT_QUOTA)
        if set(value) != required:
            raise ValidationError(
                f"quota must contain exactly: {', '.join(sorted(required))}"
            )
        quota: dict[str, int | float] = {}
        for metric, quantity in value.items():
            if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
                raise ValidationError(f"quota {metric} must be numeric")
            if quantity < 0:
                raise ValidationError(f"quota {metric} must be non-negative")
            quota[metric] = quantity
        return quota

    @staticmethod
    def _validate_spec(kind: str, spec: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(spec, Mapping):
            raise ValidationError("spec must be an object")
        normalized = dict(spec)
        requirements = {
            "service": ("image",),
            "database": ("engine",),
            "model": ("model_id",),
            "knowledge_base": ("source",),
            "agent": ("tools",),
            "job": ("command",),
        }
        missing = [field for field in requirements[kind] if field not in normalized]
        if missing:
            raise ValidationError(f"missing required fields: {', '.join(missing)}")

        if kind == "service":
            image = normalized.get("image")
            image = image.strip() if isinstance(image, str) else ""
            if not image or image.endswith(":latest"):
                raise ValidationError("service image must be explicit and must not use latest")
            normalized["image"] = image
            normalized["replicas"] = ControlPlane._bounded_integer_field(
                normalized.get("replicas", 1), "replicas", 1, 20
            )
            normalized["port"] = ControlPlane._bounded_integer_field(
                normalized.get("port", 8080), "port", 1, 65_535
            )
        elif kind in {"database", "model", "knowledge_base"}:
            field = {"database": "engine", "model": "model_id", "knowledge_base": "source"}[kind]
            value = normalized.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"spec.{field} must be a non-empty string")
            normalized[field] = value.strip()
        elif kind == "agent":
            tools = normalized.get("tools")
            if (
                not isinstance(tools, list)
                or not all(isinstance(tool, str) and tool.strip() for tool in tools)
            ):
                raise ValidationError("spec.tools must be an array of non-empty strings")
            normalized["tools"] = [tool.strip() for tool in tools]
        elif kind == "job":
            command = normalized.get("command")
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(part, str) and part for part in command)
            ):
                raise ValidationError("spec.command must be a non-empty string array")

        resources = normalized.setdefault("resources", {})
        if not isinstance(resources, Mapping):
            raise ValidationError("spec.resources must be an object")
        resources = dict(resources)
        for metric, default in (("cpu", 1), ("memory_mb", 512), ("gpu", 0)):
            quantity = resources.get(metric, default)
            if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
                raise ValidationError(f"spec.resources.{metric} must be numeric")
            if quantity < 0:
                raise ValidationError(
                    f"spec.resources.{metric} must be non-negative"
                )
            resources[metric] = quantity
        normalized["resources"] = resources
        return normalized

    @staticmethod
    def _bounded_integer_field(value: object, name: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"spec.{name} must be an integer")
        if not minimum <= value <= maximum:
            raise ValidationError(f"spec.{name} must be between {minimum} and {maximum}")
        return value
