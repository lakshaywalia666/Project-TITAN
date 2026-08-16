"""Validated microVM provisioning plan; execution remains an explicit lab boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass


SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class MicroVMPlanError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MicroVMSpec:
    name: str
    base_image_digest: str
    vcpus: int
    memory_mb: int
    disk_gb: int
    bridge: str
    network_egress: bool = False


@dataclass(frozen=True, slots=True)
class MicroVMPlan:
    name: str
    steps: tuple[str, ...]
    limits: dict[str, int | bool]


class MicroVMPlanner:
    def __init__(self, *, allowed_bridges: tuple[str, ...]) -> None:
        self.allowed_bridges = set(allowed_bridges)

    def plan(self, spec: MicroVMSpec) -> MicroVMPlan:
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,30}", spec.name):
            raise MicroVMPlanError("microVM name is invalid")
        if not SHA256.fullmatch(spec.base_image_digest):
            raise MicroVMPlanError("base image must be addressed by SHA-256 digest")
        if spec.bridge not in self.allowed_bridges:
            raise MicroVMPlanError("network bridge is outside the allow-list")
        if not 1 <= spec.vcpus <= 4 or not 256 <= spec.memory_mb <= 8192 or not 2 <= spec.disk_gb <= 40:
            raise MicroVMPlanError("microVM resource request exceeds lab limits")
        return MicroVMPlan(
            name=spec.name,
            steps=(
                "verify-base-image-digest",
                "create-copy-on-write-disk",
                "create-tap-device",
                f"attach-to-{spec.bridge}",
                "write-restricted-vm-definition",
                "start-and-health-check",
            ),
            limits={
                "vcpus": spec.vcpus,
                "memory_mb": spec.memory_mb,
                "disk_gb": spec.disk_gb,
                "network_egress": spec.network_egress,
            },
        )

