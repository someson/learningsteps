###############################################################################
# bootstrap/main.tf — creates the Azure Storage account that holds the remote
# state for the MAIN configuration in ../
#
# Chicken-and-egg problem: remote state needs a storage account, but a storage
# account is infrastructure. This tiny root module solves it by using LOCAL
# state for itself. Its state file describes only a storage account, contains
# no secrets, and is re-creatable, so keeping it local is acceptable — unlike
# the main state, which will hold the database password in cleartext.
#
# Run this ONCE, before anything in ../:
#   cd bootstrap && terraform init && terraform apply -var-file=../terraform.tfvars
#   # then copy the output into ../backend.hcl
###############################################################################

terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.5"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  # v5 registers NO resource providers by default (v4 registered ~60).
  # "core" covers Compute, Networking and Storage — enough for this module.
  resource_provider_registrations = "core"
  features {}
}

variable "location" {
  type        = string
  default     = "swedencentral"
  description = "Azure region for the state storage account."
}

variable "admin_ip_ranges" {
  type        = list(string)
  description = "CIDRs allowed to reach the state blobs, e.g. [\"93.201.27.36/32\"]. Same value as in ../terraform.tfvars."
}

variable "state_resource_group_name" {
  type        = string
  default     = "learningsteps-tfstate-rg"
  description = "Resource group holding the Terraform state storage account."
}

# Storage account names are globally unique, 3-24 chars, lowercase alphanumeric.
data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_resource_group" "tfstate" {
  name     = var.state_resource_group_name
  location = var.location

  # "created-on" is stamped by an organisation-level Azure Policy.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

resource "azurerm_storage_account" "tfstate" {
  name                = "lsstate${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.tfstate.name
  location            = azurerm_resource_group.tfstate.location

  account_tier             = "Standard"
  account_replication_type = "LRS"

  # The state file contains secrets in cleartext. Lock the account down.
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  # Shared account keys are disabled: the main configuration's backend sets
  # use_azuread_auth = true, so access goes through Entra ID identities that
  # can be revoked individually. A shared key cannot be scoped or revoked
  # without rotating it for everyone — and it would be flagged by the IaC
  # scanners added in the DevSecOps phase.
  shared_access_key_enabled = false

  # Blob data plane reachable only from the admin's IP. Storage rejects /31
  # and /32 CIDRs in ip_rules, so single addresses are passed bare.
  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
    ip_rules       = [for c in var.admin_ip_ranges : trimsuffix(c, "/32")]
  }

  blob_properties {
    # Lets you recover state after a bad apply or an accidental delete.
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  # "created-on" is stamped by an organisation-level Azure Policy.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

resource "azurerm_storage_container" "tfstate" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.tfstate.id
  container_access_type = "private"
}

# With shared keys disabled, reading and writing state requires a data-plane
# role. Owner/Contributor on the subscription is NOT sufficient — those are
# control-plane roles and grant no access to blob contents.
#
# Role assignments take a minute or two to propagate. If the first
# `terraform init` in ../ fails with a 403, wait and retry.
resource "azurerm_role_assignment" "tfstate_blob_contributor" {
  scope                = azurerm_storage_account.tfstate.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

output "backend_hcl" {
  description = "Paste this into ../backend.hcl"
  value       = <<-EOT
    resource_group_name  = "${azurerm_resource_group.tfstate.name}"
    storage_account_name = "${azurerm_storage_account.tfstate.name}"
    container_name       = "${azurerm_storage_container.tfstate.name}"
    key                  = "learningsteps.tfstate"
  EOT
}
