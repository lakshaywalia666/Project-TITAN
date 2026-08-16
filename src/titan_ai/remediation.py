"""Policy-controlled operational remediation with kill switch and rate limits."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Mapping

from titan_ai.agent import RiskLevel


class RemediationDenied(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RemediationPolicy:
    action: str
    risk: RiskLevel
    max_actions: int
    window_seconds: float
    precondition: Callable[[Mapping[str, object]], bool]
    verify: Callable[[Mapping[str, object]], bool]


@dataclass(frozen=True, slots=True)
class RemediationResult:
    action: str
    executed: bool
    verified: bool
    rolled_back: bool


class RemediationEngine:
    def __init__(self, policies: tuple[RemediationPolicy, ...]) -> None:
        self.policies = {policy.action: policy for policy in policies}
        self._history: dict[str, deque[float]] = defaultdict(deque)
        self._enabled = True
        self._lock = threading.Lock()

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def execute(
        self,
        *,
        action: str,
        context: Mapping[str, object],
        perform: Callable[[], None],
        rollback: Callable[[], None],
        human_approved: bool = False,
    ) -> RemediationResult:
        with self._lock:
            if not self._enabled:
                raise RemediationDenied("global automation kill switch is active")
            policy = self.policies.get(action)
            if policy is None:
                raise RemediationDenied("no remediation policy exists for this action")
            if policy.risk >= RiskLevel.HIGH_RISK_APPROVAL and not human_approved:
                raise RemediationDenied("high-risk remediation requires human approval")
            if policy.risk == RiskLevel.PROHIBITED:
                raise RemediationDenied("this action is prohibited from automation")
            now = time.monotonic()
            history = self._history[action]
            while history and history[0] <= now - policy.window_seconds:
                history.popleft()
            if len(history) >= policy.max_actions:
                raise RemediationDenied("remediation rate limit exceeded")
            if not policy.precondition(context):
                raise RemediationDenied("remediation precondition is not satisfied")
            history.append(now)

        perform()
        verified = policy.verify(context)
        rolled_back = False
        if not verified:
            rollback()
            rolled_back = True
        return RemediationResult(action, True, verified, rolled_back)

