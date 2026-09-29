variable "project" {
  type        = string
  default     = "learningsteps"
  description = "Base name used to derive resource names."

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.project))
    error_message = "project must be 3-16 lowercase alphanumeric characters starting with a letter (ACR and storage names are restrictive)."
  }
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Environment suffix (dev, staging, prod)."
}

variable "location" {
  type        = string
  default     = "swedencentral"
  description = "Azure region for all resources."
}

# --- Networking -------------------------------------------------------------

variable "vnet_address_space" {
  type        = string
  default     = "10.20.0.0/16"
  description = "VNET address space."
}

variable "subnet_aks_prefix" {
  type        = string
  default     = "10.20.0.0/22"
  description = "Subnet for AKS nodes. /22 gives ~1000 usable IPs for node scaling."
}

variable "subnet_db_prefix" {
  type        = string
  default     = "10.20.4.0/24"
  description = "Subnet delegated to PostgreSQL Flexible Server. Must hold no other resources."
}

variable "aks_service_cidr" {
  type        = string
  default     = "10.30.0.0/16"
  description = "Kubernetes service CIDR. Must NOT overlap the VNET."
}

variable "aks_dns_service_ip" {
  type        = string
  default     = "10.30.0.10"
  description = "kube-dns address. Must sit inside aks_service_cidr."
}

variable "aks_pod_cidr" {
  type        = string
  default     = "10.244.0.0/16"
  description = "Pod CIDR for CNI overlay mode. Must NOT overlap the VNET or service CIDR."
}

# --- AKS --------------------------------------------------------------------

variable "aks_node_count" {
  type        = number
  default     = 2
  description = "Initial node count for the system node pool."
}

variable "aks_node_size" {
  type        = string
  default     = "Standard_D2s_v6"
  description = "VM size for AKS nodes. D2s_v6 = 2 vCPU / 8 GiB, no local temp disk (see os_disk_type in aks.tf)."
}

variable "aks_node_min_count" {
  type        = number
  default     = 2
  description = "Minimum nodes when the cluster autoscaler is active."
}

variable "aks_node_max_count" {
  type        = number
  default     = 4
  description = "Maximum nodes when the cluster autoscaler is active."
}

# --- PostgreSQL -------------------------------------------------------------

variable "postgres_version" {
  type        = string
  default     = "16"
  description = "PostgreSQL major version."
}

variable "postgres_sku" {
  type        = string
  default     = "B_Standard_B1ms"
  description = "Flexible Server SKU (tier_name pattern). B_ = burstable, cheapest tier."
}

variable "postgres_storage_mb" {
  type        = number
  default     = 32768
  description = "Storage in MB. Can only ever be scaled UP — shrinking forces replacement."
}

variable "postgres_admin_login" {
  type        = string
  default     = "lsadmin"
  description = "Server administrator login. Cannot be 'azure_superuser', 'admin', 'root' or similar reserved names."
}

variable "database_name" {
  type        = string
  default     = "learning_journal"
  description = "Application database name. Must match what the app expects."
}

# --- GitHub Actions OIDC ----------------------------------------------------

variable "github_repository" {
  type        = string
  description = "GitHub repo as 'owner/name'. Used to scope the federated credential so ONLY this repo can authenticate to Azure."

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository must be in 'owner/name' form."
  }
}

# GitHub signs OIDC tokens with an immutable subject that embeds numeric IDs
# (repo:owner@<owner_id>/name@<repo_id>:...), so a renamed or re-registered
# repo with the same name cannot match. Read the exact prefix with:
#   gh api repos/<owner>/<name>/actions/oidc/customization/sub --jq .sub_claim_prefix
# null = legacy name-based subject (repo:owner/name), for repos that opted out.
variable "github_oidc_subject_prefix" {
  type        = string
  default     = null
  description = "OIDC sub claim prefix, e.g. 'repo:owner@123/name@456'. null falls back to 'repo:<github_repository>'."

  validation {
    condition     = var.github_oidc_subject_prefix == null || can(regex("^repo:[^/]+/[^/:]+$", var.github_oidc_subject_prefix))
    error_message = "github_oidc_subject_prefix must look like 'repo:owner@123/name@456'."
  }
}

variable "github_environment" {
  type        = string
  default     = "production"
  description = "GitHub Actions environment allowed to deploy. The federated credential matches this exact environment; restrict its deployment branches to main on GitHub."
}

# --- Kubernetes identity binding -------------------------------------------

variable "k8s_namespace" {
  type        = string
  default     = "learningsteps"
  description = "Namespace the app runs in. Baked into the federated credential subject."
}

variable "k8s_service_account" {
  type        = string
  default     = "learningsteps-sa"
  description = "Kubernetes ServiceAccount name bound to the workload identity."
}

variable "k8s_migrator_service_account" {
  type        = string
  default     = "learningsteps-migrator"
  description = "ServiceAccount of the schema-migration Job. The only principal that can read the admin connection string."
}

# --- Access control ---------------------------------------------------------

variable "admin_ip_ranges" {
  type        = list(string)
  description = "CIDRs allowed to reach the Key Vault data plane and the AKS API server, e.g. [\"93.201.27.36/32\"]. The machine running terraform apply must be in this list, or writing secrets fails with 403."

  validation {
    condition     = length(var.admin_ip_ranges) > 0 && alltrue([for c in var.admin_ip_ranges : can(cidrhost(c, 0))])
    error_message = "admin_ip_ranges must be a non-empty list of CIDRs."
  }
}

variable "restrict_aks_api" {
  type        = bool
  default     = true
  description = "Limit the AKS API server to admin_ip_ranges. GitHub-hosted runners have no fixed IPs, so CI must then deploy via `az aks command invoke` (which goes through ARM, not the API server). Set false only if that route does not work for you."
}

# --- Secret rotation --------------------------------------------------------

variable "postgres_password_version" {
  type        = number
  default     = 1
  description = "Bump to rotate the Postgres admin and app passwords. They are write-only and never stored in state, so Terraform cannot detect drift — this counter is the rotation trigger."
}

variable "tags" {
  type = map(string)
  default = {
    project    = "learningsteps"
    managed_by = "terraform"
  }
  description = "Tags applied to every resource."
}
