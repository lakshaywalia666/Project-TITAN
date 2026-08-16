"""Deterministic quota-aware scheduler used by Titan capacity laboratories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Mapping


class SchedulingError(RuntimeError):
    pass


class QuotaDenied(SchedulingError):
    pass


class InsufficientCapacity(SchedulingError):
    pass


@dataclass(frozen=True, slots=True)
class Resources:
    cpu_millicores: int
    memory_mb: int
    gpus: int = 0

    def fits(self, other: "Resources") -> bool:
        return (
            self.cpu_millicores >= other.cpu_millicores
            and self.memory_mb >= other.memory_mb
            and self.gpus >= other.gpus
        )

    def add(self, other: "Resources") -> "Resources":
        return Resources(
            self.cpu_millicores + other.cpu_millicores,
            self.memory_mb + other.memory_mb,
            self.gpus + other.gpus,
        )

    def subtract(self, other: "Resources") -> "Resources":
        return Resources(
            self.cpu_millicores - other.cpu_millicores,
            self.memory_mb - other.memory_mb,
            self.gpus - other.gpus,
        )


@dataclass(frozen=True, slots=True)
class TenantQuota:
    tenant_id: str
    limit: Resources


@dataclass(frozen=True, slots=True)
class Node:
    name: str
    capacity: Resources
    accelerator_class: str | None = None


@dataclass(frozen=True, slots=True)
class Workload:
    id: str
    tenant_id: str
    request: Resources
    accelerator_class: str | None = None
    priority: int = 0
    preemptible: bool = False


@dataclass(frozen=True, slots=True)
class Placement:
    workload_id: str
    tenant_id: str
    node_name: str
    request: Resources


class CapacityPlanner:
    def __init__(self, nodes: tuple[Node, ...], quotas: tuple[TenantQuota, ...]) -> None:
        if not nodes:
            raise ValueError("at least one node is required")
        if len({node.name for node in nodes}) != len(nodes):
            raise ValueError("node names must be unique")
        self.nodes = {node.name: node for node in nodes}
        self.quotas = {quota.tenant_id: quota for quota in quotas}
        self.placements: dict[str, Placement] = {}

    def place(
        self,
        workload: Workload,
        *,
        strategy: Literal["binpack", "spread"] = "binpack",
    ) -> Placement:
        if workload.id in self.placements:
            return self.placements[workload.id]
        quota = self.quotas.get(workload.tenant_id)
        if quota is None:
            raise QuotaDenied(f"tenant has no capacity quota: {workload.tenant_id}")
        projected = self.tenant_usage(workload.tenant_id).add(workload.request)
        if not quota.limit.fits(projected):
            raise QuotaDenied(f"tenant quota exceeded: {workload.tenant_id}")

        candidates: list[tuple[tuple[int, int, int], Node]] = []
        for node in self.nodes.values():
            if workload.accelerator_class and node.accelerator_class != workload.accelerator_class:
                continue
            available = self.node_available(node.name)
            if not available.fits(workload.request):
                continue
            remaining = available.subtract(workload.request)
            score = (
                remaining.gpus,
                remaining.memory_mb,
                remaining.cpu_millicores,
            )
            candidates.append((score, node))
        if not candidates:
            raise InsufficientCapacity(f"no compatible node can place workload {workload.id}")
        candidates.sort(key=lambda item: (item[0], item[1].name), reverse=strategy == "spread")
        selected = candidates[0][1]
        placement = Placement(
            workload_id=workload.id,
            tenant_id=workload.tenant_id,
            node_name=selected.name,
            request=workload.request,
        )
        self.placements[workload.id] = placement
        return placement

    def release(self, workload_id: str) -> None:
        self.placements.pop(workload_id, None)

    def tenant_usage(self, tenant_id: str) -> Resources:
        return _sum_resources(
            placement.request
            for placement in self.placements.values()
            if placement.tenant_id == tenant_id
        )

    def node_available(self, node_name: str) -> Resources:
        node = self.nodes[node_name]
        used = _sum_resources(
            placement.request
            for placement in self.placements.values()
            if placement.node_name == node_name
        )
        return node.capacity.subtract(used)

    def usage_report(self) -> Mapping[str, Mapping[str, int]]:
        return {
            tenant_id: {
                "cpu_millicores": usage.cpu_millicores,
                "memory_mb": usage.memory_mb,
                "gpus": usage.gpus,
            }
            for tenant_id in sorted(self.quotas)
            for usage in (self.tenant_usage(tenant_id),)
        }


def _sum_resources(values: Iterable[Resources]) -> Resources:
    total = Resources(0, 0, 0)
    for value in values:
        total = total.add(value)
    return total
