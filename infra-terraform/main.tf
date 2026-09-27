data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

locals {
  name   = "${var.project}-${var.environment}"
  suffix = random_string.suffix.result

  # ACR names allow only alphanumerics, no hyphens, and must be globally unique.
  acr_name = "${var.project}acr${local.suffix}"

  # Key Vault names allow alphanumerics and hyphens, max 24 chars, also global.
  key_vault_name = substr("${var.project}-kv-${local.suffix}", 0, 24)

  tags = merge(var.tags, {
    environment = var.environment
  })
}

resource "azurerm_resource_group" "main" {
  name     = "${local.name}-rg"
  location = var.location
  tags     = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}
