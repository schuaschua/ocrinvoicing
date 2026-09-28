# Offline tests: every provider is mocked, nothing reaches Azure.

# Mocked ids must look like real ARM ids, because the AVM modules parse them.
mock_provider "azurerm" {
  mock_resource "azurerm_key_vault" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.OperationalInsights/workspaces/babaloo-sea-lng-log-01"
    }
  }
  mock_resource "azurerm_monitor_action_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-01"
    }
  }
}
mock_provider "azapi" {
  mock_resource "azapi_resource" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01"
    }
  }
}
mock_provider "random" {}
# A mid-month creation time; the budget must start on the 1st of that month.
mock_provider "time" {
  mock_resource "time_static" {
    defaults = {
      rfc3339 = "2026-10-15T08:30:00Z"
    }
  }
}
mock_provider "modtm" {}

variables {
  location            = "southeastasia"
  resource_group_name = "babaloo-sea-lng-rg-01"
  resource_group_id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01"
  names = {
    storage_account        = "babaloosealngst01"
    key_vault              = "babaloo-sea-lng-kv-01"
    log_analytics          = "babaloo-sea-lng-log-01"
    application_insights   = "babaloo-sea-lng-appi-01"
    action_group           = "babaloo-sea-lng-ag-01"
    action_group_shortname = "lng-ag-01"
    budget                 = "babaloo-sea-lng-budget-01"
  }
  identity_names = {
    supplier_api = "babaloo-sea-lng-id-01"
    staff_api    = "babaloo-sea-lng-id-02"
    pipeline     = "babaloo-sea-lng-id-03"
    accounts_sim = "babaloo-sea-lng-id-04"
  }
  tags = {
    owner              = "test-owner"
    costCentre         = "test-cc"
    environment        = "dev"
    application        = "test-app"
    dataClassification = "test-class"
  }
  tenant_id                        = "11111111-1111-1111-1111-111111111111"
  deploy_principal_id              = "22222222-2222-2222-2222-222222222222"
  alert_email                      = "alerts@example.test"
  budget_amount                    = 2
  app_insights_sampling_percentage = 50
}

run "storage_retention_and_messaging" {
  command = apply

  assert {
    condition     = local.containers == ["images", "corrections"]
    error_message = "containers must be images and corrections (AD-15)."
  }
  assert {
    condition     = local.queues == ["q-quality", "q-extract", "q-validate", "q-post"]
    error_message = "queues must be the four AD-2 stage queues."
  }
  assert {
    condition     = local.tables == ["supplierlinks", "uploadkeys", "supplierreminders"]
    error_message = "tables must be supplierlinks, uploadkeys and supplierreminders."
  }
  assert {
    condition     = keys(module.storage.containers) == ["corrections", "images"] && length(module.storage.queues) == 4 && length(module.storage.tables) == 3
    error_message = "the storage module must create every container, queue and table."
  }
  assert {
    condition     = nonsensitive(module.storage.resource.body.sku.name) == "Standard_LRS"
    error_message = "storage must be LRS (P-15)."
  }
  assert {
    condition     = nonsensitive(module.storage.resource.body.properties.allowSharedKeyAccess) == false
    error_message = "shared-key access must be off."
  }
  assert {
    condition     = nonsensitive(module.storage.resource.tags) == var.tags
    error_message = "storage must carry the five P-17 tags."
  }
}

# The AVM storage module applies these in nested submodules and outputs neither, and
# tests can only read module outputs, so this checks the exact objects main.tf passes
# as blob_properties and storage_management_policy_rule.
run "storage_policies" {
  command = plan

  assert {
    condition     = local.blob_properties.delete_retention_policy.days == 7 && local.blob_properties.delete_retention_policy.enabled
    error_message = "blob soft delete must be on for 7 days (AD-15)."
  }
  assert {
    condition     = local.blob_properties.container_delete_retention_policy.days == 7
    error_message = "container soft delete must be 7 days."
  }
  assert {
    condition     = local.lifecycle_rules.retention.actions.base_blob.delete_after_days_since_creation_greater_than == 30
    error_message = "lifecycle rule must delete after 30 days since creation (AD-15)."
  }
  assert {
    condition     = local.lifecycle_rules.retention.filters.prefix_match == ["images/", "corrections/"]
    error_message = "lifecycle rule must cover images/ and corrections/ only."
  }
}

