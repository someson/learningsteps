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

  # Partial backend configuration: the values live in backend.hcl, which is
  # gitignored because it names your storage account. Initialise with:
  #   terraform init -backend-config=backend.hcl
  backend "azurerm" {
    use_azuread_auth = true
  }
}
