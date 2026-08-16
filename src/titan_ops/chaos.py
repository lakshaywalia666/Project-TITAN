"""Guardrails for reversible, explicitly scoped chaos experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class ChaosSafetyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ChaosPlan:
    name: str
    environment: str
    target: str
    fault: str
    duration_seconds: int
    expected_impact: str
    abort_condition: str


@dataclass(frozen=True, slots=True)
class ChaosResult:
    name: str
    injected: bool
    recovered: bool
    observations: tuple[str, ...]


class ChaosRunner:
    def __init__(
        self,
        *,
        allowed_targets: tuple[str, ...],
        max_duration_seconds: int = 300,
    ) -> None:
        self.allowed_targets = set(allowed_targets)
        self.max_duration_seconds = max_duration_seconds

    def run(
        self,
        plan: ChaosPlan,
        *,
        baseline_probe: Callable[[], bool],
        inject: Callable[[ChaosPlan], None],
        impact_probe: Callable[[], str],
        recover: Callable[[ChaosPlan], None],
        recovery_probe: Callable[[], bool],
        production_confirmation: str | None = None,
    ) -> ChaosResult:
        self._validate(plan, production_confirmation)
        if not baseline_probe():
            raise ChaosSafetyError("baseline is unhealthy; chaos experiment aborted")
        observations = ["baseline_healthy"]
        injected = False
        recovered = False
        try:
            inject(plan)
            injected = True
            observations.append(impact_probe())
        finally:
            if injected:
                recover(plan)
                recovered = recovery_probe()
                observations.append("recovered" if recovered else "recovery_failed")
        if not recovered:
            raise ChaosSafetyError("fault cleanup ran but recovery verification failed")
        return ChaosResult(plan.name, injected, recovered, tuple(observations))

    def _validate(self, plan: ChaosPlan, confirmation: str | None) -> None:
        if not plan.name or not plan.expected_impact or not plan.abort_condition:
            raise ChaosSafetyError("experiment, expected impact and abort condition are required")
        if plan.target not in self.allowed_targets:
            raise ChaosSafetyError(f"target is outside the experiment allow-list: {plan.target}")
        if not 1 <= plan.duration_seconds <= self.max_duration_seconds:
            raise ChaosSafetyError("experiment duration exceeds its safety budget")
        if plan.environment.lower() == "production" and confirmation != "CHAOS_PRODUCTION":
            raise ChaosSafetyError("production chaos requires the exact confirmation CHAOS_PRODUCTION")

