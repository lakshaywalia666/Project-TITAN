variable "project_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,62}$", var.project_name))
    error_message = "project_name must be a lowercase DNS label."
  }
}
variable "repository_url" {
  type = string
  validation {
    condition     = can(regex("^https://github\\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.repository_url))
    error_message = "repository_url must be a clean GitHub HTTPS repository URL."
  }
}
variable "image" {
  type = string
  validation {
    condition     = can(regex("^ghcr\\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", var.image))
    error_message = "image must be an immutable lowercase GHCR sha256 digest."
  }
}
variable "region" {
  type    = string
  default = "centralindia"
}
variable "container_port" {
  type    = number
  default = 8080
  validation {
    condition     = var.container_port >= 1 && var.container_port <= 65535
    error_message = "container_port must be between 1 and 65535."
  }
}
variable "health_path" {
  type    = string
  default = "/healthz"
  validation {
    condition     = startswith(var.health_path, "/") && !strcontains(var.health_path, "..")
    error_message = "health_path must be a safe absolute path."
  }
}
variable "public_access" {
  type    = bool
  default = true
}
variable "enable_postgresql" {
  type    = bool
  default = false
}
variable "enable_object_storage" {
  type    = bool
  default = false
}
variable "budget_usd_month" {
  type = number
  validation {
    condition     = var.budget_usd_month > 0
    error_message = "budget_usd_month must be a reviewed non-zero ceiling."
  }
}
