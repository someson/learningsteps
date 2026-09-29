###############################################################################
# Managed identities and federated credentials
#
# Two separate identities, each with the narrowest useful role set:
#
#   workload — assumed by the application pods; reads one Key Vault secret
#   migrator — assumed by the schema-migration Job; reads the admin DSN
#   github   — assumed by GitHub Actions; pushes images and deploys to AKS
#
# Neither has a client secret. Both use OpenID Connect federation: the caller
# presents a token issued by a trusted issuer (the AKS OIDC endpoint, or
# GitHub's), and Entra ID exchanges it for an Azure token provided the token's
# subject matches exactly. Nothing long-lived is stored anywhere.
###############################################################################

# --- Pod identity -----------------------------------------------------------

resource "azurerm_user_assigned_identity" "workload" {
  name                = "${local.name}-workload-id"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# Binds the identity to ONE ServiceAccount in ONE namespace. The subject format
# system:serviceaccount:<namespace>:<name> is fixed by Kubernetes; a pod using
# any other ServiceAccount gets no token, which is the point.
resource "azurerm_federated_identity_credential" "workload" {
  name                      = "${local.name}-workload-federation"
  user_assigned_identity_id = azurerm_user_assigned_identity.workload.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject                   = "system:serviceaccount:${var.k8s_namespace}:${var.k8s_service_account}"
}

# --- Schema-migration identity ---------------------------------------------

# Separate from the API pods so that a compromised API pod cannot obtain the
# server-admin connection string. Only the migration Job's ServiceAccount can
# assume this identity.
resource "azurerm_user_assigned_identity" "migrator" {
  name                = "${local.name}-migrator-id"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

resource "azurerm_federated_identity_credential" "migrator" {
  name                      = "${local.name}-migrator-federation"
  user_assigned_identity_id = azurerm_user_assigned_identity.migrator.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject                   = "system:serviceaccount:${var.k8s_namespace}:${var.k8s_migrator_service_account}"
}

# --- GitHub Actions identity ------------------------------------------------

resource "azurerm_user_assigned_identity" "github" {
  name                = "${local.name}-github-id"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags

  # "created-on" is stamped by an organisation-level Azure Policy; without
  # this, every plan would try to remove it and the policy would add it back.
  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# Scoped to a GitHub *environment*, not a branch. A job that declares
# `environment: production` receives an OIDC token with the subject below;
# any other job — a feature branch, a PR, or a job on main that skips the
# environment — presents a different subject and is refused. That makes the
# environment's protection rules (deployment branches limited to main,
# optional required reviewers) the single gate in front of Azure.
#
# The environment's "deployment branches" rule MUST be restricted to the
# deploy branch on GitHub; otherwise any branch could declare the
# environment and obtain this token. See NEXT_SESSION.md / README.
resource "azurerm_federated_identity_credential" "github_environment" {
  name                      = "${local.name}-github-env-${var.github_environment}"
  user_assigned_identity_id = azurerm_user_assigned_identity.github.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${var.github_repository}:environment:${var.github_environment}"
}

# No credential for pull_request events. This identity can push images and
# deploy, and a same-repo PR branch would otherwise get exactly those rights.
# Build, test and scan jobs on PRs need no Azure access at all.

resource "azurerm_role_assignment" "github_acr_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

# "Cluster User" grants only the ability to fetch a kubeconfig. What the
# pipeline may then DO inside the cluster is decided by the Azure RBAC
# assignment below, enforced because the cluster has azure_rbac_enabled.
resource "azurerm_role_assignment" "github_aks_user" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

# The API server accepts only admin_ip_ranges and GitHub runners have no fixed
# IP, so CI deploys through `az aks command invoke`: Azure runs kubectl in a
# pod inside the cluster, authenticated with the caller's Entra token (so the
# namespace-scoped RBAC Writer below still limits what it can change). The
# only built-in role with runCommand is "Cluster Admin Role", which also
# hands out admin credentials — hence this two-action custom role.
resource "azurerm_role_definition" "aks_run_command" {
  name              = "${local.name}-aks-run-command"
  scope             = azurerm_kubernetes_cluster.main.id
  description       = "Run kubectl through az aks command invoke; nothing else."
  assignable_scopes = [azurerm_kubernetes_cluster.main.id]

  permissions {
    actions = [
      "Microsoft.ContainerService/managedClusters/runCommand/action",
      "Microsoft.ContainerService/managedClusters/commandResults/read",
    ]
  }
}

resource "azurerm_role_assignment" "github_aks_run_command" {
  scope              = azurerm_kubernetes_cluster.main.id
  role_definition_id = azurerm_role_definition.aks_run_command.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.github.principal_id
}

# Lets the pipeline apply manifests via Entra-authenticated kubectl.
# Narrower than "Cluster Admin", which would also permit cluster-wide RBAC
# changes and node access.
resource "azurerm_role_assignment" "github_aks_rbac_writer" {
  scope                = "${azurerm_kubernetes_cluster.main.id}/namespaces/${var.k8s_namespace}"
  role_definition_name = "Azure Kubernetes Service RBAC Writer"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}
