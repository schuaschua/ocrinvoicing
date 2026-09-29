# Offline root test for shared/foundation: every provider is mocked, nothing
# reaches Azure.

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      subscription_id = "00000000-0000-0000-0000-000000000000"
      tenant_id       = "11111111-1111-1111-1111-111111111111"
      object_id       = "22222222-2222-2222-2222-222222222222"
    }
  }
  mock_resource "azurerm_postgresql_flexible_server" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.DBforPostgreSQL/flexibleServers/babaloo-sea-lng-psql-21"
    }
  }
  mock_resource "azurerm_monitor_action_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-21"
    }
  }
}

mock_provider "azapi" {
  mock_resource "azapi_resource" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21"
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

# The resource group is adopted with an import block; mock providers cannot import.
override_resource {
  target = azurerm_resource_group.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21"
  }
}

variables {
  owner                               = "test-owner"
  cost_centre                         = "test-cc"
  application                         = "test-app"
  data_classification                 = "test-class"
  alert_email                         = "alerts@example.test"
  postgres_entra_admin_object_id      = "33333333-3333-3333-3333-333333333333"
  postgres_entra_admin_principal_name = "operator@example.test"
  postgres_entra_admin_principal_type = "Group"
}

run "shared_foundation" {
  command = apply

  assert {
    condition     = azurerm_resource_group.this.name == "babaloo-sea-lng-rg-21" && azurerm_resource_group.this.location == "southeastasia"
    error_message = "the shared resource group must be babaloo-sea-lng-rg-21 in southeastasia."
  }
  assert {
    condition = azurerm_resource_group.this.tags == tomap({
      owner              = "test-owner"
      costCentre         = "test-cc"
      environment        = "shared"
      application        = "test-app"
      dataClassification = "test-class"
    })
    error_message = "the resource group must carry exactly the five P-17 tags."
  }

  # PostgreSQL (AD-11, AD-12). The AVM module outputs no server attributes and tests
  # can only read module outputs, so these check the exact objects passed to it.
  assert {
    condition     = local.postgres_authentication.password_auth_enabled == false && local.postgres_authentication.active_directory_auth_enabled == true
    error_message = "PostgreSQL must use Entra-only authentication (AD-11)."
  }
  assert {
    condition     = local.postgres_authentication.tenant_id == "11111111-1111-1111-1111-111111111111"
    error_message = "Entra authentication must use this tenant."
  }
  assert {
    condition     = local.postgres_ad_administrator.operator.object_id == "33333333-3333-3333-3333-333333333333" && local.postgres_ad_administrator.operator.principal_type == "Group"
    error_message = "the Entra admin must be the configured operator principal."
  }
  assert {
    condition     = module.postgres.name == "babaloo-sea-lng-psql-21"
    error_message = "the server must be named babaloo-sea-lng-psql-21."
  }
  assert {
    condition = local.postgres == {
      sku_name                     = "B_Standard_B1ms"
      server_version               = "18"
      storage_mb                   = 32768
      backup_retention_days        = 7
      geo_redundant_backup_enabled = false
      auto_grow_enabled            = false
    }
    error_message = "the server must be B1ms, PostgreSQL 18, 32 GB, 7-day local backup (AD-12)."
  }
  assert {
    condition     = output.database_names == { dev = "invoicing_dev", prod = "invoicing_prod" }
    error_message = "the server must hold invoicing_dev and invoicing_prod."
  }
  assert {
    condition     = length(module.postgres.database_resource_ids) == 2
    error_message = "both databases must be created."
  }
  assert {
    condition     = local.postgres_firewall_rules.all_ipv4.start_ip_address == "0.0.0.0" && local.postgres_firewall_rules.all_ipv4.end_ip_address == "255.255.255.255"
    error_message = "the firewall must be open to all public IPv4 addresses (AD-17 step 2 exception)."
  }
  assert {
    condition     = local.postgres_extensions == "PGCRYPTO"
    error_message = "pgcrypto must be allow-listed (AD-11)."
  }
  assert {
    condition     = azurerm_postgresql_flexible_server_configuration.require_secure_transport.value == "ON"
    error_message = "TLS must be required."
  }

  # Document Intelligence F0 (AD-8)
  assert {
    condition     = module.document_intelligence.resource.sku_name == "F0" && module.document_intelligence.resource.kind == "FormRecognizer"
    error_message = "Document Intelligence must be FormRecognizer F0."
  }
  assert {
    condition     = module.document_intelligence.resource.custom_subdomain_name == "babaloo-sea-lng-di-21"
    error_message = "Document Intelligence must have its custom subdomain (AD-8)."
  }
  assert {
    condition     = tostring(module.document_intelligence.resource.local_auth_enabled) == "false"
    error_message = "Document Intelligence keys must be off (managed identity only)."
  }
  assert {
    condition     = module.document_intelligence.resource.location == "southeastasia"
    error_message = "Document Intelligence must be in southeastasia."
  }

  # Budget (azure.md rule 17)
  assert {
    condition = toset([
      for n in azurerm_consumption_budget_resource_group.this.notification : "${n.threshold_type}:${n.threshold}"
    ]) == toset(["Actual:90", "Actual:100", "Actual:110", "Forecasted:110"])
    error_message = "the shared budget must alert at actual 90/100/110 and forecast 110."
  }
  assert {
    condition     = azurerm_consumption_budget_resource_group.this.time_period[0].start_date == "2026-10-01T00:00:00Z"
    error_message = "the budget must start on the first of the month it is created in."
  }
  assert {
    condition     = azurerm_consumption_budget_resource_group.this.name == "babaloo-sea-lng-budget-21"
    error_message = "the shared budget must be babaloo-sea-lng-budget-21."
  }

  # Action group ag-21 (Story 1.5): the shared and subscription budgets notify through it.
  assert {
    condition     = azurerm_monitor_action_group.this.name == "babaloo-sea-lng-ag-21" && azurerm_monitor_action_group.this.short_name == "lng-ag-21"
    error_message = "the shared action group must be babaloo-sea-lng-ag-21 (P-16)."
  }
  assert {
    condition     = azurerm_monitor_action_group.this.email_receiver[0].email_address == "alerts@example.test" && azurerm_monitor_action_group.this.tags == tomap(local.tags)
    error_message = "the shared action group must email Dj and carry the five tags."
  }
  assert {
    condition     = alltrue([for n in azurerm_consumption_budget_resource_group.this.notification : tolist(n.contact_groups) == tolist([azurerm_monitor_action_group.this.id]) && tolist(n.contact_emails) == tolist(["alerts@example.test"])])
    error_message = "every shared budget notification must go through ag-21, and to Dj's email."
  }
  assert {
    condition     = output.action_group_id == azurerm_monitor_action_group.this.id
    error_message = "the action group id must be an output, for budget-and-roles.sh."
  }
}

run "entra_admin_must_be_a_guid" {
  command = plan

  variables {
    postgres_entra_admin_object_id = "not-a-guid"
  }

  expect_failures = [var.postgres_entra_admin_object_id]
}
