from __future__ import annotations

import unittest

from titan_operator.reconcile import FINALIZER, OperatorValidationError, plan_service_reconciliation


def service_resource(*, deleting: bool = False, finalizer: bool = True) -> dict[str, object]:
    metadata: dict[str, object] = {
        "name": "payments",
        "namespace": "tenant-a",
        "generation": 2,
        "finalizers": [FINALIZER] if finalizer else [],
    }
    if deleting:
        metadata["deletionTimestamp"] = "2026-08-16T10:00:00Z"
    return {
        "metadata": metadata,
        "spec": {"image": "registry.example/payments@sha256:abc", "replicas": 2, "port": 8080},
    }


class OperatorPlanningTests(unittest.TestCase):
    def test_missing_child_is_recreated(self) -> None:
        plan = plan_service_reconciliation(service_resource(), child_deployment=None)
        self.assertIn("apply-child", [action.kind for action in plan.actions])
        self.assertEqual("Reconciling", plan.status["conditions"][0]["reason"])

    def test_deletion_waits_for_child_before_removing_finalizer(self) -> None:
        existing_child = {"metadata": {}, "spec": {}, "status": {}}
        first = plan_service_reconciliation(
            service_resource(deleting=True), child_deployment=existing_child
        )
        second = plan_service_reconciliation(
            service_resource(deleting=True), child_deployment=None
        )
        self.assertEqual("delete-child", first.actions[0].kind)
        self.assertEqual("remove-finalizer", second.actions[0].kind)

    def test_external_provider_requeues_without_infinite_busy_loop(self) -> None:
        plan = plan_service_reconciliation(
            service_resource(), child_deployment=None, provider_ready=False
        )
        self.assertEqual(10, plan.requeue_after_seconds)
        self.assertEqual("ExternalProviderPending", plan.status["conditions"][0]["reason"])

    def test_latest_image_is_rejected(self) -> None:
        resource = service_resource()
        resource["spec"]["image"] = "example/payments:latest"
        with self.assertRaises(OperatorValidationError):
            plan_service_reconciliation(resource, child_deployment=None)


if __name__ == "__main__":
    unittest.main()

