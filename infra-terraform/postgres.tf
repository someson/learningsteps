###############################################################################
# PostgreSQL Flexible Server — Tier 2
#
# VNET-integrated (private access) mode: the server gets a NIC in the delegated
# subnet and no public endpoint whatsoever. This is stronger than the VM build,
# where Postgres listened on a private IP and three separate layers (NSG,
# pg_hba.conf, ufw) had to agree to keep it private. Here there is simply no
# public listener to reach.
#
# Note: private access cannot be switched to public access later, or back —
# the mode is fixed at creation time.
###############################################################################

# Ephemeral: generated during apply, handed to write-only arguments, and never
# written to state or plan files. The same apply feeds each value to both the
# server and Key Vault, so they always agree. Later applies generate a new
# value but do not send it, because the *_wo_version counters are unchanged.
#
# special = false keeps the values safe to embed in a postgresql:// URL.
ephemeral "random_password" "postgres_admin" {
  length  = 32
  special = false
}

# The application's own role. Terraform cannot create it — the server is not
# reachable from outside the VNET — so the schema-migration Job creates it
# from this password, which it reads out of Key Vault.
ephemeral "random_password" "postgres_app" {
  length  = 32
  special = false
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                = "${local.name}-pg-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  version    = var.postgres_version
  sku_name   = var.postgres_sku
  storage_mb = var.postgres_storage_mb

  administrator_login               = var.postgres_admin_login
  administrator_password_wo         = ephemeral.random_password.postgres_admin.result
  administrator_password_wo_version = var.postgres_password_version

  # The three settings that together mean "not on the internet".
  public_network_access_enabled = false
  delegated_subnet_id           = azurerm_subnet.db.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id

  backup_retention_days = 7

  tags = local.tags

  # The DNS zone link must exist before the server, or provisioning fails with
  # an unhelpful DNS error.
  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]

  lifecycle {
    ignore_changes = [
      tags["created-on"],
      # zone is assigned by Azure when unspecified; without this, every plan
      # after the first shows a spurious change that would recreate the server.
      zone,
    ]
  }
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "utf8"

  lifecycle {
    # Guard against a rename silently dropping the database with its data.
    prevent_destroy = false # set true once you have real data you care about
  }
}

# --- Server parameters ------------------------------------------------------

# Azure already enforces TLS by default. Setting it explicitly documents the
# intent and survives a change of platform default.
resource "azurerm_postgresql_flexible_server_configuration" "require_ssl" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "ON"
}

# Audit trail for who connected and when, visible in the server logs.
resource "azurerm_postgresql_flexible_server_configuration" "log_connections" {
  name      = "log_connections"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "ON"
}

resource "azurerm_postgresql_flexible_server_configuration" "log_disconnections" {
  name      = "log_disconnections"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "ON"
}

resource "azurerm_postgresql_flexible_server_configuration" "log_checkpoints" {
  name      = "log_checkpoints"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "ON"
}

# Temporarily blocks a source IP after repeated failed logins.
resource "azurerm_postgresql_flexible_server_configuration" "connection_throttle" {
  name      = "connection_throttle.enable"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "ON"
}
