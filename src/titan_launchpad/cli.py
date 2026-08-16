"""Offline CLI for catalog inspection, assessments and dry-run plans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from titan_launchpad.catalog import catalog_document
from titan_launchpad.engine import RecommendationEngine
from titan_launchpad.models import WorkloadSpec, example_workload
from titan_launchpad.store import LaunchpadStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="titan-launchpad")
    parser.add_argument(
        "--database", default="var/titan-launchpad.db", help="SQLite planning state"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("catalog", help="print the source-linked provider catalog")
    subparsers.add_parser("example", help="print an example workload specification")
    assess = subparsers.add_parser("assess", help="persist a multi-cloud assessment")
    assess.add_argument("--file", required=True, help="workload JSON file")
    assess.add_argument("--actor", default="local-cli")
    plan = subparsers.add_parser("plan", help="create a guarded provider plan")
    plan.add_argument("--assessment", required=True)
    plan.add_argument("--provider", choices=("aws", "azure", "gcp"), required=True)
    plan.add_argument("--actor", default="local-cli")
    subparsers.add_parser("list", help="list persisted assessments")
    return parser


def main(argv: list[str] | None = None) -> None:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "catalog":
        document = catalog_document()
    elif arguments.command == "example":
        document = example_workload()
    else:
        store = LaunchpadStore(Path(arguments.database))
        engine = RecommendationEngine()
        if arguments.command == "assess":
            raw = json.loads(Path(arguments.file).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise SystemExit("workload file must contain one JSON object")
            document, _ = store.create_assessment(
                spec=WorkloadSpec.from_document(raw),
                actor=arguments.actor,
                idempotency_key=f"cli-{uuid4().hex}",
                engine=engine,
            )
        elif arguments.command == "plan":
            assessment = store.get_assessment(arguments.assessment)
            if assessment["actor"] != arguments.actor:
                raise SystemExit("assessment belongs to a different actor")
            document, _ = store.create_plan(
                assessment_id=arguments.assessment,
                provider=arguments.provider,
                actor=arguments.actor,
                idempotency_key=f"cli-{uuid4().hex}",
                engine=engine,
            )
        else:
            document = {"items": store.list_assessments(actor=None, limit=100)}
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

