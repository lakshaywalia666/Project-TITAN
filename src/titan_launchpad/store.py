"""SQLite persistence and idempotency for Launchpad assessments and plans."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from titan_launchpad.engine import RecommendationEngine
from titan_launchpad.models import IdempotencyConflict, NotFoundError, WorkloadSpec


class LaunchpadStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS launchpad_assessments (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    workload_name TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_launchpad_assessments_actor_created
                    ON launchpad_assessments(actor, created_at DESC);

                CREATE TABLE IF NOT EXISTS launchpad_plans (
                    id TEXT PRIMARY KEY,
                    assessment_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (assessment_id) REFERENCES launchpad_assessments(id)
                );
                CREATE INDEX IF NOT EXISTS idx_launchpad_plans_assessment
                    ON launchpad_plans(assessment_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS launchpad_idempotency (
                    actor TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    PRIMARY KEY (actor, operation, idempotency_key)
                );
                """
            )

    def create_assessment(
        self,
        *,
        spec: WorkloadSpec,
        actor: str,
        idempotency_key: str,
        engine: RecommendationEngine,
    ) -> tuple[dict[str, Any], bool]:
        request_hash = _hash_document(spec.to_document())
        operation = "assessment:create"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(
                connection,
                actor=actor,
                operation=operation,
                key=idempotency_key,
                request_hash=request_hash,
                table="launchpad_assessments",
            )
            if replay is not None:
                connection.commit()
                return replay, True
            assessment_id = f"asm_{uuid4().hex}"
            document = engine.analyze(spec, assessment_id=assessment_id, actor=actor)
            connection.execute(
                """
                INSERT INTO launchpad_assessments
                    (id, actor, workload_name, document_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    assessment_id,
                    actor,
                    spec.name,
                    _canonical_json(document),
                    document["created_at"],
                ),
            )
            self._record_idempotency(
                connection,
                actor=actor,
                operation=operation,
                key=idempotency_key,
                request_hash=request_hash,
                result_id=assessment_id,
            )
            connection.commit()
            return document, False

    def create_plan(
        self,
        *,
        assessment_id: str,
        provider: str,
        actor: str,
        idempotency_key: str,
        engine: RecommendationEngine,
    ) -> tuple[dict[str, Any], bool]:
        request_hash = _hash_document(
            {"assessment_id": assessment_id, "provider": provider}
        )
        operation = "plan:create"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result(
                connection,
                actor=actor,
                operation=operation,
                key=idempotency_key,
                request_hash=request_hash,
                table="launchpad_plans",
            )
            if replay is not None:
                connection.commit()
                return replay, True
            assessment_row = connection.execute(
                "SELECT actor, document_json FROM launchpad_assessments WHERE id = ?",
                (assessment_id,),
            ).fetchone()
            if assessment_row is None:
                raise NotFoundError("assessment not found")
            if assessment_row["actor"] != actor:
                raise NotFoundError("assessment not found")
            assessment = json.loads(assessment_row["document_json"])
            plan_id = f"pln_{uuid4().hex}"
            document = engine.create_plan(
                assessment,
                provider,
                plan_id=plan_id,
                actor=actor,
            )
            connection.execute(
                """
                INSERT INTO launchpad_plans
                    (id, assessment_id, actor, provider, document_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    assessment_id,
                    actor,
                    provider,
                    _canonical_json(document),
                    document["created_at"],
                ),
            )
            self._record_idempotency(
                connection,
                actor=actor,
                operation=operation,
                key=idempotency_key,
                request_hash=request_hash,
                result_id=plan_id,
            )
            connection.commit()
            return document, False

    def get_assessment(self, assessment_id: str) -> dict[str, Any]:
        return self._get_document(
            "launchpad_assessments", assessment_id, "assessment not found"
        )

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        return self._get_document("launchpad_plans", plan_id, "plan not found")

    def list_assessments(
        self, *, actor: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._connection() as connection:
            if actor is None:
                rows = connection.execute(
                    """
                    SELECT document_json FROM launchpad_assessments
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT document_json FROM launchpad_assessments
                    WHERE actor = ? ORDER BY created_at DESC LIMIT ?
                    """,
                    (actor, limit),
                ).fetchall()
        return [json.loads(row["document_json"]) for row in rows]

    def _get_document(self, table: str, item_id: str, message: str) -> dict[str, Any]:
        if table not in {"launchpad_assessments", "launchpad_plans"}:
            raise ValueError("invalid table")
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT document_json FROM {table} WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(message)
        return json.loads(row["document_json"])

    @staticmethod
    def _idempotent_result(
        connection: sqlite3.Connection,
        *,
        actor: str,
        operation: str,
        key: str,
        request_hash: str,
        table: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT request_sha256, result_id FROM launchpad_idempotency
            WHERE actor = ? AND operation = ? AND idempotency_key = ?
            """,
            (actor, operation, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_hash:
            raise IdempotencyConflict(
                "idempotency key was already used for a different request"
            )
        result = connection.execute(
            f"SELECT document_json FROM {table} WHERE id = ?", (row["result_id"],)
        ).fetchone()
        if result is None:
            raise RuntimeError("idempotency record refers to a missing result")
        return json.loads(result["document_json"])

    @staticmethod
    def _record_idempotency(
        connection: sqlite3.Connection,
        *,
        actor: str,
        operation: str,
        key: str,
        request_hash: str,
        result_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO launchpad_idempotency
                (actor, operation, idempotency_key, request_sha256, result_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (actor, operation, key, request_hash, result_id),
        )


def _canonical_json(document: Any) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def _hash_document(document: Any) -> str:
    return hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()
