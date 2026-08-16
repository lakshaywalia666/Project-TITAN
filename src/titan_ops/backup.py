"""Verified, online SQLite backup and guarded restore operations."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    logical_name: str
    filename: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BackupManifest:
    format_version: int
    created_at: str
    artifacts: tuple[BackupArtifact, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": self.format_version,
            "created_at": self.created_at,
            "artifacts": [
                {
                    "logical_name": item.logical_name,
                    "filename": item.filename,
                    "sha256": item.sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in self.artifacts
            ],
        }


class SQLiteBackupManager:
    def backup(
        self, *, databases: Mapping[str, str | Path], destination: str | Path
    ) -> BackupManifest:
        target = Path(destination).resolve()
        target.mkdir(parents=True, exist_ok=True)
        if any(target.iterdir()):
            raise BackupError("backup destination must be empty")

        artifacts: list[BackupArtifact] = []
        for logical_name, source_value in sorted(databases.items()):
            _validate_logical_name(logical_name)
            source = Path(source_value).resolve()
            if not source.is_file():
                raise BackupError(f"database does not exist: {source}")
            output = target / f"{logical_name}.sqlite3"
            with closing(sqlite3.connect(source)) as source_connection:
                with closing(sqlite3.connect(output)) as destination_connection:
                    source_connection.backup(destination_connection)
                    integrity = destination_connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0]
                    if integrity != "ok":
                        raise BackupError(
                            f"backup integrity check failed for {logical_name}: {integrity}"
                        )
            artifacts.append(
                BackupArtifact(
                    logical_name=logical_name,
                    filename=output.name,
                    sha256=_sha256(output),
                    size_bytes=output.stat().st_size,
                )
            )

        manifest = BackupManifest(
            format_version=1,
            created_at=datetime.now(UTC).isoformat(),
            artifacts=tuple(artifacts),
        )
        manifest_path = target / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    def verify(self, backup_directory: str | Path) -> BackupManifest:
        root = Path(backup_directory).resolve()
        manifest_path = root / "manifest.json"
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BackupError("backup manifest is missing or invalid") from error
        if document.get("format_version") != 1 or not isinstance(
            document.get("artifacts"), list
        ):
            raise BackupError("backup manifest format is unsupported")
        artifacts: list[BackupArtifact] = []
        for item in document["artifacts"]:
            try:
                artifact = BackupArtifact(
                    logical_name=str(item["logical_name"]),
                    filename=str(item["filename"]),
                    sha256=str(item["sha256"]),
                    size_bytes=int(item["size_bytes"]),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise BackupError("backup artifact metadata is invalid") from error
            _validate_logical_name(artifact.logical_name)
            artifact_path = (root / artifact.filename).resolve()
            if artifact_path.parent != root:
                raise BackupError("backup artifact path escapes its backup directory")
            if (
                not artifact_path.is_file()
                or artifact_path.stat().st_size != artifact.size_bytes
                or _sha256(artifact_path) != artifact.sha256
            ):
                raise BackupError(f"backup artifact failed verification: {artifact.filename}")
            with closing(sqlite3.connect(f"file:{artifact_path}?mode=ro", uri=True)) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError(f"SQLite integrity failed: {artifact.filename}")
            artifacts.append(artifact)
        return BackupManifest(
            format_version=1,
            created_at=str(document.get("created_at", "")),
            artifacts=tuple(artifacts),
        )

    def restore(
        self,
        *,
        backup_directory: str | Path,
        destinations: Mapping[str, str | Path],
        confirmation: str,
    ) -> None:
        if confirmation != "RESTORE_TITAN_DATA":
            raise BackupError("restore requires the exact confirmation RESTORE_TITAN_DATA")
        root = Path(backup_directory).resolve()
        manifest = self.verify(root)
        artifacts = {item.logical_name: item for item in manifest.artifacts}
        if set(destinations) != set(artifacts):
            raise BackupError("restore destinations must exactly match backup artifacts")

        for logical_name, destination_value in sorted(destinations.items()):
            destination = Path(destination_value).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = root / artifacts[logical_name].filename
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".restore", dir=destination.parent
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as source_connection:
                    with closing(sqlite3.connect(temporary)) as destination_connection:
                        source_connection.backup(destination_connection)
                        if destination_connection.execute(
                            "PRAGMA integrity_check"
                        ).fetchone()[0] != "ok":
                            raise BackupError("restored SQLite database failed integrity check")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)


def _validate_logical_name(value: str) -> None:
    if not value or not value.replace("-", "").replace("_", "").isalnum():
        raise BackupError(f"invalid database logical name: {value!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

