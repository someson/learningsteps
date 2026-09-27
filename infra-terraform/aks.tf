###############################################################################
# Azure Kubernetes Service
###############################################################################

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.name}-law"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

resource "azurerm_kubernetes_cluster" "main" {
  name                = "${local.name}-aks"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  dns_prefix          = "${local.name}-${local.suffix}"

  # Pinning nothing here means AKS picks a current default version. Pin
  # kubernetes_version explicitly once you need reproducible upgrades.
  sku_tier = "Free"

  # Patch releases and node OS images carry most CVE fixes. Letting AKS apply
  # them keeps the cluster from silently ageing between terraform runs.
  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"

  # Required from azurerm v5. "Manual" means node pools are exactly what this
  # configuration declares; "Auto" hands provisioning to AKS node autoprovision.
  node_provisioning_profile {
    mode = "Manual"
  }

  default_node_pool {
    name                 = "system"
    vm_size              = var.aks_node_size
    vnet_subnet_id       = azurerm_subnet.aks.id
    auto_scaling_enabled = true
    node_count           = var.aks_node_count
    min_count            = var.aks_node_min_count
    max_count            = var.aks_node_max_count
    os_disk_size_gb      = 64

    # Explicit, and load-bearing for the v6 sizes. The non-"d" v6 SKUs
    # (D2s_v6) have NO local temp disk and report a cache size of 0. AKS
    # otherwise prefers an Ephemeral OS disk whenever it thinks one fits,
    # and asking for one on a 0-byte cache fails with
    # VMCannotFitEphemeralOSDisk. Stating Managed removes the guesswork.
    # If you later switch to a "d" size (D2ds_v6) and want Ephemeral, note
    # that changing this needs temporary_name_for_rotation set.
    os_disk_type = "Managed"

    upgrade_settings {
      max_surge = "33%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  # Entra ID authentication + Azure RBAC for Kubernetes authorisation.
  #
  # Without this block the namespace-scoped "RBAC Writer" assignment in
  # identity.tf is inert, and "Cluster User Role" on a cluster with local
  # accounts hands out a certificate-based kubeconfig that is effectively
  # cluster-admin. With it, every kubectl call carries an Entra token and is
  # checked against Azure role assignments.
  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }

  # No static admin certificate. `az aks get-credentials --admin` stops
  # working; all access is through Entra identities that can be revoked.
  local_account_disabled = true

  # The API server stays public (a private cluster needs a jump host or VPN),
  # but only admin_ip_ranges may connect. CI reaches the cluster through
  # `az aks command invoke`, which goes via ARM and needs no API-server route.
  dynamic "api_server_access_profile" {
    for_each = var.restrict_aks_api ? [1] : []
    content {
      authorized_ip_ranges = var.admin_ip_ranges
    }
  }

  # Workload Identity: pods exchange a projected Kubernetes service-account
  # token for an Entra ID token. No client secret is ever stored in the
  # cluster. oidc_issuer_enabled defaults to true in azurerm v5, but it is
  # stated here because workload_identity_enabled is meaningless without it.
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  # Installs the Secrets Store CSI driver plus the Azure Key Vault provider,
  # which is what mounts Key Vault secrets into pods as files.
  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "2m"
  }

  network_profile {
    network_plugin = "azure"

    # Overlay mode: pods draw addresses from pod_cidr instead of consuming
    # real VNET addresses. Without it, a /22 node subnet is exhausted by a few
    # dozen pods, because every pod would take a VNET IP.
    network_plugin_mode = "overlay"
    network_policy      = "calico"

    service_cidr   = var.aks_service_cidr
    dns_service_ip = var.aks_dns_service_ip
    pod_cidr       = var.aks_pod_cidr

    load_balancer_sku = "standard"
    outbound_type     = "loadBalancer"
  }

  oms_agent {
    log_analytics_workspace_id      = azurerm_log_analytics_workspace.main.id
    msi_auth_for_monitoring_enabled = true
  }

  tags = local.tags

  # The ingress IP is held by a LoadBalancer Service inside the cluster. It
  # can only be deleted once the cluster (and that Service) is gone, so the
  # cluster must be destroyed first.
  depends_on = [azurerm_public_ip.ingress]

  lifecycle {
    ignore_changes = [
      tags["created-on"],
      # The autoscaler owns this value at runtime; without the exception every
      # plan would try to reset it to var.aks_node_count.
      default_node_pool[0].node_count,
    ]
  }
}

# --- Role assignments -------------------------------------------------------

# Lets the cluster's kubelet identity pull images from ACR without an
# imagePullSecret. This replaces the old "az aks update --attach-acr".
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
  skip_service_principal_aad_check = true
}

# With local accounts disabled, whoever runs Terraform needs an Azure role to
# use kubectl at all.
resource "azurerm_role_assignment" "operator_aks_admin" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = data.azurerm_client_config.current.object_id
}

# The cloud provider inside AKS attaches the ingress IP to its load balancer.
# The IP lives outside the node resource group, so the cluster identity needs
# explicit rights on it. Scoped to the one IP rather than the resource group.
resource "azurerm_role_assignment" "aks_ingress_ip" {
  scope                = azurerm_public_ip.ingress.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.main.identity[0].principal_id
}
