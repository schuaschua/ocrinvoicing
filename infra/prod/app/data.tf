# Reads this environment's foundation outputs (AD-17 step 4): identities, storage,
# Key Vault and Application Insights (terraform.md rule 7).
data "terraform_remote_state" "foundation" {
  backend = "azurerm"

  config = {
    resource_group_name  = "babaloo-sea-lng-rg-22"
    storage_account_name = "babaloosealngst21"
    container_name       = "prod"
    key                  = "foundation.tfstate"
    use_azuread_auth     = true
  }
}