run "identities_key_vault_monitoring_budget" {
  command = apply

  assert {
    condition = {
      for app, identity in module.identities : app => identity.resource.name
      } == {
      supplier_api = "babaloo-sea-lng-id-01"
      staff_api    = "babaloo-sea-lng-id-02"
      pipeline     = "babaloo-sea-lng-id-03"
      accounts_sim = "babaloo-sea-lng-id-04"
    }
    error_message = "the four app identities must be named id-01..04 in AD-1 order."
  }
  assert {
    condition     = alltrue([for identity in module.identities : identity.resource.tags == var.tags])
    error_message = "every identity must carry the five tags."
  }
  assert {
    condition     = module.key_vault.name == "babaloo-sea-lng-kv-01" && keys(module.key_vault.secrets) == ["hmac_key"]
    error_message = "the vault must hold exactly the Terraform-generated HMAC key (the PGP pair is step 4b)."
  }
  assert {
    condition     = module.key_vault.secrets["hmac_key"].name == "hmac-key"
    error_message = "the HMAC secret must be named hmac-key."
  }
  assert {
    condition     = random_password.hmac_key.length == 64 && random_password.hmac_key.special == false
    error_message = "the HMAC key must be a 64-character random value."
  }
  assert {
    condition     = module.log_analytics.resource.daily_quota_gb == 0.08 && module.log_analytics.resource.retention_in_days == 30
    error_message = "Log Analytics must cap at 0.08 GB/day with 30-day retention (AD-17)."
  }
  assert {
    condition     = module.log_analytics.resource.sku == "PerGB2018" && module.log_analytics.resource.tags == var.tags
    error_message = "Log Analytics must be PerGB2018 and tagged."
  }
  assert {
    condition     = module.application_insights.resource.sampling_percentage == 50 && module.application_insights.resource.local_authentication_disabled
    error_message = "Application Insights must sample and have local auth off."
  }
  assert {
    condition     = module.application_insights.resource.workspace_id == module.log_analytics.resource_id && module.application_insights.resource.tags == var.tags
    error_message = "Application Insights must be workspace-based on this environment's workspace, and tagged."
  }
  assert {
    condition     = azurerm_monitor_action_group.this.email_receiver[0].email_address == "alerts@example.test" && azurerm_monitor_action_group.this.tags == var.tags
    error_message = "the action group must email Dj and be tagged."
  }
  assert {
    condition = toset([
      for n in azurerm_consumption_budget_resource_group.this.notification : "${n.threshold_type}:${n.threshold}"
    ]) == toset(["Actual:90", "Actual:100", "Actual:110", "Forecasted:110"])
    error_message = "the budget must alert at actual 90/100/110 and forecast 110 (azure.md rule 17)."
  }
  assert {
    condition     = azurerm_consumption_budget_resource_group.this.time_period[0].start_date == "2026-10-01T00:00:00Z"
    error_message = "the budget must start on the first of the month it is created in."
  }
  assert {
    condition     = azurerm_consumption_budget_resource_group.this.name == "babaloo-sea-lng-budget-01" && azurerm_consumption_budget_resource_group.this.amount == 2
    error_message = "the budget name and amount must come from the inputs."
  }
}

run "tags_must_be_complete" {
  command = plan

  variables {
    tags = {
      owner       = "test-owner"
      environment = "dev"
    }
  }

  expect_failures = [var.tags]
}

run "sampling_must_be_on" {
  command = plan

  variables {
    app_insights_sampling_percentage = 100
  }

  expect_failures = [var.app_insights_sampling_percentage]
}
