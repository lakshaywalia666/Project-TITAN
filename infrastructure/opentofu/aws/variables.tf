variable "aws_region" {
  type        = string
  description = "One AWS region for the disposable lab"
}

variable "owner" {
  type        = string
  description = "Owner tag used for cost attribution"
}

variable "name" {
  type        = string
  default     = "titan-lab"
  description = "Resource name prefix"
}

variable "vpc_cidr" {
  type    = string
  default = "10.90.0.0/16"
}

variable "public_subnet_cidr" {
  type    = string
  default = "10.90.10.0/24"
}

variable "operator_cidr" {
  type        = string
  description = "Exact trusted public IP in CIDR form for SSH, never 0.0.0.0/0"

  validation {
    condition     = can(cidrhost(var.operator_cidr, 0)) && endswith(var.operator_cidr, "/32")
    error_message = "operator_cidr must be one exact trusted IPv4 address with a /32 suffix."
  }
}

variable "ami_id" {
  type        = string
  default     = ""
  description = "Optional explicit free-tier-eligible Ubuntu AMI; empty uses Canonical's regional SSM parameter"
}

variable "instance_type" {
  type        = string
  default     = "t3.micro"
  description = "Small disposable lab instance; verify current pricing/free-tier eligibility"
}

variable "ssh_public_key" {
  type        = string
  description = "SSH public key material"
  sensitive   = true
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
