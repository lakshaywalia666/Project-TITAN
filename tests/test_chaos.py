from __future__ import annotations

import unittest
from dataclasses import replace

from titan_ops.chaos import ChaosPlan, ChaosRunner, ChaosSafetyError


class ChaosRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = ChaosPlan(
            name="controller-restart",
            environment="lab",
            target="controller",
            fault="process-stop",
            duration_seconds=10,
            expected_impact="reconciliation pauses",
            abort_condition="API error ratio exceeds 1%",
        )
        self.runner = ChaosRunner(allowed_targets=("controller",))

    def test_fault_is_cleaned_up_and_recovery_is_verified(self) -> None:
        actions: list[str] = []
        result = self.runner.run(
            self.plan,
            baseline_probe=lambda: True,
            inject=lambda _: actions.append("inject"),
            impact_probe=lambda: "reconciliation_paused",
            recover=lambda _: actions.append("recover"),
            recovery_probe=lambda: True,
        )
        self.assertEqual(["inject", "recover"], actions)
        self.assertTrue(result.recovered)

    def test_unhealthy_baseline_aborts_before_injection(self) -> None:
        with self.assertRaises(ChaosSafetyError):
            self.runner.run(
                self.plan,
                baseline_probe=lambda: False,
                inject=lambda _: self.fail("must not inject"),
                impact_probe=lambda: "",
                recover=lambda _: None,
                recovery_probe=lambda: True,
            )

    def test_production_requires_exact_confirmation(self) -> None:
        production = replace(self.plan, environment="production")
        with self.assertRaises(ChaosSafetyError):
            self.runner._validate(production, None)


if __name__ == "__main__":
    unittest.main()
