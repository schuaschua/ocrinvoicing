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
  mock_resource "azurerm_application_insights" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01"
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
  tenant_id           = "11111111-1111-1111-1111-111111111111"
  deploy_principal_id = "22222222-2222-2222-2222-222222222222"
  alert_email         = "alerts@example.test"
  budget_amount       = 2
}

# Covers: storage_retention_and_messaging, identities_key_vault_monitoring_budget, monitoring_and_alerts.
run "story_1_1_env_foundation_applied" {
  command = apply

  # --- storage_retention_and_messaging
  assert {
    condition     = local.containers == ["images", "corrections"]
    error_message = "containers must be images and corrections (AD-15)."
  }
  assert {
    condition     = local.host_containers == ["azure-webjobs-hosts", "azure-webjobs-secrets"] && output.storage_account.host_containers == local.host_containers
    error_message = "the Functions host containers must exist for <env>/app to scope roles to (platform requirement)."
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
    condition     = keys(module.storage.containers) == ["azure-webjobs-hosts", "azure-webjobs-secrets", "corrections", "images"] && length(module.storage.queues) == 4 && length(module.storage.tables) == 3
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
  # --- identities_key_vault_monitoring_budget
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
    condition     = module.application_insights.resource.sampling_percentage == 100 && module.application_insights.resource.local_authentication_disabled
    error_message = "Application Insights must not sample at ingestion (the apps sample) and must have local auth off."
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
  # --- monitoring_and_alerts
  # Story 1.5: dimension alerting, Key Vault audit logs, and budgets through the action group.
  assert {
    condition     = azapi_update_resource.application_insights_custom_metric_dimensions.body.properties.CustomMetricsOptedInType == "WithDimensions" && output.application_insights.custom_metrics_opted_in_type == "WithDimensions"
    error_message = "alerting on custom metric dimensions must be on (AD-17), or poison_message{queue} loses its queue."
  }
  assert {
    condition     = azapi_update_resource.application_insights_custom_metric_dimensions.resource_id == module.application_insights.resource_id && azapi_update_resource.application_insights_custom_metric_dimensions.type == "Microsoft.Insights/components@2020-02-02"
    error_message = "the dimension setting must patch this environment's Application Insights component."
  }
  assert {
    condition     = terraform_data.application_insights_settings.input.resource_id == module.application_insights.resource_id && terraform_data.application_insights_settings.input.tags == var.tags && terraform_data.application_insights_settings.input.sampling_percentage == 100
    error_message = "the dimension patch must be re-applied whenever the component's managed settings change."
  }
  assert {
    condition     = keys(local.key_vault_diagnostic_settings) == ["audit"] && local.key_vault_diagnostic_settings.audit.log_categories == ["AuditEvent"] && length(local.key_vault_diagnostic_settings.audit.log_groups) == 0 && length(local.key_vault_diagnostic_settings.audit.metric_categories) == 0
    error_message = "Key Vault must send exactly its AuditEvent log (azure.md rule 15: only the categories needed)."
  }
  assert {
    condition     = local.key_vault_diagnostic_settings.audit.workspace_resource_id == module.log_analytics.resource_id && output.key_vault.audit_log_workspace_id == module.log_analytics.resource_id
    error_message = "Key Vault audit logs must go to this environment's workspace."
  }
  assert {
    condition     = local.key_vault_diagnostic_settings.audit.name == "diag-babaloo-sea-lng-kv-01"
    error_message = "the Key Vault diagnostic setting must be named after the vault."
  }
  assert {
    condition     = alltrue([for n in azurerm_consumption_budget_resource_group.this.notification : tolist(n.contact_groups) == tolist([azurerm_monitor_action_group.this.id]) && tolist(n.contact_emails) == tolist(["alerts@example.test"])])
    error_message = "every budget notification must go through the action group, and to Dj's email."
  }
  assert {
    condition     = output.budget_contact_groups == tolist([output.action_group_id])
    error_message = "the budget must notify only this environment's action group."
  }
  assert {
    condition     = output.application_insights.sampling_percentage == 100
    error_message = "ingestion sampling must be off (100%), so it never compounds with the apps' sampling."
  }
}
