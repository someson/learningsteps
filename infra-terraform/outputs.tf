output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "acr_name" {
  value = azurerm_container_registry.main.name
}

output "acr_login_server" {
  description = "Image prefix, e.g. <this>/learningsteps:tag"
  value       = azurerm_container_registry.main.login_server
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "aks_get_credentials_command" {
  description = "Points kubectl at the cluster. Local accounts are disabled, so kubectl authenticates through Entra ID via kubelogin (brew install Azure/kubelogin/kubelogin)."
  value       = "az aks get-credentials --resource-group ${azurerm_resource_group.main.name} --name ${azurerm_kubernetes_cluster.main.name} && kubelogin convert-kubeconfig -l azurecli"
}

output "ingress_public_ip" {
  description = "Static IP for Caddy's LoadBalancer Service. Caddy requests a Let's Encrypt certificate for this address."
  value       = azurerm_public_ip.ingress.ip_address
}

output "key_vault_name" {
  value = azurerm_key_vault.main.name
}

output "database_url_secret_name" {
  value = azurerm_key_vault_secret.database_url.name
}

output "database_admin_url_secret_name" {
  description = "Readable only by the migrator identity."
  value       = azurerm_key_vault_secret.database_admin_url.name
}

output "postgres_fqdn" {
  description = "Resolvable only from inside the VNET, via the private DNS zone."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

# --- Values needed by the Kubernetes manifests (phase 3) --------------------

output "workload_identity_client_id" {
  description = "Goes in the ServiceAccount annotation azure.workload.identity/client-id."
  value       = azurerm_user_assigned_identity.workload.client_id
}

output "migrator_identity_client_id" {
  description = "Goes in the migration Job's ServiceAccount annotation azure.workload.identity/client-id."
  value       = azurerm_user_assigned_identity.migrator.client_id
}

output "k8s_migrator_service_account" {
  value = var.k8s_migrator_service_account
}

output "ingress_public_ip_name" {
  description = "For the Service annotation service.beta.kubernetes.io/azure-pip-name."
  value       = azurerm_public_ip.ingress.name
}

output "db_subnet_cidr" {
  description = "Egress target for the API and migration NetworkPolicies."
  value       = var.subnet_db_prefix
}

output "ingress_resource_group" {
  description = "For the Service annotation service.beta.kubernetes.io/azure-load-balancer-resource-group."
  value       = azurerm_resource_group.main.name
}

output "tenant_id" {
  value = data.azurerm_client_config.current.tenant_id
}

output "k8s_namespace" {
  value = var.k8s_namespace
}

output "k8s_service_account" {
  value = var.k8s_service_account
}

output "entra_client_id" {
  description = "Application (client) ID of the web app registration (entra.tf)."
  value       = azuread_application.web.client_id
}

output "entra_authority_tenant" {
  description = "Tenant segment of the sign-in URL: a tenant ID, or \"organizations\" for a multi-tenant app."
  value       = local.entra_authority_tenant
}

output "entra_allowed_tenants" {
  description = "Comma-separated tenant IDs whose accounts may sign in."
  value       = join(",", local.entra_allowed_tenants)
}

# --- Values needed by the GitHub Actions workflow (phase 4) -----------------

output "github_actions_client_id" {
  description = "Set as the AZURE_CLIENT_ID repository variable (not a secret — it is an identifier, not a credential)."
  value       = azurerm_user_assigned_identity.github.client_id
}

output "subscription_id" {
  value = data.azurerm_client_config.current.subscription_id
}

output "github_repository_variables" {
  description = "Repository variables to set under Settings > Secrets and variables > Actions > Variables."
  value = {
    AZURE_CLIENT_ID       = azurerm_user_assigned_identity.github.client_id
    AZURE_TENANT_ID       = data.azurerm_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID = data.azurerm_client_config.current.subscription_id
    ACR_LOGIN_SERVER      = azurerm_container_registry.main.login_server
    AKS_CLUSTER_NAME      = azurerm_kubernetes_cluster.main.name
    AKS_RESOURCE_GROUP    = azurerm_resource_group.main.name
    ENTRA_CLIENT_ID       = azuread_application.web.client_id
    ENTRA_TENANT          = local.entra_authority_tenant
    ENTRA_ALLOWED_TENANTS = join(",", local.entra_allowed_tenants)
  }
}

# Deliberately NOT output: the database passwords and connection strings. They
# are write-only (never in state) and live only in Key Vault.
