# Offline root test for prod/foundation: every provider and the shared remote state
# are mocked, nothing reaches Azure. Detailed resource values are tested in
# infra/modules/env-foundation/tests.

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      subscription_id = "00000000-0000-0000-0000-000000000000"
      tenant_id       = "11111111-1111-1111-1111-111111111111"
      object_id       = "22222222-2222-2222-2222-222222222222"
    }
  }
  mock_resource "azurerm_key_vault" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-11/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-11"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-11/providers/Microsoft.OperationalInsights/workspaces/babaloo-sea-lng-log-11"
    }
  }
  mock_resource "azurerm_application_insights" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-11/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-11"
    }
  }
  mock_resource "azurerm_monitor_action_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-11/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-11"
    }
  }
}

mock_provider "azapi" {
  mock_resource "azapi_resource" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-11/providers/Microsoft.Storage/storageAccounts/babaloosealngst11"
    }
  }
}

mock_provider "random" {}

# The resource group is adopted with an import block; mock providers cannot import.
override_resource {
  target = azurerm_resource_group.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-11"
  }
}
# A mid-month creation time; the budget must start on the 1st of that month.
mock_provider "time" {
  mock_resource "time_static" {
    defaults = {
      rfc3339 = "2026-10-15T08:30:00Z"
    }
  }
}
mock_provider "modtm" {}

override_data {
  target = data.terraform_remote_state.shared
  values = {
    outputs = {
      database_names = {
        dev  = "invoicing_dev"
        prod = "invoicing_prod"
      }
      postgres_fqdn                  = "babaloo-sea-lng-psql-21.postgres.database.azure.com"
      document_intelligence_id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21"
      document_intelligence_endpoint = "https://babaloo-sea-lng-di-21.cognitiveservices.azure.com/"
    }
  }
}

variables {
  owner               = "test-owner"
  cost_centre         = "test-cc"
  application         = "test-app"
  data_classification = "test-class"
  alert_email         = "alerts@example.test"
}

run "prod_foundation" {
  command = apply

  assert {
    condition     = var.location == "southeastasia" && azurerm_resource_group.this.location == "southeastasia"
    error_message = "the region must default to southeastasia (azure.md rule 5)."
  }
  assert {
    condition     = azurerm_resource_group.this.name == "babaloo-sea-lng-rg-11"
    error_message = "the prod resource group must be babaloo-sea-lng-rg-11 (P-16)."
  }
  assert {
    condition     = output.resource_group_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-11"
    error_message = "the resource group id must be an output, for prod/app (terraform.md rule 8)."
  }
  assert {
    condition = azurerm_resource_group.this.tags == tomap({
      owner              = "test-owner"
      costCentre         = "test-cc"
      environment        = "prod"
      application        = "test-app"
      dataClassification = "test-class"
    })
    error_message = "the resource group must carry exactly the five P-17 tags."
  }
  assert {
    condition = local.names == {
      resource_group         = "babaloo-sea-lng-rg-11"
      postgres_server        = "babaloo-sea-lng-psql-11"
      document_intelligence  = "babaloo-sea-lng-di-11"
      key_vault              = "babaloo-sea-lng-kv-11"
      log_analytics          = "babaloo-sea-lng-log-11"
      application_insights   = "babaloo-sea-lng-appi-11"
      action_group           = "babaloo-sea-lng-ag-11"
      budget                 = "babaloo-sea-lng-budget-11"
      storage_account        = "babaloosealngst11"
      action_group_shortname = "lng-ag-11"
    }
    error_message = "prod names must use the 11-19 range (P-16)."
  }
  assert {
    condition     = output.storage_account.name == "babaloosealngst11" && output.key_vault.name == "babaloo-sea-lng-kv-11"
    error_message = "storage and vault names must follow P-16."
  }
  assert {
    condition     = output.identities["pipeline"].name == "babaloo-sea-lng-id-13" && length(output.identities) == 4
    error_message = "the four prod identities must be id-11..14."
  }
  assert {
    condition     = output.database.name == "invoicing_prod"
    error_message = "prod must read its database name from the shared stack's remote state."
  }
  assert {
    condition     = output.document_intelligence_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21" && output.document_intelligence_endpoint == "https://babaloo-sea-lng-di-21.cognitiveservices.azure.com/"
    error_message = "prod must pass the shared DI resource's id and endpoint through to prod/app (Story 2.3)."
  }
  assert {
    condition     = var.budget_amount == 2
    error_message = "terraform.tfvars must set the prod budget."
  }

  # Story 1.5: dimension alerting, Key Vault audit logs, budget through the action group.
  assert {
    condition     = output.application_insights.custom_metrics_opted_in_type == "WithDimensions"
    error_message = "prod Application Insights must have alerting on custom metric dimensions on (AD-17)."
  }
  assert {
    condition     = output.key_vault.audit_log_workspace_id == output.log_analytics_workspace_id
    error_message = "the prod Key Vault audit log must go to the prod workspace."
  }
  assert {
    condition     = module.foundation.budget_contact_groups == tolist([output.action_group_id])
    error_message = "the prod budget must notify through the prod action group."
  }
  assert {
    condition     = output.application_insights.sampling_percentage == 100
    error_message = "the prod Application Insights must not sample at ingestion (the apps sample)."
  }
}

