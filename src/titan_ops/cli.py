"""Command-line recovery interface with explicit destructive-action guards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from titan_ops.backup import SQLiteBackupManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="titan-ops")
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="create and verify an online backup")
    backup.add_argument("--control", required=True)
    backup.add_argument("--knowledge", required=True)
    backup.add_argument("--destination", required=True)

    verify = commands.add_parser("verify", help="verify checksums and SQLite integrity")
    verify.add_argument("backup_directory")

    restore = commands.add_parser("restore", help="replace databases from a verified backup")
    restore.add_argument("backup_directory")
    restore.add_argument("--control", required=True)
    restore.add_argument("--knowledge", required=True)
    restore.add_argument("--confirm", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    manager = SQLiteBackupManager()
    if arguments.command == "backup":
        manifest = manager.backup(
            databases={"control": arguments.control, "knowledge": arguments.knowledge},
            destination=Path(arguments.destination),
        )
    elif arguments.command == "verify":
        manifest = manager.verify(arguments.backup_directory)
    else:
        manager.restore(
            backup_directory=arguments.backup_directory,
            destinations={"control": arguments.control, "knowledge": arguments.knowledge},
            confirmation=arguments.confirm,
        )
        manifest = manager.verify(arguments.backup_directory)
    print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

