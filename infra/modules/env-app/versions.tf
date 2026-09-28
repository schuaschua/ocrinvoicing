terraform {
  required_version = ">= 1.9, < 2.0"

  # azapi, random, time and modtm are used by the AVM modules this module calls.
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.81.0, < 5.0.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = ">= 2.13.0, < 3.0.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.9.1, < 4.0.0"
    }
    time = {
      source  = "hashicorp/time"
      version = ">= 0.14.2, < 1.0.0"
    }
    modtm = {
      source  = "Azure/modtm"
      version = ">= 0.4.0, < 1.0.0"
    }
  }
}
