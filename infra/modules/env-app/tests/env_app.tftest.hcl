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
  application_insights_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01"
  action_group_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-01"
  metric_alert_names = {
    poison_message = "babaloo-sea-lng-ar-01"
    stuck_invoices = "babaloo-sea-lng-ar-02"
  }
  telemetry_sampling_ratio               = 0.5
  staff_api_client_id                    = "30000000-0000-0000-0000-0000000000a1"
  application_insights_connection_string = "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://southeastasia-0.in.applicationinsights.azure.com/"
  tags = {
    owner              = "test-owner"
    costCentre         = "test-cc"
    environment        = "dev"
    application        = "test-app"
    dataClassification = "test-class"
  }
}


run "four_apps_one_plan_each" {
  command = apply

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
}

run "app_settings_hold_no_secrets" {
  command = plan

  assert {
    condition = { for app, settings in local.app_settings : app => toset(keys(settings)) } == {
      supplier_api = toset(["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "TELEMETRY_SAMPLING_RATIO", "AzureWebJobsStorage__accountName", "AzureWebJobsStorage__credential", "AzureWebJobsStorage__clientId", "STORAGE_ACCOUNT_NAME"])
      staff_api    = toset(["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "TELEMETRY_SAMPLING_RATIO", "AzureWebJobsStorage__accountName", "AzureWebJobsStorage__credential", "AzureWebJobsStorage__clientId", "STORAGE_ACCOUNT_NAME", "KEY_VAULT_URI"])
      pipeline     = toset(["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "TELEMETRY_SAMPLING_RATIO", "AzureWebJobsStorage__accountName", "AzureWebJobsStorage__credential", "AzureWebJobsStorage__clientId", "STORAGE_ACCOUNT_NAME", "KEY_VAULT_URI", "POSTGRES_HOST", "POSTGRES_DATABASE", "POSTGRES_USER"])
      accounts_sim = toset(["APP_ENVIRONMENT", "AZURE_CLIENT_ID", "APPLICATIONINSIGHTS_AUTHENTICATION_STRING", "TELEMETRY_SAMPLING_RATIO", "AzureWebJobsStorage__accountName", "AzureWebJobsStorage__credential", "AzureWebJobsStorage__clientId"])
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
}

# Story 2.1: the pipeline signs in to its environment's database as its own identity,
# with an Entra token (AD-11); no other app gets database settings.
run "pipeline_database_settings" {
  command = plan

  assert {
    condition = (
      local.app_settings["pipeline"].POSTGRES_HOST == "babaloo-sea-lng-psql-21.postgres.database.azure.com" &&
      local.app_settings["pipeline"].POSTGRES_DATABASE == "invoicing_dev" &&
      local.app_settings["pipeline"].POSTGRES_USER == "babaloo-sea-lng-id-03"
    )
    error_message = "the pipeline must connect to its environment's database as its own identity's login."
  }
  assert {
    condition = alltrue([
      for app in ["supplier_api", "staff_api", "accounts_sim"] :
      length([for key in keys(local.app_settings[app]) : key if startswith(key, "POSTGRES_")]) == 0
    ])
    error_message = "only the pipeline gets database settings in Story 2.1 (supplier-api has no login, AD-11)."
  }
}

# Story 1.5: every app exports telemetry with Entra auth and samples (AD-17).
run "telemetry_settings" {
  command = plan

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
}

run "sampling_must_be_on_in_the_apps" {
  command = plan

  variables {
    telemetry_sampling_ratio = 1
  }

  expect_failures = [var.telemetry_sampling_ratio]
}

run "runtime_roles_are_exactly_ad17" {
  command = apply

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
      "10000000-0000-0000-0000-000000000002 | Key Vault Secrets User | /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01/secrets/pgp-private-key",
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
    error_message = "runtime roles must be exactly the AD-17 table (minus DI and ACS, Stories 2.3 and 5.2) plus Blob Data Owner on the two Functions host containers."
  }
  assert {
    condition     = alltrue([for ra in azurerm_role_assignment.runtime : can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/.+", ra.scope))])
    error_message = "no runtime role may be scoped to the subscription or a resource group (azure.md rule 9)."
  }
  assert {
    condition     = length([for ra in azurerm_role_assignment.runtime : ra if ra.principal_id == "10000000-0000-0000-0000-000000000003" && endswith(ra.scope, "/secrets/pgp-private-key")]) == 0
    error_message = "the pipeline must never read the PGP private key (AD-11)."
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
}

run "environment_must_be_dev_or_prod" {
  command = plan

  variables {
    environment = "shared"
  }

  expect_failures = [var.environment]
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

# Story 2.2: the pipeline's two metric alerts (AD-17).
run "metric_alerts_poison_and_stuck" {
  command = plan

  assert {
    condition = (
      azurerm_monitor_metric_alert.poison_message.name == "babaloo-sea-lng-ar-01" &&
      azurerm_monitor_metric_alert.stuck_invoices.name == "babaloo-sea-lng-ar-02"
    )
    error_message = "the alert rules must take their P-16 names from the naming module."
  }
  assert {
    condition = alltrue([
      for alert in [azurerm_monitor_metric_alert.poison_message, azurerm_monitor_metric_alert.stuck_invoices] :
      alert.resource_group_name == "babaloo-sea-lng-rg-01" &&
      alert.scopes == toset(["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01"]) &&
      [for action in alert.action : action.action_group_id] == ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-01"] &&
      alert.tags == tomap({
        owner              = "test-owner"
        costCentre         = "test-cc"
        environment        = "dev"
        application        = "test-app"
        dataClassification = "test-class"
      })
    ])
    error_message = "both alerts must watch the environment's Application Insights, notify its action group and carry the five P-17 tags."
  }
  assert {
    condition = (
      one(azurerm_monitor_metric_alert.poison_message.criteria).metric_name == "poison_message" &&
      one(azurerm_monitor_metric_alert.poison_message.criteria).metric_namespace == "azure.applicationinsights" &&
      one(azurerm_monitor_metric_alert.poison_message.criteria).aggregation == "Total" &&
      one(azurerm_monitor_metric_alert.poison_message.criteria).operator == "GreaterThan" &&
      one(azurerm_monitor_metric_alert.poison_message.criteria).threshold == 0 &&
      one(azurerm_monitor_metric_alert.poison_message.criteria).skip_metric_validation &&
      azurerm_monitor_metric_alert.poison_message.window_size == "PT1H"
    )
    error_message = "poison_message must alert when its total is above 0 over an hour (AD-17)."
  }
  assert {
    condition = jsonencode([
      for dimension in one(azurerm_monitor_metric_alert.poison_message.criteria).dimension :
      [dimension.name, dimension.operator, dimension.values]
    ]) == jsonencode([["queue", "Include", ["*"]]])
    error_message = "poison_message must be split by queue."
  }
  assert {
    condition = (
      one(azurerm_monitor_metric_alert.stuck_invoices.criteria).metric_name == "stuck_invoices" &&
      one(azurerm_monitor_metric_alert.stuck_invoices.criteria).metric_namespace == "azure.applicationinsights" &&
      one(azurerm_monitor_metric_alert.stuck_invoices.criteria).aggregation == "Maximum" &&
      one(azurerm_monitor_metric_alert.stuck_invoices.criteria).operator == "GreaterThan" &&
      one(azurerm_monitor_metric_alert.stuck_invoices.criteria).threshold == 0 &&
      one(azurerm_monitor_metric_alert.stuck_invoices.criteria).skip_metric_validation &&
      length(one(azurerm_monitor_metric_alert.stuck_invoices.criteria).dimension) == 0
    )
    error_message = "stuck_invoices must alert when above 0 (AD-17)."
  }
}

run "metric_alert_names_must_be_exactly_the_two_metrics" {
  command = plan

  variables {
    metric_alert_names = { poison_message = "babaloo-sea-lng-ar-01" }
  }

  expect_failures = [var.metric_alert_names]
}

# Story 2.7: staff-api signs in with Entra through built-in auth (AD-14).
run "staff_api_built_in_auth" {
  command = apply

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
}

run "staff_api_client_id_must_be_a_uuid" {
  command = plan

  variables {
    staff_api_client_id = "babaloo-sea-lng-staff-api-dev"
  }

  expect_failures = [var.staff_api_client_id]
}
