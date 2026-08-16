"""SQLite persistence with transactions, audit history and retry-safe operations."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping

from titan_control.domain import (
    Operation,
    OperationState,
    Project,
    Resource,
    ResourceState,
    canonical_json,
    new_id,
    utc_now,
)


class StoreError(RuntimeError):
    pass


class NotFoundError(StoreError):
    pass


class ConflictError(StoreError):
    pass


class IdempotencyConflictError(ConflictError):
    pass


class GenerationConflictError(ConflictError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    quota_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    status_json TEXT NOT NULL,
    state TEXT NOT NULL,
    generation INTEGER NOT NULL,
    observed_generation INTEGER NOT NULL,
    deletion_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, kind, name)
);

CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES resources(id),
    action TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operations_ready
ON operations(state, next_attempt_at, created_at);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(scope, key)
);

CREATE TABLE IF NOT EXISTS audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    outcome TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_records (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    resource_id TEXT REFERENCES resources(id),
    metric TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


class SQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                (utc_now(),),
            )
            connection.commit()

    def create_project(
        self,
        *,
        name: str,
        quota: Mapping[str, int | float],
        actor: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Project:
        scope = "project:create"
        with self.transaction() as connection:
            previous = self._idempotent_response(
                connection, scope, idempotency_key, request_fingerprint
            )
            if previous is not None:
                return _project_from_mapping(previous)

            project = Project(
                id=new_id("prj"),
                name=name,
                quota=dict(quota),
                created_at=utc_now(),
            )
            try:
                connection.execute(
                    "INSERT INTO projects(id, name, quota_json, created_at) VALUES(?, ?, ?, ?)",
                    (
                        project.id,
                        project.name,
                        canonical_json(project.quota),
                        project.created_at,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ConflictError(f"project name already exists: {name}") from error

            self._save_idempotency(
                connection,
                scope,
                idempotency_key,
                request_fingerprint,
                project.to_dict(),
            )
            self._audit(
                connection,
                actor=actor,
                action="project:create",
                target_type="project",
                target_id=project.id,
                outcome="allowed",
                details={"name": name},
            )
            return project

    def list_projects(self) -> list[Project]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY created_at, id"
            ).fetchall()
        return [_project_from_row(row) for row in rows]

    def get_project(self, project_id: str) -> Project:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"project not found: {project_id}")
        return _project_from_row(row)

    def project_allocation(self, project_id: str) -> dict[str, float]:
        allocation = {"resources": 0.0, "cpu": 0.0, "memory_mb": 0.0, "gpu": 0.0}
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT spec_json FROM resources
                WHERE project_id = ? AND state != ? AND deletion_requested = 0
                """,
                (project_id, ResourceState.DELETED.value),
            ).fetchall()
        for row in rows:
            specification = json.loads(row["spec_json"])
            requested = specification.get("resources", {})
            allocation["resources"] += 1
            allocation["cpu"] += float(requested.get("cpu", 0))
            allocation["memory_mb"] += float(requested.get("memory_mb", 0))
            allocation["gpu"] += float(requested.get("gpu", 0))
        return allocation

    def create_resource(
        self,
        *,
        project_id: str,
        kind: str,
        name: str,
        spec: Mapping[str, Any],
        actor: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Resource:
        scope = f"resource:create:{project_id}"
        with self.transaction() as connection:
            self._require_project(connection, project_id)
            previous = self._idempotent_response(
                connection, scope, idempotency_key, request_fingerprint
            )
            if previous is not None:
                return _resource_from_mapping(previous)

            now = utc_now()
            resource = Resource(
                id=new_id("res"),
                project_id=project_id,
                kind=kind,
                name=name,
                spec=dict(spec),
                status={"conditions": []},
                state=ResourceState.PENDING,
                generation=1,
                observed_generation=0,
                deletion_requested=False,
                created_at=now,
                updated_at=now,
            )
            try:
                connection.execute(
                    """
                    INSERT INTO resources(
                        id, project_id, kind, name, spec_json, status_json, state,
                        generation, observed_generation, deletion_requested,
                        created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource.id,
                        resource.project_id,
                        resource.kind,
                        resource.name,
                        canonical_json(resource.spec),
                        canonical_json(resource.status),
                        resource.state.value,
                        resource.generation,
                        resource.observed_generation,
                        0,
                        resource.created_at,
                        resource.updated_at,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ConflictError(
                    f"resource already exists: {project_id}/{kind}/{name}"
                ) from error

            self._enqueue_operation(connection, resource.id, "APPLY", now)
            self._save_idempotency(
                connection,
                scope,
                idempotency_key,
                request_fingerprint,
                resource.to_dict(),
            )
            self._audit(
                connection,
                actor=actor,
                action="resource:create",
                target_type=kind,
                target_id=resource.id,
                outcome="allowed",
                details={"project_id": project_id, "name": name},
            )
            return resource

    def list_resources(
        self, project_id: str, *, include_deleted: bool = False
    ) -> list[Resource]:
        query = "SELECT * FROM resources WHERE project_id = ?"
        parameters: list[Any] = [project_id]
        if not include_deleted:
            query += " AND state != ?"
            parameters.append(ResourceState.DELETED.value)
        query += " ORDER BY created_at, id"
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_resource_from_row(row) for row in rows]

    def get_resource(self, resource_id: str) -> Resource:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM resources WHERE id = ?", (resource_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"resource not found: {resource_id}")
        return _resource_from_row(row)

    def update_resource(
        self,
        *,
        resource_id: str,
        spec: Mapping[str, Any],
        expected_generation: int,
        actor: str,
    ) -> Resource:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM resources WHERE id = ?", (resource_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"resource not found: {resource_id}")
            current = _resource_from_row(row)
            if current.deletion_requested or current.state == ResourceState.DELETED:
                raise ConflictError("a deleting or deleted resource cannot be updated")
            if current.generation != expected_generation:
                raise GenerationConflictError(
                    f"expected generation {expected_generation}, current generation is "
                    f"{current.generation}"
                )

            now = utc_now()
            new_generation = current.generation + 1
            connection.execute(
                """
                UPDATE resources
                SET spec_json = ?, state = ?, generation = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    canonical_json(spec),
                    ResourceState.UPDATING.value,
                    new_generation,
                    now,
                    resource_id,
                ),
            )
            self._enqueue_operation(connection, resource_id, "APPLY", now)
            self._audit(
                connection,
                actor=actor,
                action="resource:update",
                target_type=current.kind,
                target_id=resource_id,
                outcome="allowed",
                details={
                    "previous_generation": current.generation,
                    "generation": new_generation,
                },
            )
        return self.get_resource(resource_id)

    def request_deletion(self, *, resource_id: str, actor: str) -> Resource:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM resources WHERE id = ?", (resource_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"resource not found: {resource_id}")
            current = _resource_from_row(row)
            if current.state == ResourceState.DELETED:
                return current
            if not current.deletion_requested:
                now = utc_now()
                connection.execute(
                    """
                    UPDATE resources
                    SET deletion_requested = 1, state = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (ResourceState.DELETING.value, now, resource_id),
                )
                self._enqueue_operation(connection, resource_id, "DELETE", now)
                self._audit(
                    connection,
                    actor=actor,
                    action="resource:delete",
                    target_type=current.kind,
                    target_id=resource_id,
                    outcome="allowed",
                    details={"generation": current.generation},
                )
        return self.get_resource(resource_id)

    def claim_operations(self, limit: int = 20) -> list[Operation]:
        now = utc_now()
        claimed: list[Operation] = []
        with self.transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE state IN (?, ?) AND next_attempt_at <= ? AND attempts < 5
                ORDER BY created_at, id
                LIMIT ?
                """,
                (
                    OperationState.PENDING.value,
                    OperationState.RETRY.value,
                    now,
                    limit,
                ),
            ).fetchall()
            for row in rows:
                attempts = int(row["attempts"]) + 1
                connection.execute(
                    """
                    UPDATE operations SET state = ?, attempts = ?, updated_at = ?
                    WHERE id = ? AND state IN (?, ?)
                    """,
                    (
                        OperationState.RUNNING.value,
                        attempts,
                        now,
                        row["id"],
                        OperationState.PENDING.value,
                        OperationState.RETRY.value,
                    ),
                )
                claimed.append(
                    Operation(
                        id=row["id"],
                        resource_id=row["resource_id"],
                        action=row["action"],
                        state=OperationState.RUNNING,
                        attempts=attempts,
                        next_attempt_at=row["next_attempt_at"],
                        last_error=row["last_error"],
                        created_at=row["created_at"],
                        updated_at=now,
                    )
                )
        return claimed

    def mark_operation_succeeded(
        self, operation: Operation, *, status: Mapping[str, Any]
    ) -> None:
        now = utc_now()
        with self.transaction() as connection:
            resource_row = connection.execute(
                "SELECT * FROM resources WHERE id = ?", (operation.resource_id,)
            ).fetchone()
            if resource_row is None:
                raise NotFoundError(f"resource not found: {operation.resource_id}")
            resource = _resource_from_row(resource_row)
            final_state = (
                ResourceState.DELETED
                if operation.action == "DELETE"
                else ResourceState.READY
            )
            observed_generation = (
                resource.observed_generation
                if final_state == ResourceState.DELETED
                else resource.generation
            )
            connection.execute(
                """
                UPDATE resources
                SET state = ?, status_json = ?, observed_generation = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    final_state.value,
                    canonical_json(status),
                    observed_generation,
                    now,
                    resource.id,
                ),
            )
            connection.execute(
                """
                UPDATE operations SET state = ?, last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (OperationState.SUCCEEDED.value, now, operation.id),
            )
            self._audit(
                connection,
                actor="system:reconciler",
                action=f"operation:{operation.action.lower()}",
                target_type=resource.kind,
                target_id=resource.id,
                outcome="succeeded",
                details={"operation_id": operation.id, "attempts": operation.attempts},
            )

    def mark_operation_failed(self, operation: Operation, *, error: str) -> None:
        now = datetime.now(UTC)
        exhausted = operation.attempts >= 5
        operation_state = (
            OperationState.FAILED if exhausted else OperationState.RETRY
        )
        next_attempt = now + timedelta(seconds=min(2**operation.attempts, 60))
        with self.transaction() as connection:
            resource_row = connection.execute(
                "SELECT * FROM resources WHERE id = ?", (operation.resource_id,)
            ).fetchone()
            if resource_row is None:
                raise NotFoundError(f"resource not found: {operation.resource_id}")
            resource = _resource_from_row(resource_row)
            status = {
                "conditions": [
                    {
                        "type": "Ready",
                        "status": "False",
                        "reason": "ProviderError",
                        "message": error,
                        "observed_generation": resource.observed_generation,
                    }
                ]
            }
            connection.execute(
                "UPDATE resources SET state = ?, status_json = ?, updated_at = ? WHERE id = ?",
                (
                    ResourceState.FAILED.value,
                    canonical_json(status),
                    now.isoformat(),
                    resource.id,
                ),
            )
            connection.execute(
                """
                UPDATE operations
                SET state = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    operation_state.value,
                    next_attempt.isoformat(),
                    error[:1_000],
                    now.isoformat(),
                    operation.id,
                ),
            )
            self._audit(
                connection,
                actor="system:reconciler",
                action=f"operation:{operation.action.lower()}",
                target_type=resource.kind,
                target_id=resource.id,
                outcome="failed",
                details={
                    "operation_id": operation.id,
                    "attempts": operation.attempts,
                    "retry": not exhausted,
                    "error": error[:1_000],
                },
            )

    def list_operations(
        self, resource_id: str | None = None, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("operation limit must be between 1 and 500")
        query = "SELECT * FROM operations"
        parameters: list[Any] = []
        if resource_id is not None:
            query += " WHERE resource_id = ?"
            parameters.append(resource_id)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        parameters.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def record_usage(
        self,
        *,
        project_id: str,
        resource_id: str | None,
        metric: str,
        quantity: float,
        unit: str,
    ) -> str:
        usage_id = new_id("use")
        with self.transaction() as connection:
            self._require_project(connection, project_id)
            connection.execute(
                """
                INSERT INTO usage_records(
                    id, project_id, resource_id, metric, quantity, unit, recorded_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_id,
                    project_id,
                    resource_id,
                    metric,
                    quantity,
                    unit,
                    utc_now(),
                ),
            )
        return usage_id

    def usage_summary(self, project_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT metric, unit, SUM(quantity) AS quantity
                FROM usage_records WHERE project_id = ?
                GROUP BY metric, unit ORDER BY metric, unit
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_denial(
        self,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id: str | None,
        reason: str,
    ) -> None:
        with self.transaction() as connection:
            self._audit(
                connection,
                actor=actor,
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome="denied",
                details={"reason": reason},
            )

    def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("audit limit must be between 1 and 500")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM audit_events ORDER BY sequence DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            event = dict(row)
            event["details"] = json.loads(event.pop("details_json"))
            events.append(event)
        return events

    @staticmethod
    def _require_project(connection: sqlite3.Connection, project_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"project not found: {project_id}")

    @staticmethod
    def _enqueue_operation(
        connection: sqlite3.Connection, resource_id: str, action: str, now: str
    ) -> str:
        operation_id = new_id("op")
        connection.execute(
            """
            INSERT INTO operations(
                id, resource_id, action, state, attempts, next_attempt_at,
                last_error, created_at, updated_at
            ) VALUES(?, ?, ?, ?, 0, ?, NULL, ?, ?)
            """,
            (
                operation_id,
                resource_id,
                action,
                OperationState.PENDING.value,
                now,
                now,
                now,
            ),
        )
        return operation_id

    @staticmethod
    def _idempotent_response(
        connection: sqlite3.Connection,
        scope: str,
        key: str,
        request_fingerprint: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT request_fingerprint, response_json FROM idempotency_keys
            WHERE scope = ? AND key = ?
            """,
            (scope, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_fingerprint"] != request_fingerprint:
            raise IdempotencyConflictError(
                "idempotency key was already used for a different request"
            )
        return json.loads(row["response_json"])

    @staticmethod
    def _save_idempotency(
        connection: sqlite3.Connection,
        scope: str,
        key: str,
        request_fingerprint: str,
        response: Mapping[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO idempotency_keys(
                scope, key, request_fingerprint, response_json, created_at
            ) VALUES(?, ?, ?, ?, ?)
            """,
            (scope, key, request_fingerprint, canonical_json(response), utc_now()),
        )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id: str | None,
        outcome: str,
        details: Mapping[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events(
                id, actor, action, target_type, target_id, outcome,
                details_json, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("evt"),
                actor,
                action,
                target_type,
                target_id,
                outcome,
                canonical_json(details),
                utc_now(),
            ),
        )


def _project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        quota=json.loads(row["quota_json"]),
        created_at=row["created_at"],
    )


def _project_from_mapping(value: Mapping[str, Any]) -> Project:
    return Project(
        id=value["id"],
        name=value["name"],
        quota=value["quota"],
        created_at=value["created_at"],
    )


def _resource_from_row(row: sqlite3.Row) -> Resource:
    return Resource(
        id=row["id"],
        project_id=row["project_id"],
        kind=row["kind"],
        name=row["name"],
        spec=json.loads(row["spec_json"]),
        status=json.loads(row["status_json"]),
        state=ResourceState(row["state"]),
        generation=int(row["generation"]),
        observed_generation=int(row["observed_generation"]),
        deletion_requested=bool(row["deletion_requested"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _resource_from_mapping(value: Mapping[str, Any]) -> Resource:
    return Resource(
        id=value["id"],
        project_id=value["project_id"],
        kind=value["kind"],
        name=value["name"],
        spec=value["spec"],
        status=value["status"],
        state=ResourceState(value["state"]),
        generation=int(value["generation"]),
        observed_generation=int(value["observed_generation"]),
        deletion_requested=bool(value["deletion_requested"]),
        created_at=value["created_at"],
        updated_at=value["updated_at"],
    )
