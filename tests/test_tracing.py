from __future__ import annotations

import unittest

from titan_observability.tracing import TraceContext


class TraceContextTests(unittest.TestCase):
    def test_valid_parent_preserves_trace_and_creates_new_span(self) -> None:
        parent = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
        context = TraceContext.from_header(parent)
        self.assertEqual("a" * 32, context.trace_id)
        self.assertNotEqual("b" * 16, context.span_id)
        self.assertRegex(context.as_traceparent(), r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")

    def test_invalid_or_zero_parent_is_not_reflected(self) -> None:
        context = TraceContext.from_header("00-" + "0" * 32 + "-" + "0" * 16 + "-01")
        self.assertNotEqual("0" * 32, context.trace_id)


if __name__ == "__main__":
    unittest.main()

