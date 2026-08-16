from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from titan_control.domain import Identity, ResourceState
from titan_control.policy import PolicyEngine
from titan_control.reconciler import LocalResourceProvider, Reconciler
from titan_control.service import (
    AuthorizationError,
    ControlPlane,
    QuotaExceededError,
    ValidationError,
)
from titan_control.store import (
    GenerationConflictError,
    IdempotencyConflictError,
    SQLiteStore,
)


class ControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database = Path(self.temporary_directory.name) / "control.db"
        self.store = SQLiteStore(database)
        self.control_plane = ControlPlane(self.store, PolicyEngine())
        self.admin = Identity("admin@example.test", ("admin",))
        self.project = self.control_plane.create_project(
            identity=self.admin,
            name="demo",
            idempotency_key="create-demo-project",
            quota={"resources": 2, "cpu": 2, "memory_mb": 2048, "gpu": 0},
        )
        self.developer = Identity(
            "developer@example.test", ("developer",), (self.project.id,)
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def create_service(self, *, key: str = "create-service-0001"):
        return self.control_plane.create_resource(
            identity=self.developer,
            project_id=self.project.id,
            kind="service",
            name="payments-api",
            spec={
                "image": "registry.example/payments@sha256:abc",
                "resources": {"cpu": 1, "memory_mb": 512, "gpu": 0},
            },
            idempotency_key=key,
        )

    def test_idempotent_create_returns_same_resource(self) -> None:
        first = self.create_service()
        second = self.create_service()

        self.assertEqual(first.id, second.id)
        self.assertEqual(1, len(self.store.list_resources(self.project.id)))

    def test_reusing_key_for_different_request_is_rejected(self) -> None:
        self.create_service()

        with self.assertRaises(IdempotencyConflictError):
            self.control_plane.create_resource(
                identity=self.developer,
                project_id=self.project.id,
                kind="service",
                name="different-api",
                spec={"image": "registry.example/different@sha256:def"},
                idempotency_key="create-service-0001",
            )

    def test_reconciliation_converges_desired_state(self) -> None:
        created = self.create_service()

        summary = Reconciler(self.store, LocalResourceProvider()).run_once()
        observed = self.store.get_resource(created.id)

        self.assertEqual(1, summary.succeeded)
        self.assertEqual(ResourceState.READY, observed.state)
        self.assertEqual(observed.generation, observed.observed_generation)
        self.assertEqual("local", observed.status["provider"])

    def test_generation_conflict_prevents_lost_update(self) -> None:
        created = self.create_service()
        self.control_plane.update_resource(
            identity=self.developer,
            resource_id=created.id,
            spec={"image": "registry.example/payments@sha256:def"},
            expected_generation=1,
        )

        with self.assertRaises(GenerationConflictError):
            self.control_plane.update_resource(
                identity=self.developer,
                resource_id=created.id,
                spec={"image": "registry.example/payments@sha256:ghi"},
                expected_generation=1,
            )

    def test_quota_is_enforced_before_resource_creation(self) -> None:
        self.create_service()

        with self.assertRaises(QuotaExceededError):
            self.control_plane.create_resource(
                identity=self.developer,
                project_id=self.project.id,
                kind="model",
                name="oversized-model",
                spec={
                    "model_id": "example/model",
                    "resources": {"cpu": 2, "memory_mb": 512, "gpu": 0},
                },
                idempotency_key="create-model-0001",
            )

    def test_viewer_cannot_create_resource_and_denial_is_audited(self) -> None:
        viewer = Identity("viewer@example.test", ("viewer",), (self.project.id,))

        with self.assertRaises(AuthorizationError):
            self.control_plane.create_resource(
                identity=viewer,
                project_id=self.project.id,
                kind="service",
                name="forbidden-api",
                spec={"image": "registry.example/forbidden@sha256:abc"},
                idempotency_key="forbidden-create-0001",
            )

        events = self.store.list_audit_events()
        self.assertTrue(
            any(
                event["actor"] == "viewer@example.test"
                and event["outcome"] == "denied"
                for event in events
            )
        )

    def test_delete_requires_provider_cleanup_before_deleted_state(self) -> None:
        created = self.create_service()
        Reconciler(self.store, LocalResourceProvider()).run_once()

        deleting = self.control_plane.delete_resource(
            identity=self.developer, resource_id=created.id
        )
        self.assertEqual(ResourceState.DELETING, deleting.state)

        Reconciler(self.store, LocalResourceProvider()).run_once()
        deleted = self.store.get_resource(created.id)
        self.assertEqual(ResourceState.DELETED, deleted.state)

    def test_unsafe_image_and_non_dns_name_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.control_plane.create_resource(
                identity=self.developer,
                project_id=self.project.id,
                kind="service",
                name="payments-",
                spec={"image": "registry.example/payments:0.1.0"},
                idempotency_key="invalid-service-name",
            )
        with self.assertRaises(ValidationError):
            self.control_plane.create_resource(
                identity=self.developer,
                project_id=self.project.id,
                kind="service",
                name="payments",
                spec={"image": "registry.example/payments:latest"},
                idempotency_key="invalid-latest-image",
            )


if __name__ == "__main__":
    unittest.main()
