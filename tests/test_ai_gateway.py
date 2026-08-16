from __future__ import annotations

import unittest

from titan_ai.gateway import (
    AIGateway,
    BackendUnavailable,
    BudgetLedger,
    DeterministicBackend,
    ModelAccessDenied,
    RequestRateExceeded,
    RequestRateLimiter,
    Route,
    TokenBudgetExceeded,
)
from titan_ai.models import ChatMessage, GenerateRequest


class AIGatewayTests(unittest.TestCase):
    def gateway(self, *, small_fail: bool = False, budget: int = 1_000):
        small = DeterministicBackend(
            name="small", model="small-model", response_text="small answer", fail=small_fail
        )
        large = DeterministicBackend(
            name="large", model="large-model", response_text="large answer"
        )
        gateway = AIGateway(
            routes=(
                Route("small-route", small, 0.1, 0.2, "simple"),
                Route("large-route", large, 1.0, 2.0, "complex"),
            ),
            allowed_models={"project-a": ("small-model", "large-model")},
            budget_ledger=BudgetLedger({"project-a": budget}),
            simple_request_character_limit=100,
        )
        return gateway, small, large

    def test_simple_request_uses_cheaper_route(self) -> None:
        gateway, small, large = self.gateway()
        response = gateway.generate(
            project_id="project-a",
            request=GenerateRequest((ChatMessage("user", "hello"),)),
            correlation_id="request-1",
        )

        self.assertEqual("small-route", response.backend)
        self.assertFalse(response.fallback_used)
        self.assertEqual(1, small.calls)
        self.assertEqual(0, large.calls)

    def test_backend_failure_uses_permitted_fallback(self) -> None:
        gateway, small, large = self.gateway(small_fail=True)
        response = gateway.generate(
            project_id="project-a",
            request=GenerateRequest((ChatMessage("user", "hello"),)),
            correlation_id="request-2",
        )

        self.assertEqual("large-route", response.backend)
        self.assertTrue(response.fallback_used)
        self.assertEqual(1, small.calls)
        self.assertEqual(1, large.calls)

    def test_request_rate_is_enforced_before_model_call(self) -> None:
        gateway, small, _ = self.gateway()
        gateway.rate_limiter = RequestRateLimiter({"project-a": 1})
        request = GenerateRequest((ChatMessage("user", "hello"),))
        gateway.generate(project_id="project-a", request=request, correlation_id="first")
        with self.assertRaises(RequestRateExceeded):
            gateway.generate(project_id="project-a", request=request, correlation_id="second")
        self.assertEqual(1, small.calls)

    def test_budget_is_enforced_before_model_call(self) -> None:
        gateway, small, _ = self.gateway(budget=10)

        with self.assertRaises(TokenBudgetExceeded):
            gateway.generate(
                project_id="project-a",
                request=GenerateRequest(
                    (ChatMessage("user", "hello"),), max_output_tokens=100
                ),
                correlation_id="request-3",
            )

        self.assertEqual(0, small.calls)

    def test_denied_model_does_not_consume_budget(self) -> None:
        gateway, small, _ = self.gateway()
        with self.assertRaises(ModelAccessDenied):
            gateway.generate(
                project_id="project-a",
                request=GenerateRequest(
                    (ChatMessage("user", "hello"),),
                    requested_model="not-permitted",
                ),
                correlation_id="request-4",
            )
        self.assertEqual(0, gateway.budget_ledger.usage("project-a")["used"])
        self.assertEqual(0, small.calls)

    def test_total_backend_failure_refunds_reservation(self) -> None:
        gateway, small, large = self.gateway(small_fail=True)
        large.fail = True
        with self.assertRaises(BackendUnavailable):
            gateway.generate(
                project_id="project-a",
                request=GenerateRequest((ChatMessage("user", "hello"),)),
                correlation_id="request-5",
            )
        self.assertEqual(0, gateway.budget_ledger.usage("project-a")["used"])


if __name__ == "__main__":
    unittest.main()
