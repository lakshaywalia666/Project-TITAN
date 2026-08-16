from __future__ import annotations

import unittest

from titan_edge.load_balancer import Backend, LayerSevenBalancer, NoHealthyBackend
from titan_edge.microvm import MicroVMPlanError, MicroVMPlanner, MicroVMSpec


class LoadBalancerTests(unittest.TestCase):
    def test_round_robin_and_safe_get_retry(self) -> None:
        balancer = LayerSevenBalancer((Backend("a", "http://a"), Backend("b", "http://b")), failure_threshold=1)
        calls: list[str] = []

        def transport(backend, method, path, body, timeout, request_id):
            calls.append(backend.name)
            if backend.name == "a":
                raise ConnectionError("down")
            return 200, {}, b"ok"

        response = balancer.forward(method="GET", path="/", body=b"", request_id="req", transport=transport)
        self.assertEqual(["a", "b"], calls)
        self.assertEqual(2, response.attempts)

    def test_post_is_never_retried_automatically(self) -> None:
        balancer = LayerSevenBalancer((Backend("a", "http://a"), Backend("b", "http://b")), failure_threshold=1)
        calls: list[str] = []
        def fail_transport(backend, method, path, body, timeout, request_id):
            calls.append(backend.name)
            raise ConnectionError("write outcome is unknown")

        with self.assertRaises(NoHealthyBackend):
            balancer.forward(
                method="POST",
                path="/orders",
                body=b"{}",
                request_id="req",
                transport=fail_transport,
            )
        self.assertEqual(1, len(calls))


class MicroVMPlannerTests(unittest.TestCase):
    def test_plan_is_bounded_and_digest_addressed(self) -> None:
        plan = MicroVMPlanner(allowed_bridges=("titan-br0",)).plan(
            MicroVMSpec("lab-vm-1", "sha256:" + "a" * 64, 2, 2048, 10, "titan-br0")
        )
        self.assertEqual(2, plan.limits["vcpus"])

    def test_unknown_bridge_is_rejected(self) -> None:
        with self.assertRaises(MicroVMPlanError):
            MicroVMPlanner(allowed_bridges=("titan-br0",)).plan(
                MicroVMSpec("lab-vm-1", "sha256:" + "a" * 64, 2, 2048, 10, "br0")
            )


if __name__ == "__main__":
    unittest.main()
