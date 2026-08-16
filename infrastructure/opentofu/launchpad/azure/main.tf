terraform {
  required_version = ">= 1.8.0"
}

locals {
  architecture = {
    provider                 = "azure"
    region                   = var.region
    runtime                  = "Azure Container Apps"
    registry                 = "Azure Container Registry"
    database                 = var.enable_postgresql ? "Azure Database for PostgreSQL Flexible Server" : null
    object_storage           = var.enable_object_storage ? "Azure Blob Storage" : null
    secrets                  = "Azure Key Vault"
    identity                 = "GitHub OIDC and managed identities"
    observability            = "Azure Monitor"
    public_access            = var.public_access
    monthly_budget_ceiling   = var.budget_usd_month
    official_cost_calculator = "https://azure.microsoft.com/en-us/pricing/calculator/"
  }
}

output "deployment_contract" {
  description = "Credential-free architecture contract for human review."
  value = {
    implementation_status    = "PROTOTYPE_DRY_RUN"
    cloud_mutation_performed = false
    application = {
      name           = var.project_name
      repository_url = var.repository_url
      image          = var.image
      container_port = var.container_port
      health_path    = var.health_path
    }
    architecture   = local.architecture
    approval_gates = ["official cost calculation", "least-privilege OIDC review", "image signature verification", "human approval before apply"]
  }
}
