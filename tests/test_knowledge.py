from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from titan_ai.knowledge import AccessControl, KnowledgeStore


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(Path(self.temporary_directory.name) / "knowledge.db")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_acl_filtering_happens_before_results_are_returned(self) -> None:
        self.store.upsert_document(
            knowledge_base_id="support",
            source_id="public-guide",
            content="Reset a user password from the account settings page.",
            acl=AccessControl(projects=("project-a",)),
        )
        self.store.upsert_document(
            knowledge_base_id="support",
            source_id="secret-runbook",
            content="Reset the production root password using the protected vault.",
            acl=AccessControl(projects=("security",)),
        )

        results = self.store.retrieve(
            knowledge_base_id="support",
            query="reset password",
            subject="developer@example.test",
            project_id="project-a",
        )

        self.assertEqual(["public-guide"], [result.source_id for result in results])

    def test_update_increments_version_and_replaces_chunks(self) -> None:
        first = self.store.upsert_document(
            knowledge_base_id="support",
            source_id="guide",
            content="The first version explains deployments.",
            acl=AccessControl(public=True),
        )
        second = self.store.upsert_document(
            knowledge_base_id="support",
            source_id="guide",
            content="The second version explains safe deployment rollback.",
            acl=AccessControl(public=True),
        )

        results = self.store.retrieve(
            knowledge_base_id="support",
            query="rollback",
            subject="anyone",
            project_id="any-project",
        )
        self.assertEqual(1, first["version"])
        self.assertEqual(2, second["version"])
        self.assertTrue(all(result.document_version == 2 for result in results))

    def test_deleted_document_is_not_retrievable(self) -> None:
        self.store.upsert_document(
            knowledge_base_id="support",
            source_id="temporary",
            content="Temporary document about networking.",
            acl=AccessControl(public=True),
        )
        self.store.delete_document(
            knowledge_base_id="support", source_id="temporary"
        )

        results = self.store.retrieve(
            knowledge_base_id="support",
            query="networking",
            subject="anyone",
            project_id="any-project",
        )
        self.assertEqual([], results)


if __name__ == "__main__":
    unittest.main()

