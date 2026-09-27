###############################################################################
# Networking
#
# Same two-tier shape as the hand-built deployment, expressed as code:
#   snet-aks — holds the AKS nodes, reaches the internet via the load balancer
#   snet-db  — delegated to PostgreSQL Flexible Server, no public endpoint
#
# The primary isolation mechanism differs from the VM version: with VNET
# integration the Flexible Server has no public IP at all and is resolvable
# only through a private DNS zone linked to this VNET. The NSG on snet-db
# (5432 from snet-aks only, deny everything else) is defence in depth on top
# of that, not the main control.
###############################################################################

resource "azurerm_virtual_network" "main" {
  name                = "${local.name}-vnet"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = [var.vnet_address_space]
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_aks_prefix]

  # Key Vault only accepts traffic from admin_ip_ranges and this subnet. The
  # service endpoint is what lets the CSI driver on the nodes match the
  # subnet rule; without it their traffic arrives from the load balancer's
  # public outbound IP and is refused.
  service_endpoint {
    service = "Microsoft.KeyVault"
  }
}

resource "azurerm_subnet" "db" {
  name                 = "snet-db"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_db_prefix]

  # Azure adds this endpoint itself when the Flexible Server is created
  # (backups go to Storage). Declared so the code matches reality.
  service_endpoint {
    service = "Microsoft.Storage"
  }

  # Delegation hands the subnet to the PostgreSQL service, which injects the
  # server's NIC here. Azure forbids any other resource in a delegated subnet.
  delegation {
    name = "postgresql-flexible-server"

    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# --- NSGs -------------------------------------------------------------------

resource "azurerm_network_security_group" "aks" {
  name                = "${local.name}-nsg-aks"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# Deliberately minimal: one allow rule for the ingress ports, Azure's default
# rules for everything else. Egress restriction belongs in Kubernetes
# NetworkPolicy (enabled on the cluster) rather than at the NSG layer.

# AKS writes rules for LoadBalancer Services into the NSG it owns in the node
# resource group, not into this one — and traffic must pass both. Without
# this rule the Caddy ingress is unreachable, and Let's Encrypt's http-01
# renewal (every few days for a 6-day IP certificate) fails silently.
# Port 80 is not a redirect convenience here; it is part of the TLS design.
resource "azurerm_network_security_rule" "aks_allow_ingress_http" {
  name                        = "Allow-Ingress-HTTP-HTTPS"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_ranges     = ["80", "443"]
  source_address_prefix       = "Internet"
  # The AKS load balancer uses floating IP: packets reach the nodes with the
  # PUBLIC frontend address as destination, not a node's private IP. A rule
  # scoped to the subnet CIDR never matches (verified: ACME timed out).
  destination_address_prefix  = azurerm_public_ip.ingress.ip_address
  resource_group_name         = azurerm_resource_group.main.name
  network_security_group_name = azurerm_network_security_group.aks.name
}

resource "azurerm_subnet_network_security_group_association" "aks" {
  subnet_id                 = azurerm_subnet.aks.id
  network_security_group_id = azurerm_network_security_group.aks.id
}

resource "azurerm_network_security_group" "db" {
  name                = "${local.name}-nsg-db"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

resource "azurerm_network_security_rule" "db_allow_postgres_from_aks" {
  name                        = "Allow-Postgres-From-AKS"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "5432"
  source_address_prefix       = var.subnet_aks_prefix
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.main.name
  network_security_group_name = azurerm_network_security_group.db.name
}

resource "azurerm_network_security_rule" "db_deny_all_inbound" {
  name                        = "Deny-All-Inbound"
  priority                    = 4096
  direction                   = "Inbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.main.name
  network_security_group_name = azurerm_network_security_group.db.name
}

resource "azurerm_subnet_network_security_group_association" "db" {
  subnet_id                 = azurerm_subnet.db.id
  network_security_group_id = azurerm_network_security_group.db.id
}

# --- Private DNS for PostgreSQL --------------------------------------------

# Without this zone the server's FQDN resolves to nothing from inside the VNET.
# The zone name MUST end in .postgres.database.azure.com — the service rejects
# anything else.
resource "azurerm_private_dns_zone" "postgres" {
  name                = "${local.name}-${local.suffix}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                 = "${local.name}-postgres-link"
  private_dns_zone_id  = azurerm_private_dns_zone.postgres.id
  virtual_network_id   = azurerm_virtual_network.main.id
  registration_enabled = false
  tags                 = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# --- Ingress public IP ------------------------------------------------------

# Static, Standard SKU, and owned by Terraform rather than by the Kubernetes
# Service. Caddy obtains a Let's Encrypt certificate for this exact address,
# so it must not change when the Service is recreated. It still changes on
# destroy/apply; Caddy then simply requests a new certificate.
resource "azurerm_public_ip" "ingress" {
  name                = "${local.name}-ingress-pip"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}
