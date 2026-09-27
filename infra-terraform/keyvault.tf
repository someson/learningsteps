###############################################################################
# Key Vault
#
# RBAC authorisation rather than the legacy access-policy model: permissions
# become normal Azure role assignments, visible alongside every other grant in
# the subscription instead of in a per-vault list. In azurerm v5 the
# rbac_authorization_enabled property is Required (it was optional, and named
# enable_rbac_authorization, in v4).
#
# Two secrets, two readers, no overlap:
#   database-url        app role     → read by the API pods
#   database-admin-url  server admin → read only by the schema-migration Job
###############################################################################

resource "azurerm_key_vault" "main" {
  name                = local.key_vault_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  rbac_authorization_enabled = true

  # Soft delete is mandatory and cannot be disabled. Purge protection is left
  # off so `terraform destroy` genuinely removes the vault — with it enabled
  # the name stays reserved for 90 days, which breaks the destroy/apply
  # recovery criterion. Turn it ON for anything real.
  soft_delete_retention_days = 7
  #trivy:ignore:AZU-0016 -- deliberate, see above
  purge_protection_enabled = false

  # Data plane reachable only from the admin's IP (to write secrets during
  # apply) and from the AKS subnet via its service endpoint (CSI driver).
  network_acls {
    default_action             = "Deny"
    bypass                     = "AzureServices"
    ip_rules                   = var.admin_ip_ranges
    virtual_network_subnet_ids = [azurerm_subnet.aks.id]
  }

  tags = local.tags
}

# The identity running Terraform needs data-plane rights to write the secrets
# below. RBAC on Key Vault is data-plane, so control-plane Owner is not enough.
resource "azurerm_role_assignment" "tf_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

locals {
  app_db_user = "learningsteps"

  # sslmode=require is explicit because the server enforces TLS; the driver's
  # own default (prefer) would silently accept a downgrade if the server ever
  # stopped requiring it.
  pg_dsn_template = "postgresql://%s:%s@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${var.database_name}?sslmode=require"
}

# value_wo: the connection string goes to Key Vault but never into state.
resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  key_vault_id = azurerm_key_vault.main.id

  value_wo         = format(local.pg_dsn_template, local.app_db_user, ephemeral.random_password.postgres_app.result)
  value_wo_version = var.postgres_password_version

  content_type = "connection-string"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.tf_kv_admin]
}

resource "azurerm_key_vault_secret" "database_admin_url" {
  name         = "database-admin-url"
  key_vault_id = azurerm_key_vault.main.id

  value_wo         = format(local.pg_dsn_template, var.postgres_admin_login, ephemeral.random_password.postgres_admin.result)
  value_wo_version = var.postgres_password_version

  content_type = "connection-string"
  tags         = local.tags

  depends_on = [azurerm_role_assignment.tf_kv_admin]
}

# "Secrets User" can read secret values but cannot list, set, or delete them.
# Scoped to individual secrets, not the vault: the API pods cannot read the
# admin connection string even though it sits in the same vault.
resource "azurerm_role_assignment" "workload_kv_reader" {
  scope                = azurerm_key_vault_secret.database_url.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
}

# The migrator needs both: the admin DSN to create the app role, and the app
# DSN to know which password to give it.
resource "azurerm_role_assignment" "migrator_kv_reader" {
  for_each = {
    admin = azurerm_key_vault_secret.database_admin_url.resource_versionless_id
    app   = azurerm_key_vault_secret.database_url.resource_versionless_id
  }

  scope                = each.value
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.migrator.principal_id
}
