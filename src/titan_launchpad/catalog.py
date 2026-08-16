"""Versioned, source-linked provider catalog without embedded dollar prices."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


CATALOG_VERSION = "2026-08-16"


@dataclass(frozen=True, slots=True)
class Service:
    key: str
    name: str
    category: str
    purpose: str
    operational_model: str
    cost_drivers: tuple[str, ...]
    documentation_url: str
    pricing_url: str

    def to_document(self) -> dict[str, Any]:
        value = asdict(self)
        value["cost_drivers"] = list(self.cost_drivers)
        return value


@dataclass(frozen=True, slots=True)
class Provider:
    key: str
    name: str
    compute: Service
    registry: Service
    database: Service
    object_storage: Service
    secrets: Service
    identity: Service
    observability: Service
    regions: dict[str, str]
    calculator_url: str
    notes: tuple[str, ...]

    def services(self) -> tuple[Service, ...]:
        return (
            self.compute,
            self.registry,
            self.database,
            self.object_storage,
            self.secrets,
            self.identity,
            self.observability,
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "regions": self.regions,
            "calculator_url": self.calculator_url,
            "notes": list(self.notes),
            "services": [service.to_document() for service in self.services()],
        }


AWS = Provider(
    key="aws",
    name="Amazon Web Services",
    compute=Service(
        "app_runner",
        "AWS App Runner",
        "compute",
        "Managed HTTP web service for source code or ECR container images.",
        "Managed service with autoscaling and a stable service URL.",
        ("provisioned memory", "active compute", "requests", "outbound traffic"),
        "https://docs.aws.amazon.com/apprunner/latest/dg/what-is-apprunner.html",
        "https://aws.amazon.com/apprunner/pricing/",
    ),
    registry=Service(
        "ecr",
        "Amazon Elastic Container Registry",
        "registry",
        "Provider-native OCI image registry required by the managed image path.",
        "Managed regional registry.",
        ("stored image data", "image transfer", "scanning"),
        "https://docs.aws.amazon.com/AmazonECR/latest/userguide/what-is-ecr.html",
        "https://aws.amazon.com/ecr/pricing/",
    ),
    database=Service(
        "rds_postgresql",
        "Amazon RDS for PostgreSQL",
        "database",
        "Managed PostgreSQL with backups, maintenance and optional high availability.",
        "Provisioned managed database; it is a standing cost driver.",
        ("instance class", "storage", "backup retention", "multi-AZ", "traffic"),
        "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_PostgreSQL.html",
        "https://aws.amazon.com/rds/postgresql/pricing/",
    ),
    object_storage=Service(
        "s3",
        "Amazon S3",
        "object_storage",
        "Durable object storage for uploads, artifacts and backups.",
        "Managed object storage with per-operation and transfer dimensions.",
        ("stored bytes", "request classes", "retrieval", "outbound traffic"),
        "https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html",
        "https://aws.amazon.com/s3/pricing/",
    ),
    secrets=Service(
        "secrets_manager",
        "AWS Secrets Manager",
        "secrets",
        "Runtime secret references and optional rotation.",
        "Managed secret store accessed through workload identity.",
        ("secret count", "API calls", "rotation functions"),
        "https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html",
        "https://aws.amazon.com/secrets-manager/pricing/",
    ),
    identity=Service(
        "iam_oidc",
        "AWS IAM and GitHub OIDC",
        "identity",
        "Short-lived deployment and workload authorization without stored AWS keys.",
        "Federated identity and least-privilege roles.",
        (),
        "https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws",
        "https://aws.amazon.com/iam/pricing/",
    ),
    observability=Service(
        "cloudwatch",
        "Amazon CloudWatch",
        "observability",
        "Application logs, metrics, alarms and deployment diagnostics.",
        "Managed telemetry service.",
        ("log ingestion", "retention", "custom metrics", "alarms"),
        "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/WhatIsCloudWatch.html",
        "https://aws.amazon.com/cloudwatch/pricing/",
    ),
    regions={"india": "ap-south-1", "us": "us-east-1", "europe": "eu-west-1", "global": "us-east-1"},
    calculator_url="https://calculator.aws/",
    notes=(
        "App Runner managed image deployments require an Amazon ECR image mirror.",
        "Private database connectivity adds VPC networking components and cost drivers.",
    ),
)


AZURE = Provider(
    key="azure",
    name="Microsoft Azure",
    compute=Service(
        "container_apps",
        "Azure Container Apps",
        "compute",
        "Serverless container application platform with ingress, revisions and autoscaling.",
        "Managed container environment with consumption or dedicated capacity choices.",
        ("vCPU seconds", "memory seconds", "requests", "minimum replicas", "traffic"),
        "https://learn.microsoft.com/azure/container-apps/overview",
        "https://azure.microsoft.com/pricing/details/container-apps/",
    ),
    registry=Service(
        "acr",
        "Azure Container Registry",
        "registry",
        "Provider-native private OCI registry; public registries can also be used for prototypes.",
        "Managed regional registry.",
        ("registry tier", "storage", "build tasks", "traffic"),
        "https://learn.microsoft.com/azure/container-registry/container-registry-intro",
        "https://azure.microsoft.com/pricing/details/container-registry/",
    ),
    database=Service(
        "postgres_flexible",
        "Azure Database for PostgreSQL Flexible Server",
        "database",
        "Managed PostgreSQL with maintenance, backups and optional zone redundancy.",
        "Provisioned managed database; it is a standing cost driver.",
        ("compute tier", "storage", "backup retention", "high availability", "traffic"),
        "https://learn.microsoft.com/azure/postgresql/overview",
        "https://azure.microsoft.com/pricing/details/postgresql/flexible-server/",
    ),
    object_storage=Service(
        "blob_storage",
        "Azure Blob Storage",
        "object_storage",
        "Durable object storage for uploads, artifacts and backups.",
        "Managed object storage with access tiers.",
        ("stored bytes", "access tier", "operations", "retrieval", "traffic"),
        "https://learn.microsoft.com/azure/storage/blobs/storage-blobs-introduction",
        "https://azure.microsoft.com/pricing/details/storage/blobs/",
    ),
    secrets=Service(
        "key_vault",
        "Azure Key Vault",
        "secrets",
        "Runtime secret references protected by Azure identity and policy.",
        "Managed key and secret store.",
        ("operations", "protected keys", "certificate lifecycle"),
        "https://learn.microsoft.com/azure/key-vault/general/overview",
        "https://azure.microsoft.com/pricing/details/key-vault/",
    ),
    identity=Service(
        "managed_identity_oidc",
        "Managed Identity and GitHub OIDC",
        "identity",
        "Short-lived deployment federation and workload identity without client secrets.",
        "Federated credentials plus managed workload identity.",
        (),
        "https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure",
        "https://azure.microsoft.com/pricing/details/active-directory/",
    ),
    observability=Service(
        "azure_monitor",
        "Azure Monitor and Log Analytics",
        "observability",
        "Container logs, metrics, alerts and diagnostics.",
        "Managed telemetry and query workspace.",
        ("log ingestion", "retention", "queries", "alerts"),
        "https://learn.microsoft.com/azure/azure-monitor/fundamentals/overview",
        "https://azure.microsoft.com/pricing/details/monitor/",
    ),
    regions={"india": "centralindia", "us": "eastus", "europe": "westeurope", "global": "eastus"},
    calculator_url="https://azure.microsoft.com/pricing/calculator/",
    notes=(
        "Container Apps can use public or private registries; ACR is recommended for controlled production delivery.",
        "A Container Apps environment and logging choices contribute separate cost dimensions.",
    ),
)


GCP = Provider(
    key="gcp",
    name="Google Cloud",
    compute=Service(
        "cloud_run",
        "Google Cloud Run",
        "compute",
        "Managed container application platform with HTTPS, revisions and request-based scaling.",
        "Managed service or job; request-based services can scale to zero.",
        ("vCPU time", "memory time", "requests", "minimum instances", "traffic"),
        "https://docs.cloud.google.com/run/docs/overview/what-is-cloud-run",
        "https://cloud.google.com/run/pricing",
    ),
    registry=Service(
        "artifact_registry",
        "Artifact Registry",
        "registry",
        "Provider-native OCI registry used for controlled Cloud Run delivery.",
        "Managed regional or multi-regional registry.",
        ("stored image data", "traffic", "vulnerability analysis"),
        "https://docs.cloud.google.com/artifact-registry/docs/overview",
        "https://cloud.google.com/artifact-registry/pricing",
    ),
    database=Service(
        "cloud_sql_postgresql",
        "Cloud SQL for PostgreSQL",
        "database",
        "Managed PostgreSQL with backups, maintenance and optional high availability.",
        "Provisioned managed database; it is a standing cost driver.",
        ("machine shape", "storage", "backups", "high availability", "IP addresses", "traffic"),
        "https://docs.cloud.google.com/sql/docs/postgres/introduction",
        "https://cloud.google.com/sql/pricing",
    ),
    object_storage=Service(
        "cloud_storage",
        "Cloud Storage",
        "object_storage",
        "Durable object storage for uploads, artifacts and backups.",
        "Managed object storage with multiple location and class choices.",
        ("stored bytes", "storage class", "operations", "retrieval", "traffic"),
        "https://docs.cloud.google.com/storage/docs/introduction",
        "https://cloud.google.com/storage/pricing",
    ),
    secrets=Service(
        "secret_manager",
        "Secret Manager",
        "secrets",
        "Versioned runtime secrets accessed through service identity.",
        "Managed secret store with IAM authorization.",
        ("active secret versions", "access operations", "replication"),
        "https://docs.cloud.google.com/secret-manager/docs/overview",
        "https://cloud.google.com/secret-manager/pricing",
    ),
    identity=Service(
        "service_account_wif",
        "Service Account and Workload Identity Federation",
        "identity",
        "Short-lived GitHub deployment federation and workload service identity.",
        "Federated deployment principal plus per-service account.",
        (),
        "https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-google-cloud-platform",
        "https://cloud.google.com/iam/pricing",
    ),
    observability=Service(
        "cloud_operations",
        "Cloud Logging and Cloud Monitoring",
        "observability",
        "Container logs, metrics, alerts, errors and service diagnostics.",
        "Managed telemetry services integrated with Cloud Run.",
        ("log ingestion", "retention", "custom metrics", "uptime checks"),
        "https://docs.cloud.google.com/stackdriver/docs",
        "https://cloud.google.com/stackdriver/pricing",
    ),
    regions={"india": "asia-south1", "us": "us-central1", "europe": "europe-west1", "global": "us-central1"},
    calculator_url="https://cloud.google.com/products/calculator",
    notes=(
        "The controlled production path mirrors images into Artifact Registry.",
        "Cloud Run filesystems are disposable; persistent files belong in an external data service.",
    ),
)


PROVIDERS = {provider.key: provider for provider in (AWS, AZURE, GCP)}


def catalog_document() -> dict[str, Any]:
    return {
        "catalog_version": CATALOG_VERSION,
        "pricing_policy": (
            "TITAN does not embed dollar estimates. Pricing and free-tier eligibility "
            "must be recalculated with the linked official calculator before approval."
        ),
        "providers": [provider.to_document() for provider in PROVIDERS.values()],
    }

