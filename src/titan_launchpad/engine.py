"""Deterministic recommendation and guarded deployment-plan generation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from titan_launchpad.catalog import CATALOG_VERSION, PROVIDERS, Provider
from titan_launchpad.models import LaunchpadError, WorkloadSpec


WEIGHTS = {
    "application_fit": 0.30,
    "operational_simplicity": 0.25,
    "cost_control": 0.20,
    "portability": 0.15,
    "data_fit": 0.10,
}


class RecommendationEngine:
    def analyze(
        self,
        spec: WorkloadSpec,
        *,
        assessment_id: str | None = None,
        actor: str = "local",
    ) -> dict[str, Any]:
        recommendations = [
            self._recommend(provider, spec) for provider in PROVIDERS.values()
        ]
        recommendations.sort(key=lambda item: (-int(item["score"]), str(item["provider"])))
        global_blockers = _global_blockers(spec)
        global_warnings = _global_warnings(spec)
        return {
            "id": assessment_id or f"asm_{uuid4().hex}",
            "schema_version": "1.0",
            "catalog_version": CATALOG_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "actor": actor,
            "workload": spec.to_document(),
            "cloud_mutation_performed": False,
            "scope": {
                "golden_path": "containerized-http-application",
                "supported_database": "postgresql",
                "supports_object_storage": True,
                "pricing_mode": "official-calculator-required",
                "cloud_mutation_performed": False,
            },
            "deployment_readiness": (
                "BLOCKED" if global_blockers else "READY_FOR_PROVIDER_SELECTION"
            ),
            "blockers": global_blockers,
            "warnings": global_warnings,
            "recommended_provider": recommendations[0]["provider"],
            "recommendations": recommendations,
        }

    def create_plan(
        self,
        assessment: dict[str, Any],
        provider_key: str,
        *,
        plan_id: str | None = None,
        actor: str = "local",
    ) -> dict[str, Any]:
        if provider_key not in PROVIDERS:
            raise LaunchpadError("provider must be aws, azure or gcp")
        recommendation = next(
            (
                item
                for item in assessment["recommendations"]
                if item["provider"] == provider_key
            ),
            None,
        )
        if recommendation is None:
            raise LaunchpadError("assessment does not contain the selected provider")
        workload = assessment["workload"]
        blockers = list(
            dict.fromkeys(
                list(assessment.get("blockers", []))
                + list(recommendation.get("blockers", []))
            )
        )
        provider = PROVIDERS[provider_key]
        resources = [
            _resource_step(provider.compute, "application runtime", required=True),
            _resource_step(provider.registry, "immutable image delivery", required=True),
            _resource_step(provider.identity, "deployment and workload identity", required=True),
            _resource_step(provider.secrets, "runtime secret references", required=True),
            _resource_step(provider.observability, "logs, metrics and alerts", required=True),
        ]
        if workload["database"] == "postgresql":
            resources.append(
                _resource_step(provider.database, "managed application database", required=True)
            )
        if workload["object_storage"]:
            resources.append(
                _resource_step(provider.object_storage, "application object storage", required=True)
            )

        repository = workload["repository_url"].removeprefix("https://github.com/")
        status = "BLOCKED" if blockers else "READY_FOR_CREDENTIALS"
        return {
            "id": plan_id or f"pln_{uuid4().hex}",
            "schema_version": "1.0",
            "assessment_id": assessment["id"],
            "created_at": datetime.now(UTC).isoformat(),
            "actor": actor,
            "provider": provider_key,
            "provider_name": provider.name,
            "region": recommendation["region"],
            "status": status,
            "cloud_mutation_performed": False,
            "approval_required": True,
            "credentials_policy": "OIDC_ONLY_NO_LONG_LIVED_KEYS",
            "blockers": blockers,
            "resources": resources,
            "public_inputs": {
                "repository": repository,
                "image": workload["image"],
                "container_port": workload["container_port"],
                "health_path": workload["health_path"],
                "min_instances": workload["min_instances"],
                "max_instances": workload["max_instances"],
            },
            "secret_references": _secret_references(workload),
            "preflight_checks": [
                "Recalculate the architecture in the official provider calculator.",
                "Set a provider budget alert and a hard operator-approved cost ceiling.",
                "Verify the image digest and keyless signature from the source repository.",
                "Review least-privilege OIDC and workload identity policies.",
                "Run OpenTofu fmt, validate and plan without auto-approval.",
                "Require a human approval before apply.",
            ],
            "delivery_stages": [
                "test",
                "build",
                "scan-and-sbom",
                "sign",
                "mirror-to-provider-registry",
                "opentofu-plan",
                "human-approval",
                "deploy",
                "health-check",
                "observe",
            ],
            "rollback": {
                "strategy": "restore previous signed image revision",
                "automatic_trigger": "failed health verification",
                "stateful_data": "database changes require a separately reviewed migration rollback",
            },
            "destroy": {
                "required_for_preview": True,
                "command": f"tofu -chdir=infrastructure/opentofu/launchpad/{provider_key} destroy",
                "final_check": "confirm every generated resource is absent in the provider console",
            },
            "iac": {
                "engine": "OpenTofu",
                "mode": "generated-managed-service-plan",
                "module_path": f"infrastructure/opentofu/launchpad/{provider_key}",
                "implementation_status": "PROTOTYPE_DRY_RUN",
                "variables": {
                    "project_name": workload["name"],
                    "repository_url": workload["repository_url"],
                    "image": workload["image"],
                    "region": recommendation["region"],
                    "container_port": workload["container_port"],
                    "health_path": workload["health_path"],
                    "public_access": workload["public_access"],
                    "enable_postgresql": workload["database"] == "postgresql",
                    "enable_object_storage": workload["object_storage"],
                    "budget_usd_month": workload["budget_usd_month"],
                },
            },
            "next_action": (
                "Resolve blockers before credentials are connected."
                if blockers
                else "Review cost and identity, then connect provider OIDC for a disposable test."
            ),
        }

    def _recommend(self, provider: Provider, spec: WorkloadSpec) -> dict[str, Any]:
        criteria = {
            "application_fit": 88,
            "operational_simplicity": {"aws": 82, "azure": 86, "gcp": 90}[provider.key],
            "cost_control": {"aws": 70, "azure": 82, "gcp": 88}[provider.key],
            "portability": {"aws": 75, "azure": 86, "gcp": 82}[provider.key],
            "data_fit": 85 if spec.database == "postgresql" else 90,
        }
        reasons: list[str] = []
        warnings: list[str] = []
        blockers: list[str] = []

        if spec.scale_to_zero:
            if provider.key == "gcp":
                criteria["cost_control"] += 4
                reasons.append("Cloud Run directly fits the requested scale-to-zero HTTP shape.")
            elif provider.key == "azure":
                criteria["cost_control"] += 2
                reasons.append("Container Apps fits event-driven scaling for the requested HTTP service.")
            else:
                warnings.append(
                    "Confirm App Runner's minimum provisioned capacity against the budget; do not assume zero idle cost."
                )
        if spec.image:
            if provider.key in {"aws", "gcp"}:
                reasons.append(
                    f"Mirror the signed GHCR digest into {provider.registry.name} before managed deployment."
                )
            else:
                reasons.append(
                    "The public digest can be evaluated directly; use ACR for controlled production delivery."
                )
        if spec.database == "postgresql":
            criteria["cost_control"] -= 12
            warnings.append(
                f"{provider.database.name} is a standing cost driver and must be priced separately."
            )
            reasons.append(f"{provider.database.name} satisfies the requested PostgreSQL boundary.")
        if spec.object_storage:
            reasons.append(f"{provider.object_storage.name} satisfies durable object storage.")
        if spec.availability == "high":
            criteria["cost_control"] -= 10
            warnings.append(
                "High availability normally adds redundant compute or database capacity; calculator review is mandatory."
            )
        if spec.environment == "production":
            criteria["operational_simplicity"] -= 4
            reasons.append("Managed revisions and observability reduce production operational burden.")
        if spec.data_classification in {"confidential", "restricted"}:
            criteria["operational_simplicity"] -= 8
            warnings.append(
                "Private networking, managed secrets, encryption policy and data-residency review are required."
            )
        if spec.data_classification == "restricted":
            blockers.append(
                "The prototype cannot approve restricted data; a company security architecture review is required."
            )
        if spec.background_worker:
            blockers.append(
                "The first deployable golden path supports an HTTP service only; design the worker as a separate job/service."
            )

        criteria = {key: max(0, min(100, value)) for key, value in criteria.items()}
        score = round(sum(criteria[key] * WEIGHTS[key] for key in WEIGHTS))
        services = [
            provider.compute.to_document(),
            provider.registry.to_document(),
            provider.identity.to_document(),
            provider.secrets.to_document(),
            provider.observability.to_document(),
        ]
        if spec.database == "postgresql":
            services.append(provider.database.to_document())
        if spec.object_storage:
            services.append(provider.object_storage.to_document())
        return {
            "provider": provider.key,
            "provider_name": provider.name,
            "score": score,
            "score_breakdown": criteria,
            "region": provider.regions[spec.geography],
            "compute_service": provider.compute.name,
            "architecture": services,
            "reasons": reasons or ["The managed HTTP-container target fits the bounded golden path."],
            "warnings": warnings + list(provider.notes),
            "blockers": blockers,
            "cost": {
                "estimate_usd_month": None,
                "confidence": "REQUIRES_OFFICIAL_CALCULATOR",
                "budget_supplied_usd_month": spec.budget_usd_month,
                "cost_band": _cost_band(spec),
                "calculator_url": provider.calculator_url,
                "drivers": _cost_drivers(services),
                "free_tier_guaranteed": False,
            },
        }


def _global_blockers(spec: WorkloadSpec) -> list[str]:
    blockers: list[str] = []
    if not spec.image:
        blockers.append(
            "An immutable public GHCR @sha256 image is required before a deployment plan can become credential-ready."
        )
    if spec.budget_usd_month <= 0:
        blockers.append(
            "Set a non-zero reviewed monthly budget ceiling; TITAN will not interpret zero as unlimited."
        )
    if spec.data_classification == "restricted":
        blockers.append(
            "Restricted data requires a company security and compliance review outside this prototype."
        )
    if spec.background_worker:
        blockers.append(
            "Background workers are outside the first HTTP-service deployment golden path."
        )
    return blockers


def _global_warnings(spec: WorkloadSpec) -> list[str]:
    warnings = [
        "No cloud resources were created and no dollar estimate was invented.",
        "Free-tier eligibility and prices must be verified immediately before deployment.",
    ]
    if spec.public_access:
        warnings.append(
            "Public ingress requires application authentication, rate limiting, TLS and abuse monitoring."
        )
    if spec.environment == "production" and spec.min_instances == 0:
        warnings.append(
            "A production service with zero minimum instances may experience cold-start latency."
        )
    if spec.database == "postgresql":
        warnings.append(
            "Managed PostgreSQL usually dominates the minimum cost of a low-traffic architecture."
        )
    return warnings


def _cost_band(spec: WorkloadSpec) -> str:
    points = 0
    points += 2 if spec.database == "postgresql" else 0
    points += 1 if spec.object_storage else 0
    points += 2 if spec.availability == "high" else 0
    points += 1 if spec.min_instances > 0 else 0
    points += 1 if spec.monthly_requests > 1_000_000 else 0
    return "HIGH" if points >= 5 else "MEDIUM" if points >= 2 else "LOW"


def _cost_drivers(services: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            driver
            for service in services
            for driver in service.get("cost_drivers", [])
        }
    )


def _resource_step(service: Any, purpose: str, *, required: bool) -> dict[str, Any]:
    return {
        "service_key": service.key,
        "service_name": service.name,
        "category": service.category,
        "purpose": purpose,
        "required": required,
        "documentation_url": service.documentation_url,
        "pricing_url": service.pricing_url,
    }


def _secret_references(workload: dict[str, Any]) -> list[str]:
    references = ["application runtime secrets (names only; values stay in provider secret storage)"]
    if workload["database"] == "postgresql":
        references.append("DATABASE_URL provider-secret reference")
    if workload["object_storage"]:
        references.append("object storage identity binding; static storage keys are prohibited")
    return references
