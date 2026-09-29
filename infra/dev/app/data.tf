# Reads this environment's foundation outputs (AD-17 step 4): identities, storage,
# Key Vault and Application Insights (terraform.md rule 7).
data "terraform_remote_state" "foundation" {
  backend = "azurerm"

  config = {
    resource_group_name  = "rg-tfstate-sea"
    storage_account_name = "stdjtfstatesea"
    container_name       = "ocrinvoicing-dev"
    key                  = "foundation.tfstate"
    use_azuread_auth     = true
  }
}
