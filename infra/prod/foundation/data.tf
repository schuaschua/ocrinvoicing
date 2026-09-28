data "azurerm_client_config" "current" {}

# Reads the shared stack's outputs (departure from terraform.md rule 3, spine AD-17).
data "terraform_remote_state" "shared" {
  backend = "azurerm"

  config = {
    resource_group_name  = "babaloo-sea-lng-rg-22"
    storage_account_name = "babaloosealngst21"
    container_name       = "shared"
    key                  = "foundation.tfstate"
    use_azuread_auth     = true
  }
}
