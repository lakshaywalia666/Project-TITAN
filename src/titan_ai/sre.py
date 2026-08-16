"""Evidence correlation for a read-only, uncertainty-aware SRE assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DeployEvent:
    version: str
    deployed_at: datetime
    changed_components: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IncidentEvidence:
    alert_started_at: datetime
    service: str
    error_ratio: float | None
    p95_latency_ms: float | None
    deploys: tuple[DeployEvent, ...] = ()
    trace_hotspots: Mapping[str, float] | None = None
    log_signals: tuple[str, ...] | None = None
    kubernetes_state: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class SREAnalysis:
    summary: str
    likely_cause: str | None
    confidence: float
    missing_sources: tuple[str, ...]
    recommended_checks: tuple[str, ...]
    automatic_action: None = None


class ReadOnlySREInvestigator:
    def analyze(self, evidence: IncidentEvidence) -> SREAnalysis:
        missing: list[str] = []
        if evidence.error_ratio is None or evidence.p95_latency_ms is None:
            missing.append("metrics")
        if evidence.trace_hotspots is None:
            missing.append("traces")
        if evidence.log_signals is None:
            missing.append("logs")
        if evidence.kubernetes_state is None:
            missing.append("kubernetes")
        if not evidence.deploys:
            missing.append("deploy-history")

        recent = [
            deploy
            for deploy in evidence.deploys
            if 0 <= (evidence.alert_started_at - deploy.deployed_at).total_seconds() <= 1800
        ]
        hotspot = None
        if evidence.trace_hotspots:
            hotspot = max(evidence.trace_hotspots, key=evidence.trace_hotspots.__getitem__)
        likely_cause = None
        checks = ["compare the first bad request with the last known-good request"]
        if recent and hotspot:
            changed = {component for deploy in recent for component in deploy.changed_components}
            if hotspot in changed:
                likely_cause = f"recent change to {hotspot} correlates with trace latency"
                checks.append(f"inspect {hotspot} rollout and dependency latency")
        if evidence.kubernetes_state and any(
            value not in {"Ready", "Healthy"} for value in evidence.kubernetes_state.values()
        ):
            checks.append("inspect non-ready workload events and termination reasons")
        if evidence.log_signals:
            checks.append("validate log claims against metrics and traces before acting")
        confidence = max(0.15, min(0.95, 0.9 - 0.13 * len(missing)))
        if likely_cause is None:
            confidence = min(confidence, 0.55)
        summary = (
            f"Read-only investigation for {evidence.service}; "
            f"{len(missing)} telemetry source(s) unavailable."
        )
        return SREAnalysis(
            summary=summary,
            likely_cause=likely_cause,
            confidence=round(confidence, 2),
            missing_sources=tuple(missing),
            recommended_checks=tuple(checks),
        )

