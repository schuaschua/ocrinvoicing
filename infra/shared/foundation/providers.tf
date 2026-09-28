# Subscription and tenant come from ARM_SUBSCRIPTION_ID / ARM_TENANT_ID (azure.md rule 6).
provider "azurerm" {
  resource_provider_registrations = "none"
  storage_use_azuread             = true

  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
      recover_soft_deleted_secrets    = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
}

provider "azapi" {}
