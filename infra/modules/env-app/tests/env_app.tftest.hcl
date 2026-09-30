# Offline tests: every provider is mocked, nothing reaches Azure.

# Mocked ids must look like real ARM ids, because the AVM modules parse them.
mock_provider "azurerm" {}
mock_provider "azapi" {
  mock_resource "azapi_resource" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-01"
    }
  }
  mock_data "azapi_client_config" {
    defaults = {
      subscription_id = "00000000-0000-0000-0000-000000000000"
      tenant_id       = "11111111-1111-1111-1111-111111111111"
    }
  }
}
mock_provider "random" {}

# Each plan and app gets its own id (the default above is a site id, which the site
# submodules parse), so the tests can tell the plans apart.
override_resource {
  target = module.plans["supplier_api"].azapi_resource.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/babaloo-sea-lng-asp-01"
  }
}
override_resource {
  target = module.plans["staff_api"].azapi_resource.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/babaloo-sea-lng-asp-02"
  }
}
override_resource {
  target = module.plans["pipeline"].azapi_resource.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/babaloo-sea-lng-asp-03"
  }
}
override_resource {
  target = module.plans["accounts_sim"].azapi_resource.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/babaloo-sea-lng-asp-04"
  }
}
override_resource {
  target = module.function_apps["supplier_api"].azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-01"
    output = { properties = { defaultHostName = "babaloo-sea-lng-func-01.azurewebsites.net" } }
  }
}
override_resource {
  target = module.function_apps["staff_api"].azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-02"
    output = { properties = { defaultHostName = "babaloo-sea-lng-func-02.azurewebsites.net" } }
  }
}
override_resource {
  target = module.function_apps["pipeline"].azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-03"
    output = { properties = { defaultHostName = "babaloo-sea-lng-func-03.azurewebsites.net" } }
  }
}
override_resource {
  target = module.function_apps["accounts_sim"].azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-04"
    output = { properties = { defaultHostName = "babaloo-sea-lng-func-04.azurewebsites.net" } }
  }
}
mock_provider "time" {}
mock_provider "modtm" {}

variables {
  environment       = "dev"
  location          = "southeastasia"
  resource_group_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01"
  app_names = {
    supplier_api = { plan = "babaloo-sea-lng-asp-01", function_app = "babaloo-sea-lng-func-01", deployment_container = "deploy-supplier-api" }
    staff_api    = { plan = "babaloo-sea-lng-asp-02", function_app = "babaloo-sea-lng-func-02", deployment_container = "deploy-staff-api" }
    pipeline     = { plan = "babaloo-sea-lng-asp-03", function_app = "babaloo-sea-lng-func-03", deployment_container = "deploy-pipeline" }
    accounts_sim = { plan = "babaloo-sea-lng-asp-04", function_app = "babaloo-sea-lng-func-04", deployment_container = "deploy-accounts-sim" }
  }
  identities = {
    supplier_api = {
      name         = "babaloo-sea-lng-id-01"
      resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-01"
      principal_id = "10000000-0000-0000-0000-000000000001"
      client_id    = "20000000-0000-0000-0000-000000000001"
    }
    staff_api = {
      name         = "babaloo-sea-lng-id-02"
      resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-02"
      principal_id = "10000000-0000-0000-0000-000000000002"
      client_id    = "20000000-0000-0000-0000-000000000002"
    }
    pipeline = {
      name         = "babaloo-sea-lng-id-03"
      resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-03"
      principal_id = "10000000-0000-0000-0000-000000000003"
      client_id    = "20000000-0000-0000-0000-000000000003"
    }
    accounts_sim = {
      name         = "babaloo-sea-lng-id-04"
      resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-04"
      principal_id = "10000000-0000-0000-0000-000000000004"
      client_id    = "20000000-0000-0000-0000-000000000004"
    }
  }
  storage_account = {
    name        = "babaloosealngst01"
    resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01"
  }
  database = {
    name = "invoicing_dev"
    fqdn = "babaloo-sea-lng-psql-21.postgres.database.azure.com"
  }
  key_vault = {
    resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01"
    uri         = "https://babaloo-sea-lng-kv-01.vault.azure.net/"
  }
  private_key_vault_uri   = "https://babaloo-sea-lng-kv-22.vault.azure.net/"
  application_insights_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01"
  action_group_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-01"
  metric_alert_names = {
    poison_message    = "babaloo-sea-lng-ar-01"
    stuck_invoices    = "babaloo-sea-lng-ar-02"
    di_pages_used_pct = "babaloo-sea-lng-ar-03"
  }
  document_intelligence_id               = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21"
  document_intelligence_endpoint         = "https://babaloo-sea-lng-di-21.cognitiveservices.azure.com/"
  di_monthly_page_cap                    = 100
  telemetry_sampling_ratio               = 0.5
  staff_api_client_id                    = "30000000-0000-0000-0000-0000000000a1"
  accounts_sim_client_id                 = "30000000-0000-0000-0000-0000000000b1"
  application_insights_connection_string = "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://southeastasia-0.in.applicationinsights.azure.com/"
  tags = {
    owner              = "test-owner"
    costCentre         = "test-cc"
    environment        = "dev"
    application        = "test-app"
    dataClassification = "test-class"
  }
}

