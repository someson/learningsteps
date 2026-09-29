###############################################################################
# Microsoft Entra ID sign-in for the web UI (app/api/entra.py)
#
# An app registration that people sign in to with their own Microsoft work
# or school account. Nobody is created by an administrator: the API creates
# a user record on first sign-in.
#
# No client secret. The API pods authenticate to Entra with their Workload
# Identity token, trusted by the federated credential below, so there is
# nothing to store in Key Vault or rotate.
#
# Who may sign in:
#   entra_sign_in_audience = "AzureADMyOrg"         accounts of the tenant
#       this is deployed in (default; right when your subscription lives in
#       the university's directory)
#   entra_sign_in_audience = "AzureADMultipleOrgs"  accounts of the tenants
#       in entra_allowed_tenant_ids (e.g. the university's tenant while the
#       subscription is in a personal directory)
###############################################################################

data "azuread_client_config" "current" {}

locals {
  entra_multi_tenant = var.entra_sign_in_audience == "AzureADMultipleOrgs"
  # The tenant segment of the authority URL the API redirects to.
  entra_authority_tenant = local.entra_multi_tenant ? "organizations" : data.azurerm_client_config.current.tenant_id
  entra_allowed_tenants = (
    length(var.entra_allowed_tenant_ids) > 0
    ? var.entra_allowed_tenant_ids
    : [data.azurerm_client_config.current.tenant_id]
  )
  entra_redirect_uri = "https://${azurerm_public_ip.ingress.ip_address}/api/auth/entra/callback"
}

# Stable ID for the "Admin" app role (Entra requires a GUID per role).
resource "random_uuid" "admin_role" {}

locals {
  # Who gets the Admin role: the listed object IDs, or else whoever runs
  # Terraform. Everyone else in the allowed tenant(s) signs in as a regular
  # user; the role only adds the administration page (app/api/routers/admin_router.py).
  entra_admin_object_ids = (
    length(var.entra_admin_object_ids) > 0
    ? var.entra_admin_object_ids
    : [data.azuread_client_config.current.object_id]
  )
}

resource "azuread_application" "web" {
  display_name     = "${local.name}-web"
  sign_in_audience = var.entra_sign_in_audience
  owners           = [data.azuread_client_config.current.object_id]

  web {
    redirect_uris = concat([local.entra_redirect_uri], var.entra_extra_redirect_uris)

    # Authorization code flow only; nothing is ever returned in the URL
    # fragment.
    implicit_grant {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = false
    }
  }

  api {
    requested_access_token_version = 2
  }

  # Assigned users get "roles": ["Admin"] in their ID token.
  app_role {
    id                   = random_uuid.admin_role.result
    value                = "Admin"
    display_name         = "Administrator"
    description          = "Can see all users of LearningSteps and block or unblock them."
    allowed_member_types = ["User"]
    enabled              = true
  }

  # Sign-in only: openid + profile, nothing else from Microsoft Graph. These
  # need no admin consent.
  required_resource_access {
    resource_app_id = "00000003-0000-0000-c000-000000000000" # Microsoft Graph

    resource_access {
      id   = "37f7f235-527c-4136-accd-4a02d197296e" # openid
      type = "Scope"
    }
    resource_access {
      id   = "14dad69e-099b-42c9-810b-d002981feec1" # profile
      type = "Scope"
    }
  }
}

resource "azuread_service_principal" "web" {
  client_id = azuread_application.web.client_id
  owners    = [data.azuread_client_config.current.object_id]

  # Everyone in the allowed tenant(s) may sign in; no per-user assignment.
  app_role_assignment_required = false
}

# Lets the API pods present their Workload Identity token as the client
# credential for this app. Same ServiceAccount as the workload identity, so
# no other pod can sign requests as this app.
resource "azuread_application_federated_identity_credential" "web_workload" {
  application_id = azuread_application.web.id
  display_name   = "${local.name}-web-aks"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject        = "system:serviceaccount:${var.k8s_namespace}:${var.k8s_service_account}"
}

resource "azuread_app_role_assignment" "admins" {
  for_each = toset(local.entra_admin_object_ids)

  app_role_id         = azuread_application.web.app_role_ids["Admin"]
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.web.object_id
}
