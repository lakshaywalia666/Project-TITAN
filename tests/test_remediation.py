from __future__ import annotations

import unittest

from titan_ai.agent import RiskLevel
from titan_ai.remediation import (
    RemediationDenied,
    RemediationEngine,
    RemediationPolicy,
)


class RemediationTests(unittest.TestCase):
    def test_failed_verification_triggers_rollback(self) -> None:
        actions: list[str] = []
        engine = RemediationEngine(
            (
                RemediationPolicy(
                    action="restart-worker",
                    risk=RiskLevel.LOW_RISK_AUTOMATIC,
                    max_actions=2,
                    window_seconds=60,
                    precondition=lambda context: bool(context["safe"]),
                    verify=lambda context: False,
                ),
            )
        )

        result = engine.execute(
            action="restart-worker",
            context={"safe": True},
            perform=lambda: actions.append("performed"),
            rollback=lambda: actions.append("rolled-back"),
        )

        self.assertTrue(result.rolled_back)
        self.assertEqual(["performed", "rolled-back"], actions)

    def test_global_kill_switch_denies_action(self) -> None:
        engine = RemediationEngine(
            (
                RemediationPolicy(
                    action="restart-worker",
                    risk=RiskLevel.LOW_RISK_AUTOMATIC,
                    max_actions=1,
                    window_seconds=60,
                    precondition=lambda context: True,
                    verify=lambda context: True,
                ),
            )
        )
        engine.disable()

        with self.assertRaises(RemediationDenied):
            engine.execute(
                action="restart-worker",
                context={},
                perform=lambda: None,
                rollback=lambda: None,
            )


if __name__ == "__main__":
    unittest.main()

