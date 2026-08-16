from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from titan_ops.backup import BackupError, SQLiteBackupManager


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.control = self.root / "control.db"
        self.knowledge = self.root / "knowledge.db"
        for path, value in ((self.control, "control-value"), (self.knowledge, "knowledge-value")):
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE records(value TEXT NOT NULL)")
                connection.execute("INSERT INTO records VALUES(?)", (value,))
                connection.commit()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_backup_verify_and_guarded_restore(self) -> None:
        manager = SQLiteBackupManager()
        backup = self.root / "backup"
        manager.backup(
            databases={"control": self.control, "knowledge": self.knowledge},
            destination=backup,
        )
        with closing(sqlite3.connect(self.control)) as connection:
            connection.execute("UPDATE records SET value = 'damaged'")
            connection.commit()

        with self.assertRaises(BackupError):
            manager.restore(
                backup_directory=backup,
                destinations={"control": self.control, "knowledge": self.knowledge},
                confirmation="yes",
            )

        manager.restore(
            backup_directory=backup,
            destinations={"control": self.control, "knowledge": self.knowledge},
            confirmation="RESTORE_TITAN_DATA",
        )
        with closing(sqlite3.connect(self.control)) as connection:
            value = connection.execute("SELECT value FROM records").fetchone()[0]
        self.assertEqual("control-value", value)

    def test_tampered_artifact_fails_verification(self) -> None:
        manager = SQLiteBackupManager()
        backup = self.root / "backup"
        manager.backup(databases={"control": self.control}, destination=backup)
        with (backup / "control.sqlite3").open("ab") as stream:
            stream.write(b"tamper")

        with self.assertRaises(BackupError):
            manager.verify(backup)


if __name__ == "__main__":
    unittest.main()
