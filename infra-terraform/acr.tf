resource "azurerm_container_registry" "main" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Standard"

  # The admin account is a shared username/password with push rights. Leaving
  # it off forces every pull and push through Entra ID identities that can be
  # scoped and audited — AKS's kubelet identity for pulls, the GitHub Actions
  # identity for pushes. Neither needs a stored credential.
  admin_enabled = false

  tags = local.tags
}
