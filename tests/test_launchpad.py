from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from titan_launchpad.catalog import catalog_document
from titan_launchpad.engine import RecommendationEngine
from titan_launchpad.models import (
    IdempotencyConflict,
    LaunchpadError,
    NotFoundError,
    WorkloadSpec,
    example_workload,
)
from titan_launchpad.store import LaunchpadStore


IMAGE = "ghcr.io/example/support-api@sha256:" + "a" * 64


def workload(**changes: object) -> WorkloadSpec:
    document = example_workload()
    document.update({"image": IMAGE, "budget_usd_month": 25})
    document.update(changes)
    return WorkloadSpec.from_document(document)


class LaunchpadModelTests(unittest.TestCase):
    def test_example_is_valid_but_intentionally_blocked(self) -> None:
        spec = WorkloadSpec.from_document(example_workload())
        result = RecommendationEngine().analyze(spec)

        self.assertEqual("BLOCKED", result["deployment_readiness"])
        self.assertEqual("", result["workload"]["image"])
        self.assertGreaterEqual(len(result["blockers"]), 2)

    def test_unknown_fields_and_unsafe_inputs_are_rejected(self) -> None:
        for change in (
            {"unexpected": True},
            {"repository_url": "https://github.com/example/repo?token=secret"},
            {"image": "ghcr.io/example/support-api:latest"},
            {"health_path": "/../admin"},
            {"scale_to_zero": "yes"},
        ):
            document = example_workload()
            document.update(change)
            with self.subTest(change=change), self.assertRaises(LaunchpadError):
                WorkloadSpec.from_document(document)

    def test_catalog_has_source_linked_three_cloud_services(self) -> None:
        document = catalog_document()

        self.assertEqual(
            {"aws", "azure", "gcp"},
            {provider["key"] for provider in document["providers"]},
        )
        self.assertIn("does not embed dollar estimates", document["pricing_policy"])
        for provider in document["providers"]:
            self.assertTrue(provider["calculator_url"].startswith("https://"))
            for service in provider["services"]:
                self.assertTrue(service["documentation_url"].startswith("https://"))
                self.assertTrue(service["pricing_url"].startswith("https://"))


class RecommendationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RecommendationEngine()

    def test_ready_workload_is_ranked_deterministically(self) -> None:
        first = self.engine.analyze(workload())
        second = self.engine.analyze(workload())

        self.assertEqual("READY_FOR_PROVIDER_SELECTION", first["deployment_readiness"])
        self.assertEqual(first["recommended_provider"], second["recommended_provider"])
        self.assertEqual(
            [item["score"] for item in first["recommendations"]],
            [item["score"] for item in second["recommendations"]],
        )
        self.assertTrue(all(item["cost"]["estimate_usd_month"] is None for item in first["recommendations"]))
        self.assertTrue(all(not item["cost"]["free_tier_guaranteed"] for item in first["recommendations"]))

    def test_optional_data_services_appear_in_plan(self) -> None:
        assessment = self.engine.analyze(
            workload(database="postgresql", object_storage=True)
        )
        plan = self.engine.create_plan(assessment, "gcp")
        service_keys = {item["service_key"] for item in plan["resources"]}

        self.assertEqual("READY_FOR_CREDENTIALS", plan["status"])
        self.assertIn("cloud_sql_postgresql", service_keys)
        self.assertIn("cloud_storage", service_keys)
        self.assertFalse(plan["cloud_mutation_performed"])
        self.assertEqual("PROTOTYPE_DRY_RUN", plan["iac"]["implementation_status"])
        self.assertTrue(plan["iac"]["variables"]["enable_postgresql"])
        self.assertTrue(plan["iac"]["variables"]["enable_object_storage"])

    def test_restricted_worker_is_blocked_without_duplicate_messages(self) -> None:
        assessment = self.engine.analyze(
            workload(data_classification="restricted", background_worker=True)
        )
        plan = self.engine.create_plan(assessment, "azure")

        self.assertEqual("BLOCKED", plan["status"])
        self.assertEqual(len(plan["blockers"]), len(set(plan["blockers"])))


class LaunchpadStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = LaunchpadStore(Path(self.temp.name) / "launchpad.db")
        self.engine = RecommendationEngine()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_assessment_idempotency_and_conflict(self) -> None:
        first, replayed = self.store.create_assessment(
            spec=workload(), actor="alice", idempotency_key="one", engine=self.engine
        )
        second, replayed_again = self.store.create_assessment(
            spec=workload(), actor="alice", idempotency_key="one", engine=self.engine
        )

        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(first["id"], second["id"])
        with self.assertRaises(IdempotencyConflict):
            self.store.create_assessment(
                spec=workload(name="different"),
                actor="alice",
                idempotency_key="one",
                engine=self.engine,
            )

    def test_plan_is_persisted_and_isolated_by_actor(self) -> None:
        assessment, _ = self.store.create_assessment(
            spec=workload(), actor="alice", idempotency_key="assessment", engine=self.engine
        )
        plan, replayed = self.store.create_plan(
            assessment_id=assessment["id"],
            provider="aws",
            actor="alice",
            idempotency_key="plan",
            engine=self.engine,
        )

        self.assertFalse(replayed)
        self.assertEqual(plan["id"], self.store.get_plan(plan["id"])["id"])
        self.assertEqual(1, len(self.store.list_assessments(actor="alice")))
        self.assertEqual([], self.store.list_assessments(actor="bob"))
        with self.assertRaises(NotFoundError):
            self.store.create_plan(
                assessment_id=assessment["id"],
                provider="aws",
                actor="bob",
                idempotency_key="stolen-plan",
                engine=self.engine,
            )


if __name__ == "__main__":
    unittest.main()
