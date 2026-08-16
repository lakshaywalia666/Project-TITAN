from __future__ import annotations

import unittest

from titan_observability.metrics import MetricsRegistry


class MetricsRegistryTests(unittest.TestCase):
    def test_prometheus_output_contains_counter_gauge_and_histogram(self) -> None:
        metrics = MetricsRegistry()
        metrics.counter("titan_test_events_total", labels={"outcome": "ok"})
        metrics.gauge("titan_test_workers", 2)
        metrics.histogram("titan_test_latency_seconds", 0.02)

        output = metrics.render_prometheus().decode("utf-8")

        self.assertIn('titan_test_events_total{outcome="ok"} 1', output)
        self.assertIn("titan_test_workers 2", output)
        self.assertIn('titan_test_latency_seconds_bucket{le="0.025"} 1', output)
        self.assertIn("titan_test_latency_seconds_count 1", output)

    def test_rejects_negative_counters(self) -> None:
        with self.assertRaises(ValueError):
            MetricsRegistry().counter("titan_invalid_total", -1)

