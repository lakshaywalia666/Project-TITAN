"""Versioned, repeatable release evaluations for AI behavior."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Mapping


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    id: str
    input_text: str
    expected_contains: tuple[str, ...] = ()
    forbidden_contains: tuple[str, ...] = ()
    require_citations: bool = False
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateOutput:
    text: str
    citations: tuple[Mapping[str, object], ...] = ()
    cost: float = 0.0


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    passed: bool
    reasons: tuple[str, ...]
    latency_ms: float
    cost: float


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    suite_version: str
    results: tuple[CaseResult, ...]

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(result.passed for result in self.results) / len(self.results)

    @property
    def total_cost(self) -> float:
        return sum(result.cost for result in self.results)


class EvaluationSuite:
    def __init__(
        self,
        *,
        version: str,
        cases: tuple[EvaluationCase, ...],
        max_case_latency_ms: float = 10_000,
    ) -> None:
        if not version or not cases:
            raise ValueError("evaluation version and at least one case are required")
        if len({case.id for case in cases}) != len(cases):
            raise ValueError("evaluation case IDs must be unique")
        self.version = version
        self.cases = cases
        self.max_case_latency_ms = max_case_latency_ms

    def run(self, candidate: Callable[[str], CandidateOutput]) -> EvaluationReport:
        results: list[CaseResult] = []
        for case in self.cases:
            started = time.monotonic()
            output = candidate(case.input_text)
            latency_ms = (time.monotonic() - started) * 1_000
            normalized = output.text.casefold()
            reasons: list[str] = []
            for expected in case.expected_contains:
                if expected.casefold() not in normalized:
                    reasons.append(f"missing expected text: {expected}")
            for forbidden in case.forbidden_contains:
                if forbidden.casefold() in normalized:
                    reasons.append(f"contained forbidden text: {forbidden}")
            if case.require_citations and not output.citations:
                reasons.append("required citations were absent")
            if latency_ms > self.max_case_latency_ms:
                reasons.append(
                    f"latency {latency_ms:.2f}ms exceeded {self.max_case_latency_ms:.2f}ms"
                )
            results.append(
                CaseResult(
                    case_id=case.id,
                    passed=not reasons,
                    reasons=tuple(reasons),
                    latency_ms=round(latency_ms, 3),
                    cost=output.cost,
                )
            )
        return EvaluationReport(self.version, tuple(results))


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    minimum_pass_rate: float = 1.0
    maximum_total_cost: float | None = None

    def decide(self, report: EvaluationReport) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if report.pass_rate < self.minimum_pass_rate:
            reasons.append(
                f"pass rate {report.pass_rate:.3f} is below {self.minimum_pass_rate:.3f}"
            )
        if (
            self.maximum_total_cost is not None
            and report.total_cost > self.maximum_total_cost
        ):
            reasons.append(
                f"cost {report.total_cost:.6f} exceeds {self.maximum_total_cost:.6f}"
            )
        return not reasons, tuple(reasons)

