"""Versioned, ACL-aware knowledge ingestion and hybrid retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from titan_control.domain import new_id, utc_now

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class KnowledgeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AccessControl:
    public: bool = False
    subjects: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()

    def permits(self, *, subject: str, project_id: str) -> bool:
        return self.public or subject in self.subjects or project_id in self.projects


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    source_id: str
    document_version: int
    content: str
    score: float
    metadata: Mapping[str, Any]

    def citation(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "document_version": self.document_version,
            "chunk_id": self.chunk_id,
        }


KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    acl_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(knowledge_base_id, source_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    UNIQUE(document_id, ordinal)
);
"""


class KnowledgeStore:
    def __init__(self, path: str | Path, *, embedding_dimensions: int = 64) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_dimensions = embedding_dimensions
        with closing(self._connect()) as connection:
            connection.executescript(KNOWLEDGE_SCHEMA)
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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

    def upsert_document(
        self,
        *,
        knowledge_base_id: str,
        source_id: str,
        content: str,
        acl: AccessControl,
        metadata: Mapping[str, Any] | None = None,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
    ) -> dict[str, Any]:
        if not knowledge_base_id or not source_id or not content.strip():
            raise KnowledgeError("knowledge base, source and content are required")
        if not 100 <= chunk_size <= 8_000:
            raise KnowledgeError("chunk_size must be between 100 and 8000")
        if not 0 <= chunk_overlap < chunk_size:
            raise KnowledgeError("chunk_overlap must be smaller than chunk_size")

        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunks = _chunk_text(content, chunk_size, chunk_overlap)
        with self.transaction() as connection:
            existing = connection.execute(
                """
                SELECT * FROM documents
                WHERE knowledge_base_id = ? AND source_id = ?
                """,
                (knowledge_base_id, source_id),
            ).fetchone()
            if existing is not None and existing["checksum"] == checksum and not existing["deleted"]:
                return {
                    "document_id": existing["id"],
                    "version": int(existing["version"]),
                    "changed": False,
                    "chunks": connection.execute(
                        "SELECT COUNT(*) FROM chunks WHERE document_id = ?",
                        (existing["id"],),
                    ).fetchone()[0],
                }

            document_id = existing["id"] if existing is not None else new_id("doc")
            version = int(existing["version"]) + 1 if existing is not None else 1
            acl_json = json.dumps(
                {
                    "public": acl.public,
                    "subjects": list(acl.subjects),
                    "projects": list(acl.projects),
                },
                sort_keys=True,
            )
            metadata_json = json.dumps(dict(metadata or {}), sort_keys=True)
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO documents(
                        id, knowledge_base_id, source_id, version, checksum,
                        acl_json, metadata_json, deleted, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        document_id,
                        knowledge_base_id,
                        source_id,
                        version,
                        checksum,
                        acl_json,
                        metadata_json,
                        utc_now(),
                    ),
                )
            else:
                connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
                connection.execute(
                    """
                    UPDATE documents SET version = ?, checksum = ?, acl_json = ?,
                        metadata_json = ?, deleted = 0, updated_at = ? WHERE id = ?
                    """,
                    (
                        version,
                        checksum,
                        acl_json,
                        metadata_json,
                        utc_now(),
                        document_id,
                    ),
                )
            for ordinal, chunk in enumerate(chunks):
                connection.execute(
                    """
                    INSERT INTO chunks(id, document_id, ordinal, content, embedding_json)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("chk"),
                        document_id,
                        ordinal,
                        chunk,
                        json.dumps(_hash_embedding(chunk, self.embedding_dimensions)),
                    ),
                )
        return {
            "document_id": document_id,
            "version": version,
            "changed": True,
            "chunks": len(chunks),
        }

    def delete_document(self, *, knowledge_base_id: str, source_id: str) -> None:
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT id FROM documents
                WHERE knowledge_base_id = ? AND source_id = ? AND deleted = 0
                """,
                (knowledge_base_id, source_id),
            ).fetchone()
            if row is None:
                raise KnowledgeError(f"active source does not exist: {source_id}")
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (row["id"],))
            connection.execute(
                "UPDATE documents SET deleted = 1, updated_at = ? WHERE id = ?",
                (utc_now(), row["id"]),
            )

    def retrieve(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        subject: str,
        project_id: str,
        limit: int = 5,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            raise KnowledgeError("query must not be empty")
        if not 1 <= limit <= 20:
            raise KnowledgeError("limit must be between 1 and 20")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT c.id AS chunk_id, c.content, c.embedding_json,
                       d.source_id, d.version, d.acl_json, d.metadata_json
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE d.knowledge_base_id = ? AND d.deleted = 0
                """,
                (knowledge_base_id,),
            ).fetchall()

        query_terms = set(_tokens(query))
        query_embedding = _hash_embedding(query, self.embedding_dimensions)
        results: list[RetrievedChunk] = []
        for row in rows:
            acl_document = json.loads(row["acl_json"])
            acl = AccessControl(
                public=bool(acl_document.get("public", False)),
                subjects=tuple(acl_document.get("subjects", [])),
                projects=tuple(acl_document.get("projects", [])),
            )
            if not acl.permits(subject=subject, project_id=project_id):
                continue
            content_terms = set(_tokens(row["content"]))
            lexical = (
                len(query_terms & content_terms) / len(query_terms)
                if query_terms
                else 0.0
            )
            semantic = _cosine(query_embedding, json.loads(row["embedding_json"]))
            score = 0.6 * lexical + 0.4 * max(semantic, 0.0)
            if score <= 0:
                continue
            results.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    source_id=row["source_id"],
                    document_version=int(row["version"]),
                    content=row["content"],
                    score=round(score, 6),
                    metadata=json.loads(row["metadata_json"]),
                )
            )
        results.sort(key=lambda item: (-item.score, item.source_id, item.chunk_id))
        return results[:limit]


def _chunk_text(content: str, size: int, overlap: int) -> list[str]:
    normalized = " ".join(content.split())
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def _tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def _hash_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / magnitude for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise KnowledgeError("embedding dimensions do not match")
    return sum(a * b for a, b in zip(left, right, strict=True))

