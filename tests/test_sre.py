from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from titan_ai.sre import DeployEvent, IncidentEvidence, ReadOnlySREInvestigator


class SREInvestigatorTests(unittest.TestCase):
    def test_correlates_recent_change_with_trace_hotspot_without_acting(self) -> None:
        alert_time = datetime.now(UTC)
        analysis = ReadOnlySREInvestigator().analyze(
            IncidentEvidence(
                alert_started_at=alert_time,
                service="titan-shop",
                error_ratio=0.02,
                p95_latency_ms=2300,
                deploys=(DeployEvent("v42", alert_time - timedelta(minutes=5), ("database",)),),
                trace_hotspots={"database": 1800, "gateway": 80},
                log_signals=("database timeout",),
                kubernetes_state={"titan-shop": "Ready"},
            )
        )
        self.assertIn("database", analysis.likely_cause or "")
        self.assertIsNone(analysis.automatic_action)

    def test_missing_telemetry_reduces_confidence(self) -> None:
        analysis = ReadOnlySREInvestigator().analyze(
            IncidentEvidence(
                alert_started_at=datetime.now(UTC),
                service="support",
                error_ratio=0.01,
                p95_latency_ms=None,
            )
        )
        self.assertLessEqual(analysis.confidence, 0.55)
        self.assertIn("traces", analysis.missing_sources)


if __name__ == "__main__":
    unittest.main()