# Covers: four_apps_one_plan_each, runtime_roles_are_exactly_ad17, staff_api_built_in_auth,
# accounts_sim_built_in_auth.
run "story_1_3_env_app_applied" {
  command = apply

  # --- four_apps_one_plan_each
  assert {
    condition     = { for app, fa in output.function_apps : app => fa.host_name } == { for app, names in var.app_names : app => "${names.function_app}.azurewebsites.net" }
    error_message = "host_name must be each app's default host name (defaultHostName)."
  }
  assert {
    condition     = length(module.function_apps) == 4 && length(module.plans) == 4 && length(distinct(values(output.plan_ids))) == 4
    error_message = "there must be four apps and four distinct plans (AD-1)."
  }
  assert {
    condition = alltrue([
      # The AVM module normalises the casing of "serverfarms".
      for app, site in module.function_apps : lower(nonsensitive(site.resource.body.properties.serverFarmId)) == lower(module.plans[app].resource_id)
    ])
    error_message = "each app must run in its own plan (AD-1)."
  }
  assert {
    condition     = { for app, plan in module.plans : app => plan.name } == { for app, names in var.app_names : app => names.plan }
    error_message = "plans must be named asp-NN per P-16."
  }
  assert {
    condition     = local.plan_sku == "FC1" && alltrue([for site in module.function_apps : nonsensitive(site.resource.body.kind) == "functionapp,linux"])
    error_message = "plans must be Flex Consumption (FC1) and apps Linux function apps."
  }
  assert {
    condition = alltrue([
      for site in module.function_apps : nonsensitive(site.resource.body.properties.functionAppConfig.runtime) == { name = "python", version = "3.13" }
    ])
    error_message = "every app must run Python 3.13 (AD-1)."
  }
  assert {
    condition = alltrue([
      for site in module.function_apps : nonsensitive(site.resource.body.properties.functionAppConfig.scaleAndConcurrency.instanceMemoryMB) == 2048
    ])
    error_message = "instance memory must be 2,048 MB (AD-17)."
  }
  assert {
    condition = {
      for app, site in module.function_apps : app => nonsensitive(site.resource.body.properties.functionAppConfig.scaleAndConcurrency.maximumInstanceCount)
      } == {
      supplier_api = 10
      staff_api    = 10
      pipeline     = 1
      accounts_sim = 10
    }
    error_message = "maximum instances must be 1 for pipeline and 10 for the others (AD-2, AD-17)."
  }
  assert {
    condition = alltrue([
      for site in module.function_apps : nonsensitive(site.resource.body.properties.functionAppConfig.scaleAndConcurrency.alwaysReady) == null
    ])
    error_message = "apps must use on-demand instances only, no always-ready instances (AD-1)."
  }
  assert {
    condition = alltrue([
      for app, site in module.function_apps :
      nonsensitive(site.resource.identity[0].type) == "UserAssigned" &&
      toset(nonsensitive(site.resource.identity[0].identity_ids)) == toset([var.identities[app].resource_id])
    ])
    error_message = "each app must use exactly its own user-assigned identity from <env>/foundation (AD-1)."
  }
  assert {
    condition = alltrue([
      for app, site in module.function_apps :
      nonsensitive(site.resource.body.properties.functionAppConfig.deployment.storage.value) == "https://babaloosealngst01.blob.core.windows.net/${var.app_names[app].deployment_container}" &&
      nonsensitive(site.resource.body.properties.functionAppConfig.deployment.storage.authentication.userAssignedIdentityResourceId) == var.identities[app].resource_id
    ])
    error_message = "each app must deploy from its own container, read with its own identity."
  }
  assert {
    condition     = toset([for c in azurerm_storage_container.deployment : c.name]) == toset(["deploy-supplier-api", "deploy-staff-api", "deploy-pipeline", "deploy-accounts-sim"]) && alltrue([for c in azurerm_storage_container.deployment : c.container_access_type == "private"])
    error_message = "each app must have a private deployment container."
  }
  assert {
    condition = alltrue([
      for site in module.function_apps :
      nonsensitive(site.resource.body.properties.httpsOnly) && nonsensitive(site.resource.body.properties.publicNetworkAccess) == "Enabled"
    ])
    error_message = "apps must be HTTPS only and reachable without a VNet."
  }
  assert {
    condition     = alltrue([for site in module.function_apps : nonsensitive(site.resource.tags) == var.tags])
    error_message = "every app must carry the five P-17 tags."
  }
  # --- runtime_roles_are_exactly_ad17
  assert {
    condition = toset([
      for ra in azurerm_role_assignment.runtime : "${ra.principal_id} | ${ra.role_definition_name} | ${ra.scope}"
      ]) == toset([
      "10000000-0000-0000-0000-000000000001 | Storage Blob Data Contributor | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/images",
      "10000000-0000-0000-0000-000000000001 | Storage Queue Data Message Sender | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/queueServices/default/queues/q-quality",
      "10000000-0000-0000-0000-000000000001 | Storage Table Data Contributor | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01",
      "10000000-0000-0000-0000-000000000001 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/deploy-supplier-api",
      "10000000-0000-0000-0000-000000000001 | Monitoring Metrics Publisher | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01",
      "10000000-0000-0000-0000-000000000002 | Storage Blob Data Contributor | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/images",
      "10000000-0000-0000-0000-000000000002 | Storage Blob Data Contributor | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/corrections",
      "10000000-0000-0000-0000-000000000002 | Storage Queue Data Message Sender | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01",
      "10000000-0000-0000-0000-000000000002 | Storage Table Data Contributor | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01",
      "10000000-0000-0000-0000-000000000002 | Key Vault Secrets User | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01/secrets/pgp-public-key",
      "10000000-0000-0000-0000-000000000002 | Key Vault Secrets User | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01/secrets/hmac-key",
      "10000000-0000-0000-0000-000000000002 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/deploy-staff-api",
      "10000000-0000-0000-0000-000000000002 | Monitoring Metrics Publisher | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01",
      "10000000-0000-0000-0000-000000000003 | Storage Blob Data Contributor | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01",
      "10000000-0000-0000-0000-000000000003 | Storage Queue Data Contributor | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01",
      "10000000-0000-0000-0000-000000000003 | Storage Table Data Contributor | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01",
      "10000000-0000-0000-0000-000000000003 | Key Vault Secrets User | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01/secrets/pgp-public-key",
      "10000000-0000-0000-0000-000000000003 | Key Vault Secrets User | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01/secrets/hmac-key",
      "10000000-0000-0000-0000-000000000003 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/deploy-pipeline",
      "10000000-0000-0000-0000-000000000003 | Monitoring Metrics Publisher | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01",
      # Story 2.3 (AD-8): the one DI caller, on the shared F0 resource.
      "10000000-0000-0000-0000-000000000003 | Cognitive Services User | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21",
      "10000000-0000-0000-0000-000000000004 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/deploy-accounts-sim",
      "10000000-0000-0000-0000-000000000004 | Monitoring Metrics Publisher | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01",
      # Functions host containers: platform requirement beyond AD-17 (overnight decision).
      "10000000-0000-0000-0000-000000000001 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/azure-webjobs-hosts",
      "10000000-0000-0000-0000-000000000001 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/azure-webjobs-secrets",
      "10000000-0000-0000-0000-000000000002 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/azure-webjobs-hosts",
      "10000000-0000-0000-0000-000000000002 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/azure-webjobs-secrets",
      "10000000-0000-0000-0000-000000000003 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/azure-webjobs-hosts",
      "10000000-0000-0000-0000-000000000003 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/azure-webjobs-secrets",
      "10000000-0000-0000-0000-000000000004 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/azure-webjobs-hosts",
      "10000000-0000-0000-0000-000000000004 | Storage Blob Data Owner | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01/blobServices/default/containers/azure-webjobs-secrets",
    ]) && length(azurerm_role_assignment.runtime) == 31
    error_message = "runtime roles must be exactly the AD-17 table (minus ACS, Story 5.2) plus Blob Data Owner on the two Functions host containers."
  }
  assert {
    condition     = alltrue([for ra in azurerm_role_assignment.runtime : can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/.+", ra.scope))])
    error_message = "no runtime role may be scoped to the subscription or a resource group (azure.md rule 9)."
  }
  assert {
    condition     = length([for ra in azurerm_role_assignment.runtime : ra if strcontains(ra.scope, "pgp-private-key")]) == 0
    error_message = "Terraform must grant no identity any role on pgp-private-key: operator step 4b grants staff-api alone in the private-key vault (OCR-129, AD-11)."
  }
  assert {
    condition = length([
      for ra in azurerm_role_assignment.runtime : ra
      if ra.role_definition_name == "Storage Blob Data Owner" && !can(regex("/blobServices/default/containers/(deploy-[a-z-]+|azure-webjobs-hosts|azure-webjobs-secrets)$", ra.scope))
    ]) == 0
    error_message = "Blob Data Owner must be scoped to a deployment or Functions host container, never the account."
  }
  assert {
    condition     = alltrue([for ra in azurerm_role_assignment.runtime : ra.principal_type == "ServicePrincipal"])
    error_message = "runtime roles are for managed identities (ServicePrincipal)."
  }
  assert {
    condition     = [for ra in azurerm_role_assignment.runtime : ra.principal_id if ra.role_definition_name == "Cognitive Services User"] == ["10000000-0000-0000-0000-000000000003"]
    error_message = "only the pipeline identity may call Document Intelligence (AD-8: one caller)."
  }
  # Story 2.3: di_pages_used_pct alerts Dj at 80 % of the page cap (AD-8, AD-17).
  assert {
    condition = (
      output.metric_alerts["di_pages_used_pct"].name == "babaloo-sea-lng-ar-03" &&
      output.metric_alerts["di_pages_used_pct"].criteria == { metric_name = "di_pages_used_pct", operator = "GreaterThanOrEqual", threshold = 80 } &&
      output.metric_alerts["di_pages_used_pct"].action_group_ids == [var.action_group_id] &&
      output.metric_alerts["di_pages_used_pct"].scopes == toset([var.application_insights_id])
    )
    error_message = "di_pages_used_pct must alert the action group at 80 % of the cap, on this environment's Application Insights."
  }
  # --- staff_api_built_in_auth
  # Story 2.7: staff-api signs in with Entra through built-in auth (AD-14).
  assert {
    condition = (
      azapi_update_resource.staff_api_auth.type == "Microsoft.Web/sites/config@2025-03-01" &&
      azapi_update_resource.staff_api_auth.name == "authsettingsV2" &&
      azapi_update_resource.staff_api_auth.parent_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-02"
    )
    error_message = "built-in auth v2 must be configured on the staff-api site (func-02) only."
  }
  assert {
    condition = (
      azapi_update_resource.staff_api_auth.body.properties.platform.enabled &&
      azapi_update_resource.staff_api_auth.body.properties.globalValidation.requireAuthentication &&
      azapi_update_resource.staff_api_auth.body.properties.globalValidation.unauthenticatedClientAction == "RedirectToLoginPage" &&
      azapi_update_resource.staff_api_auth.body.properties.globalValidation.redirectToProvider == "azureactivedirectory" &&
      azapi_update_resource.staff_api_auth.body.properties.globalValidation.excludedPaths == ["/api/health"]
    )
    error_message = "staff-api must require sign-in, redirect pages to Entra (401 for XHR calls) and leave only /api/health anonymous (AD-14)."
  }
  assert {
    condition = (
      azapi_update_resource.staff_api_auth.body.properties.identityProviders.azureActiveDirectory.enabled &&
      azapi_update_resource.staff_api_auth.body.properties.identityProviders.azureActiveDirectory.registration == {
        clientId     = "30000000-0000-0000-0000-0000000000a1"
        openIdIssuer = "https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111/v2.0"
      }
    )
    error_message = "staff-api must sign in through its own app registration, single tenant, with no client secret (ID tokens only)."
  }
  assert {
    condition     = keys(azapi_update_resource.staff_api_auth.body.properties.identityProviders) == ["azureActiveDirectory"]
    error_message = "Entra must be the only identity provider."
  }
  assert {
    condition     = !azapi_update_resource.staff_api_auth.body.properties.login.tokenStore.enabled && azapi_update_resource.staff_api_auth.body.properties.httpSettings.requireHttps
    error_message = "the token store must be off and HTTPS required."
  }
  assert {
    condition = (
      azapi_update_resource.staff_api_auth.body.properties.login.cookieExpiration == {
        convention       = "FixedTime"
        timeToExpiration = "08:00:00"
      } &&
      azapi_update_resource.staff_api_auth.body.properties.login.preserveUrlFragmentsForLogins
    )
    error_message = "the staff session must end 8 hours after sign-in (FixedTime) and sign-in must keep URL fragments."
  }
  assert {
    condition     = !can(regex("(?i)secret", jsonencode(azapi_update_resource.staff_api_auth.body)))
    error_message = "built-in auth must use no client secret (AD-14)."
  }
  assert {
    condition = output.staff_api_auth == {
      client_id                     = "30000000-0000-0000-0000-0000000000a1"
      open_id_issuer                = "https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111/v2.0"
      require_authentication        = true
      unauthenticated_client_action = "RedirectToLoginPage"
      excluded_paths                = ["/api/health"]
      token_store_enabled           = false
      site_id                       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-02"
    }
    error_message = "the staff_api_auth output must report the configured auth."
  }
  # --- accounts_sim_built_in_auth
  # Story 3.1 (AD-10): only this environment's pipeline identity may call accounts-sim,
  # with a token for its own app registration; signed-out calls get 401.
  assert {
    condition = (
      azapi_update_resource.accounts_sim_auth.type == "Microsoft.Web/sites/config@2025-03-01" &&
      azapi_update_resource.accounts_sim_auth.name == "authsettingsV2" &&
      azapi_update_resource.accounts_sim_auth.parent_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-04" &&
      azapi_update_resource.accounts_sim_auth.body.properties.platform.enabled &&
      azapi_update_resource.accounts_sim_auth.body.properties.globalValidation == {
        requireAuthentication       = true
        unauthenticatedClientAction = "Return401"
      }
    )
    error_message = "built-in auth v2 must be on the accounts-sim site (func-04), require sign-in on every route and answer 401 to signed-out calls (AD-10)."
  }
  assert {
    condition = (
      keys(azapi_update_resource.accounts_sim_auth.body.properties.identityProviders) == ["azureActiveDirectory"] &&
      azapi_update_resource.accounts_sim_auth.body.properties.identityProviders.azureActiveDirectory.registration == {
        clientId     = "30000000-0000-0000-0000-0000000000b1"
        openIdIssuer = "https://sts.windows.net/11111111-1111-1111-1111-111111111111/v2.0"
      } &&
      azapi_update_resource.accounts_sim_auth.body.properties.identityProviders.azureActiveDirectory.validation == {
        allowedAudiences           = ["api://30000000-0000-0000-0000-0000000000b1"]
        defaultAuthorizationPolicy = { allowedPrincipals = { identities = ["10000000-0000-0000-0000-000000000003"] } }
      }
    )
    error_message = "accounts-sim must accept only tokens for its own app registration (api://<client id>), single tenant, from this environment's pipeline identity alone (AD-10)."
  }
  assert {
    condition = (
      !azapi_update_resource.accounts_sim_auth.body.properties.login.tokenStore.enabled &&
      azapi_update_resource.accounts_sim_auth.body.properties.httpSettings.requireHttps &&
      !can(regex("(?i)secret", jsonencode(azapi_update_resource.accounts_sim_auth.body)))
    )
    error_message = "accounts-sim's auth must keep no tokens, require HTTPS and use no client secret."
  }
  assert {
    condition = output.accounts_sim_auth == {
      client_id                     = "30000000-0000-0000-0000-0000000000b1"
      open_id_issuer                = "https://sts.windows.net/11111111-1111-1111-1111-111111111111/v2.0"
      allowed_audiences             = ["api://30000000-0000-0000-0000-0000000000b1"]
      allowed_principal_ids         = ["10000000-0000-0000-0000-000000000003"]
      require_authentication        = true
      unauthenticated_client_action = "Return401"
      site_id                       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-04"
    }
    error_message = "the accounts_sim_auth output must report the configured auth."
  }
}

# Covers: app_settings_hold_no_secrets, pipeline_database_settings, telemetry_settings, private_key_vault_setting.
run "story_1_3_env_app_settings_plan" {
  command = plan

  # --- app_settings_hold_no_secrets
  assert {
    condition = { for app, settings in local.app_settings : app => toset(keys(settings)) } == {
      supplier_api = toset(["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "TELEMETRY_SAMPLING_RATIO", "AzureWebJobsStorage__accountName", "AzureWebJobsStorage__credential", "AzureWebJobsStorage__clientId", "STORAGE_ACCOUNT_NAME"])
      staff_api    = toset(["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "TELEMETRY_SAMPLING_RATIO", "AzureWebJobsStorage__accountName", "AzureWebJobsStorage__credential", "AzureWebJobsStorage__clientId", "STORAGE_ACCOUNT_NAME", "KEY_VAULT_URI", "PGP_PRIVATE_KEY_VAULT_URI", "POSTGRES_HOST", "POSTGRES_DATABASE", "POSTGRES_USER", "DI_MONTHLY_PAGE_CAP", "INVOICE_CURRENCY"])
      pipeline     = toset(["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "TELEMETRY_SAMPLING_RATIO", "AzureWebJobsStorage__accountName", "AzureWebJobsStorage__credential", "AzureWebJobsStorage__clientId", "STORAGE_ACCOUNT_NAME", "KEY_VAULT_URI", "POSTGRES_HOST", "POSTGRES_DATABASE", "POSTGRES_USER", "DI_ENDPOINT", "DI_MONTHLY_PAGE_CAP", "INVOICE_CURRENCY", "ACCOUNTS_BASE_URL", "ACCOUNTS_AUDIENCE"])
      accounts_sim = toset(["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "TELEMETRY_SAMPLING_RATIO", "AzureWebJobsStorage__accountName", "AzureWebJobsStorage__credential", "AzureWebJobsStorage__clientId", "POSTGRES_HOST", "POSTGRES_DATABASE", "POSTGRES_USER", "PIPELINE_PRINCIPAL_ID"])
    }
    error_message = "each app must get exactly the settings its pydantic-settings class reads, plus the host settings."
  }
  assert {
    condition = alltrue([
      for app, settings in local.app_settings :
      settings.AZURE_CLIENT_ID == var.identities[app].client_id && settings.AzureWebJobsStorage__clientId == var.identities[app].client_id && settings.AzureWebJobsStorage__credential == "managedidentity" && settings.APP_ENVIRONMENT == "dev"
    ])
    error_message = "every app must sign in as its own identity, host storage included."
  }
  assert {
    condition = alltrue(flatten([
      for settings in local.app_settings : [
        for value in values(settings) : !can(regex("(?i)(accountkey=|sharedaccesssignature|sig=|password|secret)", value))
      ]
    ]))
    error_message = "app settings must hold no keys, SAS tokens, passwords or secrets."
  }
  # --- pipeline_database_settings
  # Story 2.1: the pipeline signs in to its environment's database as its own identity,
  # with an Entra token (AD-11); no other app gets database settings.
  assert {
    condition = (
      local.app_settings["pipeline"].POSTGRES_HOST == "babaloo-sea-lng-psql-21.postgres.database.azure.com" &&
      local.app_settings["pipeline"].POSTGRES_DATABASE == "invoicing_dev" &&
      local.app_settings["pipeline"].POSTGRES_USER == "babaloo-sea-lng-id-03" &&
      local.app_settings["pipeline"].DI_ENDPOINT == "https://babaloo-sea-lng-di-21.cognitiveservices.azure.com/" &&
      local.app_settings["pipeline"].DI_MONTHLY_PAGE_CAP == "100" &&
      local.app_settings["pipeline"].INVOICE_CURRENCY == "SGD" &&
      local.app_settings["pipeline"].ACCOUNTS_BASE_URL == "https://babaloo-sea-lng-func-04.azurewebsites.net/api" &&
      local.app_settings["pipeline"].ACCOUNTS_AUDIENCE == "api://30000000-0000-0000-0000-0000000000b1"
    )
    error_message = "the pipeline must connect to its environment's database as its own identity's login, to DI with its cap and currency (Story 2.3), and to its own accounts-sim with that registration's audience (Story 3.2)."
  }
  # Story 2.8: staff-api signs in as its own identity, with the same cap and currency.
  assert {
    condition = (
      local.app_settings["staff_api"].POSTGRES_HOST == "babaloo-sea-lng-psql-21.postgres.database.azure.com" &&
      local.app_settings["staff_api"].POSTGRES_DATABASE == "invoicing_dev" &&
      local.app_settings["staff_api"].POSTGRES_USER == "babaloo-sea-lng-id-02" &&
      local.app_settings["staff_api"].DI_MONTHLY_PAGE_CAP == "100" &&
      local.app_settings["staff_api"].INVOICE_CURRENCY == "SGD"
    )
    error_message = "staff-api must connect to its environment's database as its own identity's login, with the DI cap and currency (Story 2.8)."
  }
  # Story 3.1: accounts-sim signs in as its own identity and is told the pipeline's
  # principal id, the one caller it serves (AD-10).
  assert {
    condition = (
      local.app_settings["accounts_sim"].POSTGRES_HOST == "babaloo-sea-lng-psql-21.postgres.database.azure.com" &&
      local.app_settings["accounts_sim"].POSTGRES_DATABASE == "invoicing_dev" &&
      local.app_settings["accounts_sim"].POSTGRES_USER == "babaloo-sea-lng-id-04" &&
      local.app_settings["accounts_sim"].PIPELINE_PRINCIPAL_ID == "10000000-0000-0000-0000-000000000003"
    )
    error_message = "accounts-sim must connect to its environment's database as its own identity's login and serve only the pipeline's principal id (Story 3.1)."
  }
  assert {
    condition     = length([for key in keys(local.app_settings["supplier_api"]) : key if startswith(key, "POSTGRES_")]) == 0
    error_message = "supplier-api gets no database settings (it has no login, AD-11)."
  }
  # --- telemetry_settings
  # Story 1.5: every app exports telemetry with Entra auth and samples (AD-17).
  assert {
    condition = alltrue([
      for app, settings in local.app_settings :
      settings.APPLICATIONINSIGHTS_AUTHENTICATION_STRING == "ClientId=${var.identities[app].client_id};Authorization=AAD" && settings.TELEMETRY_SAMPLING_RATIO == "0.5"
    ])
    error_message = "every app must sign in to Application Insights as its own identity and sample at the configured ratio."
  }
  assert {
    condition     = alltrue([for app in local.apps : local.per_app_role_assignments["${app}/monitoring/appi"].role == "Monitoring Metrics Publisher" && local.per_app_role_assignments["${app}/monitoring/appi"].scope == var.application_insights_id])
    error_message = "every app identity must be Monitoring Metrics Publisher on its Application Insights."
  }
  # --- private_key_vault_setting
  # OCR-129: staff-api is told where the private-key vault is; no other app is.
  assert {
    condition     = local.app_settings["staff_api"].PGP_PRIVATE_KEY_VAULT_URI == "https://babaloo-sea-lng-kv-22.vault.azure.net/"
    error_message = "staff-api must get PGP_PRIVATE_KEY_VAULT_URI, the private-key vault's URI."
  }
  assert {
    condition = alltrue([
      for app in ["supplier_api", "pipeline", "accounts_sim"] : !contains(keys(local.app_settings[app]), "PGP_PRIVATE_KEY_VAULT_URI")
    ])
    error_message = "only staff-api may be told where the private key is (OCR-129)."
  }
}

run "private_key_vault_uri_must_be_a_vault_uri" {
  command = plan

  variables {
    private_key_vault_uri = "http://babaloo-sea-lng-kv-22.vault.azure.net/"
  }

  expect_failures = [var.private_key_vault_uri]
}

run "private_key_vault_must_not_be_the_env_vault" {
  command = plan

  variables {
    private_key_vault_uri = "https://babaloo-sea-lng-kv-01.vault.azure.net/"
  }

  expect_failures = [var.private_key_vault_uri]
}

run "all_four_identities_are_required" {
  command = plan

  variables {
    identities = {
      supplier_api = {
        name         = "babaloo-sea-lng-id-01"
        resource_id  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-01"
        principal_id = "10000000-0000-0000-0000-000000000001"
        client_id    = "20000000-0000-0000-0000-000000000001"
      }
    }
  }

  expect_failures = [var.identities]
}

run "staff_api_client_id_must_be_a_uuid" {
  command = plan

  variables {
    staff_api_client_id = "babaloo-sea-lng-staff-api-dev"
  }

  expect_failures = [var.staff_api_client_id]
}
