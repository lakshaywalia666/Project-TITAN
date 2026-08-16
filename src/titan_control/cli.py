"""Machine-readable command-line interface for the Titan control plane."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from titan_control.domain import Identity
from titan_control.reconciler import LocalResourceProvider, Reconciler
from titan_control.service import ControlPlane
from titan_control.store import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="titan")
    parser.add_argument(
        "--database",
        default=os.environ.get("TITAN_DATABASE", "var/titan-control.db"),
        help="Path to the local control-plane database",
    )
    parser.add_argument(
        "--actor", default=os.environ.get("TITAN_ACTOR", "local-admin")
    )
    parser.add_argument(
        "--roles", default=os.environ.get("TITAN_ROLES", "admin")
    )
    parser.add_argument(
        "--projects", default=os.environ.get("TITAN_PROJECTS", "")
    )
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    create_project = project_commands.add_parser("create")
    create_project.add_argument("name")
    create_project.add_argument("--idempotency-key", default=None)
    project_commands.add_parser("list")

    resource = commands.add_parser("resource")
    resource_commands = resource.add_subparsers(dest="resource_command", required=True)
    create_resource = resource_commands.add_parser("create")
    create_resource.add_argument("project_id")
    create_resource.add_argument("kind")
    create_resource.add_argument("name")
    create_resource.add_argument("--spec", required=True)
    create_resource.add_argument("--idempotency-key", default=None)
    list_resources = resource_commands.add_parser("list")
    list_resources.add_argument("project_id")
    get_resource = resource_commands.add_parser("get")
    get_resource.add_argument("resource_id")
    delete_resource = resource_commands.add_parser("delete")
    delete_resource.add_argument("resource_id")

    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--limit", type=int, default=20)

    events = commands.add_parser("events")
    events.add_argument("--limit", type=int, default=100)

    operations = commands.add_parser("operations")
    operations.add_argument("--resource-id", default=None)

    usage = commands.add_parser("usage")
    usage.add_argument("project_id")
    return parser


def identity_from_arguments(arguments: argparse.Namespace) -> Identity:
    return Identity(
        subject=arguments.actor,
        roles=tuple(item.strip() for item in arguments.roles.split(",") if item.strip()),
        project_ids=tuple(
            item.strip() for item in arguments.projects.split(",") if item.strip()
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    store = SQLiteStore(Path(arguments.database))
    control_plane = ControlPlane(store)
    identity = identity_from_arguments(arguments)

    try:
        result: Any
        if arguments.command == "project" and arguments.project_command == "create":
            result = control_plane.create_project(
                identity=identity,
                name=arguments.name,
                idempotency_key=arguments.idempotency_key or uuid4().hex,
            ).to_dict()
        elif arguments.command == "project" and arguments.project_command == "list":
            result = [
                project.to_dict()
                for project in control_plane.list_projects(identity=identity)
            ]
        elif arguments.command == "resource" and arguments.resource_command == "create":
            result = control_plane.create_resource(
                identity=identity,
                project_id=arguments.project_id,
                kind=arguments.kind,
                name=arguments.name,
                spec=json.loads(arguments.spec),
                idempotency_key=arguments.idempotency_key or uuid4().hex,
            ).to_dict()
        elif arguments.command == "resource" and arguments.resource_command == "list":
            result = [
                resource.to_dict()
                for resource in control_plane.list_resources(
                    identity=identity, project_id=arguments.project_id
                )
            ]
        elif arguments.command == "resource" and arguments.resource_command == "get":
            result = control_plane.get_resource(
                identity=identity, resource_id=arguments.resource_id
            ).to_dict()
        elif arguments.command == "resource" and arguments.resource_command == "delete":
            result = control_plane.delete_resource(
                identity=identity, resource_id=arguments.resource_id
            ).to_dict()
        elif arguments.command == "reconcile":
            summary = Reconciler(store, LocalResourceProvider()).run_once(arguments.limit)
            result = {
                "claimed": summary.claimed,
                "succeeded": summary.succeeded,
                "failed": summary.failed,
            }
        elif arguments.command == "events":
            result = store.list_audit_events(arguments.limit)
        elif arguments.command == "operations":
            result = store.list_operations(arguments.resource_id)
        elif arguments.command == "usage":
            result = store.usage_summary(arguments.project_id)
        else:
            parser.error("unsupported command")
            return 2
    except (ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"error": {"type": type(error).__name__, "message": str(error)}},
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0

