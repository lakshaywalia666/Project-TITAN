"""Desired/observed-state reconciliation with bounded retry semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from titan_control.domain import Operation, Resource
from titan_control.store import SQLiteStore


class ProviderError(RuntimeError):
    pass


class ResourceProvider(Protocol):
    def apply(self, resource: Resource) -> Mapping[str, Any]: ...

    def delete(self, resource: Resource) -> Mapping[str, Any]: ...


class LocalResourceProvider:
    """Deterministic provider used for local development and control-loop tests."""

    def apply(self, resource: Resource) -> Mapping[str, Any]:
        if resource.spec.get("simulate_failure"):
            raise ProviderError("simulated provider failure")
        return {
            "provider": "local",
            "external_id": f"local:{resource.kind}:{resource.id}",
            "endpoint": self._endpoint(resource),
            "conditions": [
                {
                    "type": "Ready",
                    "status": "True",
                    "reason": "Reconciled",
                    "observed_generation": resource.generation,
                }
            ],
        }

    def delete(self, resource: Resource) -> Mapping[str, Any]:
        if resource.spec.get("simulate_delete_failure"):
            raise ProviderError("simulated provider deletion failure")
        return {
            "provider": "local",
            "conditions": [
                {
                    "type": "Deleted",
                    "status": "True",
                    "reason": "ProviderCleanupComplete",
                    "observed_generation": resource.observed_generation,
                }
            ],
        }

    @staticmethod
    def _endpoint(resource: Resource) -> str | None:
        if resource.kind in {"service", "model", "knowledge_base", "agent"}:
            return f"local://{resource.project_id}/{resource.kind}/{resource.name}"
        return None


@dataclass(frozen=True, slots=True)
class ReconcileSummary:
    claimed: int
    succeeded: int
    failed: int


class Reconciler:
    def __init__(self, store: SQLiteStore, provider: ResourceProvider) -> None:
        self.store = store
        self.provider = provider

    def run_once(self, limit: int = 20) -> ReconcileSummary:
        operations = self.store.claim_operations(limit)
        succeeded = 0
        failed = 0
        for operation in operations:
            try:
                resource = self.store.get_resource(operation.resource_id)
                status = self._execute(operation, resource)
                self.store.mark_operation_succeeded(operation, status=status)
                succeeded += 1
            except Exception as error:
                self.store.mark_operation_failed(operation, error=str(error))
                failed += 1
        return ReconcileSummary(
            claimed=len(operations), succeeded=succeeded, failed=failed
        )

    def _execute(
        self, operation: Operation, resource: Resource
    ) -> Mapping[str, Any]:
        if operation.action == "APPLY":
            return self.provider.apply(resource)
        if operation.action == "DELETE":
            return self.provider.delete(resource)
        raise ProviderError(f"unsupported operation action: {operation.action}")

