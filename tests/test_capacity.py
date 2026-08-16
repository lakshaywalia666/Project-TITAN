from __future__ import annotations

import unittest

from titan_capacity.planner import (
    CapacityPlanner,
    InsufficientCapacity,
    Node,
    QuotaDenied,
    Resources,
    TenantQuota,
    Workload,
)


class CapacityPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = CapacityPlanner(
            nodes=(
                Node("cpu-1", Resources(4000, 8192)),
                Node("gpu-a10", Resources(8000, 32768, 1), "nvidia-a10"),
            ),
            quotas=(
                TenantQuota("team-a", Resources(6000, 16384, 1)),
                TenantQuota("team-b", Resources(2000, 4096, 0)),
            ),
        )

    def test_gpu_workload_uses_compatible_accelerator(self) -> None:
        placement = self.planner.place(
            Workload("train-1", "team-a", Resources(2000, 8192, 1), "nvidia-a10")
        )
        self.assertEqual("gpu-a10", placement.node_name)

    def test_one_tenant_exhausting_quota_does_not_consume_another_quota(self) -> None:
        self.planner.place(Workload("a-1", "team-a", Resources(4000, 4096)))
        with self.assertRaises(QuotaDenied):
            self.planner.place(Workload("a-2", "team-a", Resources(3000, 1024)))
        placement = self.planner.place(Workload("b-1", "team-b", Resources(1000, 1024)))
        self.assertEqual("team-b", placement.tenant_id)

    def test_missing_accelerator_queues_as_insufficient_capacity(self) -> None:
        with self.assertRaises(InsufficientCapacity):
            self.planner.place(
                Workload("train-h100", "team-a", Resources(1000, 4096, 1), "nvidia-h100")
            )

    def test_repeat_placement_is_idempotent(self) -> None:
        workload = Workload("api-1", "team-b", Resources(500, 512))
        self.assertEqual(self.planner.place(workload), self.planner.place(workload))


if __name__ == "__main__":
    unittest.main()

