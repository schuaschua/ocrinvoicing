terraform {
  required_version = "1.16.4"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.81.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "2.13.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
    time = {
      source  = "hashicorp/time"
      version = "0.14.2"
    }
    modtm = {
      source  = "Azure/modtm"
      version = "0.4.0"
    }
  }

  # State storage from infra/bootstrap/state-backend.sh; Entra auth only.
  backend "azurerm" {
    resource_group_name  = "babaloo-sea-lng-rg-22"
    storage_account_name = "babaloosealngst21"
    container_name       = "prod"
    key                  = "foundation.tfstate"
    use_azuread_auth     = true
  }
}
