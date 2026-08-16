from __future__ import annotations

import unittest
from typing import Any, Mapping

from titan_operator.controller import OperatorController
from titan_operator.reconcile import FINALIZER


class FakeOperatorAPI:
    def __init__(self, service: dict[str, Any], child: Mapping[str, Any] | None = None) -> None:
        self.service = service
        self.child = child
        self.calls: list[tuple[str, object]] = []

    def list_services(self) -> list[Mapping[str, Any]]:
        return [self.service]

    def get_deployment(self, name: str, namespace: str) -> Mapping[str, Any] | None:
        self.calls.append(("get", (namespace, name)))
        return self.child

    def patch_finalizers(self, resource: Mapping[str, Any], finalizers: list[str]) -> None:
        self.calls.append(("finalizers", finalizers))
        self.service["metadata"]["finalizers"] = finalizers
        self.service["metadata"]["resourceVersion"] = "8"

    def apply_deployment(self, deployment: Mapping[str, Any], owner: Mapping[str, Any]) -> None:
        self.calls.append(("apply", deployment["metadata"]["name"]))

    def delete_deployment(self, name: str, namespace: str) -> None:
        self.calls.append(("delete", (namespace, name)))

    def patch_status(self, resource: Mapping[str, Any], status: Mapping[str, Any]) -> None:
        self.calls.append(("status", status["conditions"][0]["reason"]))


def service(*, image: str = "registry.example/api@sha256:abc", deleting: bool = False) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": "api",
        "namespace": "titan-system",
        "uid": "uid-1",
        "generation": 3,
        "resourceVersion": "7",
        "finalizers": [] if not deleting else [FINALIZER],
    }
    if deleting:
        metadata["deletionTimestamp"] = "2026-08-16T12:00:00Z"
    return {"metadata": metadata, "spec": {"image": image, "replicas": 1, "port": 8080}}


class OperatorControllerTests(unittest.TestCase):
    def test_plan_is_translated_to_finalizer_apply_and_status(self) -> None:
        api = FakeOperatorAPI(service())
        controller = OperatorController(api)
        reconciled, failed = controller.reconcile_all(now=100)
        self.assertEqual((1, 0), (reconciled, failed))
        self.assertIn(("finalizers", [FINALIZER]), api.calls)
        self.assertNotIn(("apply", "api"), api.calls)
        controller.reconcile_all(now=102)
        self.assertIn(("apply", "api"), api.calls)
        self.assertIn(("status", "Reconciling"), api.calls)

    def test_deleting_parent_deletes_child_before_finalizer(self) -> None:
        api = FakeOperatorAPI(service(deleting=True), child={"metadata": {}, "spec": {}})
        OperatorController(api).reconcile_all(now=100)
        self.assertIn(("delete", ("titan-system", "api")), api.calls)
        self.assertNotIn(("finalizers", []), api.calls)

    def test_invalid_spec_is_reported_without_stopping_controller(self) -> None:
        api = FakeOperatorAPI(service(image="registry.example/api:latest"))
        with self.assertLogs("titan.operator", level="WARNING") as messages:
            reconciled, failed = OperatorController(api).reconcile_all(now=100)
        self.assertEqual((0, 1), (reconciled, failed))
        self.assertIn(("status", "InvalidSpec"), api.calls)
        self.assertIn("specification rejected", messages.output[0])

    def test_requeue_deadline_prevents_busy_loop(self) -> None:
        api = FakeOperatorAPI(service())
        controller = OperatorController(api)
        controller.reconcile_all(now=100)
        first_call_count = len(api.calls)
        controller.reconcile_all(now=101)
        self.assertEqual(first_call_count, len(api.calls))


if __name__ == "__main__":
    unittest.main()
