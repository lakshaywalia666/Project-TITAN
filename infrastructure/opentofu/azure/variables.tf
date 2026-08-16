variable "subscription_id" {
  type = string
}

variable "location" {
  type = string
}

variable "owner" {
  type = string
}

variable "name" {
  type    = string
  default = "titan-lab"
}

variable "operator_cidr" {
  type = string
  validation {
    condition     = can(cidrhost(var.operator_cidr, 0)) && endswith(var.operator_cidr, "/32")
    error_message = "operator_cidr must be one exact trusted IPv4 address with a /32 suffix."
  }
}

variable "ssh_public_key" {
  type      = string
  sensitive = true
}

variable "vm_size" {
  type    = string
  default = "Standard_B1s"
}

variable "titan_image" {
  type        = string
  description = "Public GHCR TITAN image pinned to an immutable sha256 digest"

  validation {
    condition     = can(regex("^ghcr\\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$", var.titan_image))
    error_message = "titan_image must be a public ghcr.io image pinned with @sha256:<64 lowercase hex characters>."
  }
}

variable "expires_at" {
  type        = string
  description = "Operator-reviewed UTC destruction deadline recorded on every resource"

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", var.expires_at))
    error_message = "expires_at must use UTC RFC3339 form, for example 2026-08-16T18:00:00Z."
  }
}
