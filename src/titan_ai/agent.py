"""Capability-based agent runtime with external authorization and audit."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from titan_control.domain import Identity, canonical_json, utc_now


class AgentError(RuntimeError):
    pass


class ToolDenied(AgentError):
    pass


class AgentBudgetExceeded(AgentError):
    pass


class ApprovalRequired(AgentError):
    pass


class RiskLevel(IntEnum):
    OBSERVE = 0
    RECOMMEND = 1
    LOW_RISK_AUTOMATIC = 2
    CONTROLLED_CHANGE = 3
    HIGH_RISK_APPROVAL = 4
    PROHIBITED = 5


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]
    request_id: str

    def fingerprint(self) -> str:
        value = {"name": self.name, "arguments": dict(self.arguments)}
        return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: Mapping[str, Any]
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    risk: RiskLevel
    argument_types: Mapping[str, type]
    handler: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    required_roles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Approval:
    id: str
    call_fingerprint: str
    requested_by: str
    approved_by: str | None
    expires_at: datetime
    used: bool = False


class ApprovalStore:
    def __init__(self) -> None:
        self._approvals: dict[str, Approval] = {}
        self._lock = threading.Lock()

    def request(self, *, call: ToolCall, requested_by: str, ttl_seconds: int = 900) -> Approval:
        approval = Approval(
            id=f"apr_{uuid4().hex}",
            call_fingerprint=call.fingerprint(),
            requested_by=requested_by,
            approved_by=None,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        with self._lock:
            self._approvals[approval.id] = approval
        return approval

    def approve(self, approval_id: str, *, approved_by: str) -> Approval:
        with self._lock:
            current = self._approvals.get(approval_id)
            if current is None:
                raise ToolDenied("approval does not exist")
            if current.used or current.expires_at <= datetime.now(UTC):
                raise ToolDenied("approval is expired or already used")
            approved = Approval(
                id=current.id,
                call_fingerprint=current.call_fingerprint,
                requested_by=current.requested_by,
                approved_by=approved_by,
                expires_at=current.expires_at,
                used=False,
            )
            self._approvals[approval_id] = approved
            return approved

    def consume(self, approval_id: str, *, call: ToolCall) -> Approval:
        with self._lock:
            current = self._approvals.get(approval_id)
            if current is None or current.approved_by is None:
                raise ApprovalRequired("an approved authorization is required")
            if current.used or current.expires_at <= datetime.now(UTC):
                raise ApprovalRequired("approval is expired or already used")
            if current.call_fingerprint != call.fingerprint():
                raise ApprovalRequired("approval does not match the exact tool action")
            consumed = Approval(
                id=current.id,
                call_fingerprint=current.call_fingerprint,
                requested_by=current.requested_by,
                approved_by=current.approved_by,
                expires_at=current.expires_at,
                used=True,
            )
            self._approvals[approval_id] = consumed
            return consumed


class ToolGateway:
    def __init__(self, tools: tuple[ToolDefinition, ...], approvals: ApprovalStore) -> None:
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError("tool names must be unique")
        self.tools = {tool.name: tool for tool in tools}
        self.approvals = approvals
        self.audit_events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def execute(
        self,
        *,
        identity: Identity,
        capabilities: tuple[str, ...],
        call: ToolCall,
        approval_id: str | None = None,
    ) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            self._audit(identity, call, "denied", "tool does not exist")
            raise ToolDenied(f"tool does not exist: {call.name}")
        if call.name not in capabilities:
            self._audit(identity, call, "denied", "capability not granted")
            raise ToolDenied(f"agent capability does not allow tool: {call.name}")
        if tool.risk == RiskLevel.PROHIBITED:
            self._audit(identity, call, "denied", "tool is prohibited")
            raise ToolDenied(f"tool is prohibited from agent execution: {call.name}")
        if tool.required_roles and not set(tool.required_roles) & set(identity.roles):
            self._audit(identity, call, "denied", "caller role is insufficient")
            raise ToolDenied("caller identity lacks a required role")
        self._validate_arguments(tool, call.arguments)
        if tool.risk >= RiskLevel.CONTROLLED_CHANGE:
            if not approval_id:
                self._audit(identity, call, "approval_required", "missing approval")
                raise ApprovalRequired("this exact action requires human approval")
            self.approvals.consume(approval_id, call=call)
        try:
            content = dict(tool.handler(call.arguments))
        except Exception as error:
            self._audit(identity, call, "failed", str(error))
            return ToolResult(
                {"error": {"type": type(error).__name__, "message": str(error)}},
                is_error=True,
            )
        self._audit(identity, call, "succeeded", None)
        return ToolResult(content)

    @staticmethod
    def _validate_arguments(
        tool: ToolDefinition, arguments: Mapping[str, Any]
    ) -> None:
        if set(arguments) != set(tool.argument_types):
            raise ToolDenied(
                f"tool arguments must contain exactly: "
                f"{', '.join(sorted(tool.argument_types))}"
            )
        for name, expected_type in tool.argument_types.items():
            if not isinstance(arguments[name], expected_type):
                raise ToolDenied(
                    f"tool argument {name} must be {expected_type.__name__}"
                )

    def _audit(
        self,
        identity: Identity,
        call: ToolCall,
        outcome: str,
        reason: str | None,
    ) -> None:
        event = {
            "timestamp": utc_now(),
            "actor": identity.subject,
            "tool": call.name,
            "request_id": call.request_id,
            "call_fingerprint": call.fingerprint(),
            "outcome": outcome,
            "reason": reason,
        }
        with self._lock:
            self.audit_events.append(event)


@dataclass(frozen=True, slots=True)
class AgentDecision:
    final_text: str | None = None
    tool_call: ToolCall | None = None


class AgentModel(Protocol):
    def decide(
        self, *, objective: str, observations: tuple[Mapping[str, Any], ...], step: int
    ) -> AgentDecision: ...


@dataclass(frozen=True, slots=True)
class AgentBudget:
    max_steps: int = 8
    max_tool_calls: int = 5
    max_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class AgentRun:
    final_text: str
    steps: int
    tool_calls: int
    observations: tuple[Mapping[str, Any], ...]


class AgentRuntime:
    def __init__(self, tool_gateway: ToolGateway) -> None:
        self.tool_gateway = tool_gateway

    def run(
        self,
        *,
        identity: Identity,
        model: AgentModel,
        objective: str,
        capabilities: tuple[str, ...],
        budget: AgentBudget,
        approvals: Mapping[str, str] | None = None,
    ) -> AgentRun:
        if not objective.strip():
            raise AgentError("agent objective must not be empty")
        started = time.monotonic()
        observations: list[Mapping[str, Any]] = []
        tool_calls = 0
        for step in range(1, budget.max_steps + 1):
            if time.monotonic() - started > budget.max_seconds:
                raise AgentBudgetExceeded("agent time budget exceeded")
            decision = model.decide(
                objective=objective,
                observations=tuple(observations),
                step=step,
            )
            if decision.final_text is not None:
                return AgentRun(
                    final_text=decision.final_text,
                    steps=step,
                    tool_calls=tool_calls,
                    observations=tuple(observations),
                )
            if decision.tool_call is None:
                raise AgentError("model returned neither a final answer nor a tool call")
            if tool_calls >= budget.max_tool_calls:
                raise AgentBudgetExceeded("agent tool-call budget exceeded")
            tool_calls += 1
            approval_id = (approvals or {}).get(decision.tool_call.request_id)
            result = self.tool_gateway.execute(
                identity=identity,
                capabilities=capabilities,
                call=decision.tool_call,
                approval_id=approval_id,
            )
            observations.append(
                {
                    "tool": decision.tool_call.name,
                    "request_id": decision.tool_call.request_id,
                    "content": dict(result.content),
                    "is_error": result.is_error,
                }
            )
        raise AgentBudgetExceeded("agent step budget exceeded")


class ScriptedAgentModel:
    """Deterministic model used for safe integration tests and offline demos."""

    def __init__(self, decisions: tuple[AgentDecision, ...]) -> None:
        self.decisions = decisions

    def decide(
        self, *, objective: str, observations: tuple[Mapping[str, Any], ...], step: int
    ) -> AgentDecision:
        if step > len(self.decisions):
            raise AgentError("scripted model has no decision for this step")
        return self.decisions[step - 1]

