provider "azurerm" {
  # azurerm v5 registers no resource providers by default — v4 and earlier
  # silently registered ~60 of them. "extended" covers the services used here
  # (AKS, PostgreSQL, Container Registry, Key Vault, Managed Identity); the
  # explicit list below guarantees the ones this configuration cannot work
  # without, in case the "extended" set changes.
  #
  # If your account lacks subscription-level registration rights, set this to
  # "none" and have an owner register the providers once, out of band.
  resource_provider_registrations = "extended"

  resource_providers_to_register = [
    "Microsoft.ContainerService",
    "Microsoft.ContainerRegistry",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.KeyVault",
    "Microsoft.ManagedIdentity",
    "Microsoft.OperationalInsights",
  ]

  features {
    key_vault {
      # Key Vault soft-delete means a destroyed vault keeps its name reserved.
      # Purging on destroy lets `terraform destroy` + `apply` actually round
      # trip, which is one of the project's success criteria.
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }

    resource_group {
      # Fail loudly if something outside Terraform put a resource in the group,
      # rather than silently deleting it.
      prevent_deletion_if_contains_resources = true
    }
  }
}
