# Offline root test for dev/app: every provider and the foundation remote state are
# mocked, nothing reaches Azure. Detailed values are tested in
# infra/modules/env-app/tests; this proves the wiring of the real root.

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
mock_provider "time" {}
mock_provider "modtm" {}

# Distinct ids per plan and app, so the test can tell them apart.
override_resource {
  target = module.app.module.plans["supplier_api"].azapi_resource.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/babaloo-sea-lng-asp-01"
  }
}
override_resource {
  target = module.app.module.function_apps["supplier_api"].azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-01"
    output = { properties = { defaultHostName = "babaloo-sea-lng-func-01.azurewebsites.net" } }
  }
}
override_resource {
  target = module.app.module.plans["staff_api"].azapi_resource.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/babaloo-sea-lng-asp-02"
  }
}
override_resource {
  target = module.app.module.function_apps["staff_api"].azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-02"
    output = { properties = { defaultHostName = "babaloo-sea-lng-func-02.azurewebsites.net" } }
  }
}
override_resource {
  target = module.app.module.plans["pipeline"].azapi_resource.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/babaloo-sea-lng-asp-03"
  }
}
override_resource {
  target = module.app.module.function_apps["pipeline"].azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-03"
    output = { properties = { defaultHostName = "babaloo-sea-lng-func-03.azurewebsites.net" } }
  }
}
override_resource {
  target = module.app.module.plans["accounts_sim"].azapi_resource.this
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/babaloo-sea-lng-asp-04"
  }
}
override_resource {
  target = module.app.module.function_apps["accounts_sim"].azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-04"
    output = { properties = { defaultHostName = "babaloo-sea-lng-func-04.azurewebsites.net" } }
  }
}

override_data {
  target = data.terraform_remote_state.foundation
  values = {
    outputs = {
      resource_group_name = "babaloo-sea-lng-rg-01"
      resource_group_id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01"
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
        name            = "babaloosealngst01"
        resource_id     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Storage/storageAccounts/babaloosealngst01"
        containers      = ["images", "corrections"]
        host_containers = ["azure-webjobs-hosts", "azure-webjobs-secrets"]
        queues          = ["q-quality", "q-extract", "q-validate", "q-post"]
        tables          = ["supplierlinks", "uploadkeys", "supplierreminders"]
      }
      key_vault = {
        name        = "babaloo-sea-lng-kv-01"
        resource_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01"
        uri         = "https://babaloo-sea-lng-kv-01.vault.azure.net/"
      }
      application_insights = {
        name                         = "babaloo-sea-lng-appi-01"
        resource_id                  = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01"
        custom_metrics_opted_in_type = "WithDimensions"
      }
      document_intelligence_id       = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21"
      document_intelligence_endpoint = "https://babaloo-sea-lng-di-21.cognitiveservices.azure.com/"
      database = {
        name = "invoicing_dev"
        fqdn = "babaloo-sea-lng-psql-21.postgres.database.azure.com"
      }
      action_group_id                        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-01"
      application_insights_connection_string = "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://southeastasia-0.in.applicationinsights.azure.com/"
    }
  }
}

variables {
  owner               = "test-owner"
  cost_centre         = "test-cc"
  application         = "test-app"
  data_classification = "test-class"
  staff_api_client_id = "30000000-0000-0000-0000-0000000000a1"
  # Story 3.1: accounts-sim's app registration.
  accounts_sim_client_id = "30000000-0000-0000-0000-0000000000b1"
}

run "dev_app" {
  command = apply

  assert {
    condition = { for app, fa in output.function_apps : app => fa.name } == {
      supplier_api = "babaloo-sea-lng-func-01"
      staff_api    = "babaloo-sea-lng-func-02"
      pipeline     = "babaloo-sea-lng-func-03"
      accounts_sim = "babaloo-sea-lng-func-04"
    }
    error_message = "the four dev apps must be func-01..04 (P-16)."
  }
  assert {
    condition     = { for app, fa in output.function_apps : app => fa.host_name } == { for app, fa in output.function_apps : app => "${fa.name}.azurewebsites.net" }
    error_message = "function_apps must output each app's default host name."
  }
  assert {
    condition     = length(distinct([for fa in output.function_apps : lower(fa.plan_id)])) == 4
    error_message = "each app must have its own plan (AD-1)."
  }
  assert {
    condition = alltrue([
      for app, fa in output.function_apps :
      lower(fa.plan_id) == lower("/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/serverFarms/${local.app_names[app].plan}")
    ])
    error_message = "each app must run in the plan named for it."
  }
  assert {
    condition = alltrue([
      for fa in output.function_apps : fa.instance_memory_mb == 2048
    ])
    error_message = "instance memory must be 2,048 MB (AD-17)."
  }
  assert {
    condition = {
      for app, fa in output.function_apps : app => fa.maximum_instance_count
    } == { supplier_api = 10, staff_api = 10, pipeline = 1, accounts_sim = 10 }
    error_message = "maximum instances must be 1 for pipeline and 10 for the others (AD-17)."
  }
  assert {
    condition = {
      for app, fa in output.function_apps : app => one(fa.identity_ids)
      } == {
      supplier_api = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-01"
      staff_api    = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-02"
      pipeline     = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-03"
      accounts_sim = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-04"
    }
    error_message = "each app must use its own identity from dev/foundation."
  }
  assert {
    condition = toset([for ra in output.role_assignments : ra.role]) == toset([
      "Storage Blob Data Contributor", "Storage Blob Data Owner", "Storage Queue Data Contributor",
      "Storage Queue Data Message Sender", "Storage Table Data Contributor", "Key Vault Secrets User",
      "Monitoring Metrics Publisher", "Cognitive Services User",
    ]) && length(output.role_assignments) == 31
    error_message = "only the AD-17 runtime roles, plus Blob Data Owner on the two Functions host containers (platform requirement), may be assigned (ACS comes with Story 5.2)."
  }
  assert {
    condition = alltrue([
      for key, ra in output.role_assignments : ra.principal_id == local.foundation.identities[split("/", key)[0]].principal_id
    ])
    error_message = "each role must go to the identity of the app it is for."
  }
  assert {
    condition     = alltrue([for key, ra in output.role_assignments : startswith(ra.scope, "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/") if key != "pipeline/cognitive/di"])
    error_message = "every runtime role must be scoped inside the dev resource group, never the subscription."
  }
  assert {
    condition = alltrue([
      for fa in output.function_apps : fa.tags == tomap({
        owner              = "test-owner"
        costCentre         = "test-cc"
        environment        = "dev"
        application        = "test-app"
        dataClassification = "test-class"
      })
    ])
    error_message = "every app must carry exactly the five P-17 tags."
  }

  # Story 2.2: the pipeline log alerts, named per P-16, on this environment's
  # Application Insights and action group.
  assert {
    condition = { for metric, alert in output.metric_alerts : metric => alert.name } == {
      poison_message    = "babaloo-sea-lng-ar-01"
      stuck_invoices    = "babaloo-sea-lng-ar-02"
      di_pages_used_pct = "babaloo-sea-lng-ar-03"
    }
    error_message = "the dev pipeline alerts must be ar-01 (poison_message), ar-02 (stuck_invoices) and ar-03 (di_pages_used_pct) (P-16)."
  }
  # Story 2.3 (AD-8): the dev pipeline identity alone is Cognitive Services User on the
  # shared DI resource, gets its endpoint and the dev cap of 100 pages, and Dj is
  # alerted at 80 % of it.
  assert {
    condition = (
      output.role_assignments["pipeline/cognitive/di"] == {
        role         = "Cognitive Services User"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21/providers/Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21"
        principal_id = "10000000-0000-0000-0000-000000000003"
      } &&
      length([for ra in output.role_assignments : ra if ra.role == "Cognitive Services User"]) == 1
    )
    error_message = "the dev pipeline identity, and no other, must have Cognitive Services User on the shared DI resource (AD-8)."
  }
  assert {
    condition = (
      module.app.pipeline_app_settings.DI_ENDPOINT == "https://babaloo-sea-lng-di-21.cognitiveservices.azure.com/" &&
      module.app.pipeline_app_settings.DI_MONTHLY_PAGE_CAP == "100" &&
      module.app.pipeline_app_settings.INVOICE_CURRENCY == "SGD" &&
      module.app.pipeline_app_settings.ACCOUNTS_BASE_URL == "https://babaloo-sea-lng-func-04.azurewebsites.net/api" &&
      module.app.pipeline_app_settings.ACCOUNTS_AUDIENCE == "api://30000000-0000-0000-0000-0000000000b1" &&
      module.app.staff_api_app_settings.POSTGRES_DATABASE == "invoicing_dev" &&
      module.app.staff_api_app_settings.POSTGRES_USER == "babaloo-sea-lng-id-02" &&
      module.app.staff_api_app_settings.DI_MONTHLY_PAGE_CAP == "100" &&
      module.app.staff_api_app_settings.INVOICE_CURRENCY == "SGD"
    )
    error_message = "the dev pipeline must call the shared DI endpoint with a cap of 100 pages a month in SGD (AD-8) and post to its own accounts-sim (Story 3.2), and staff-api (Story 2.8) must sign in to the dev database as its own identity with the same cap and currency."
  }
  assert {
    condition = alltrue([
      for metric, binding in {
        poison_message    = { event = "poison.done", measure = null, operator = "GreaterThan", threshold = 0 }
        stuck_invoices    = { event = "sweeper.done", measure = "stuck", operator = "GreaterThan", threshold = 0 }
        di_pages_used_pct = { event = "extract.di_usage", measure = "pages_used_pct", operator = "GreaterThanOrEqual", threshold = 80 }
      } :
      startswith(output.metric_alerts[metric].criteria.query, "traces\n| where message startswith \"${binding.event} \"") &&
      output.metric_alerts[metric].criteria.metric_measure_column == binding.measure &&
      output.metric_alerts[metric].criteria.operator == binding.operator &&
      output.metric_alerts[metric].criteria.threshold == binding.threshold
    ])
    error_message = "the dev alerts must read poison.done (any), sweeper.done (stuck above 0) and extract.di_usage (pages_used_pct at 80 % of the cap) (AD-17)."
  }
  assert {
    condition = alltrue([
      for alert in output.metric_alerts :
      alert.scopes == toset(["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/components/babaloo-sea-lng-appi-01"]) &&
      alert.action_group_ids == ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-01"] &&
      alert.tags.environment == "dev" && length(alert.tags) == 5
    ])
    error_message = "the dev pipeline alerts must watch dev's Application Insights, notify dev's action group and carry the five P-17 tags."
  }

  # OCR-129: staff-api reads pgp-private-key from the dev private-key vault in rg-22,
  # and no role on it comes from Terraform.
  assert {
    condition     = module.naming.private_key_vault_name == "babaloo-sea-lng-kv-22"
    error_message = "the dev private-key vault must be kv-22 (OCR-129)."
  }
  assert {
    condition     = module.app.staff_api_app_settings.PGP_PRIVATE_KEY_VAULT_URI == "https://babaloo-sea-lng-kv-22.vault.azure.net/"
    error_message = "staff-api must be told the dev private-key vault's URI, kv-22 (OCR-129)."
  }
  assert {
    condition     = length([for ra in output.role_assignments : ra if strcontains(ra.scope, "pgp-private-key")]) == 0
    error_message = "Terraform must grant no role on pgp-private-key (OCR-129: operator step 4b grants staff-api)."
  }

  # Story 1.5: the apps sample at their own ratio (default 0.5).
  assert {
    condition     = module.app.telemetry_sampling_ratio == 0.5
    error_message = "dev apps must sample at telemetry_sampling_ratio (default 0.5)."
  }

  # Story 2.7: built-in auth on staff-api, through the bootstrap's app registration.
  assert {
    condition = (
      output.staff_api_auth.client_id == "30000000-0000-0000-0000-0000000000a1" &&
      output.staff_api_auth.site_id == output.function_apps["staff_api"].resource_id &&
      output.staff_api_auth.site_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-02" &&
      output.staff_api_auth.require_authentication &&
      output.staff_api_auth.open_id_issuer == "https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111/v2.0"
    )
    error_message = "dev staff-api must require Entra sign-in through staff_api_client_id, single tenant (AD-14)."
  }
  # Story 3.1: built-in auth on accounts-sim admits only the dev pipeline identity, with
  # a token for accounts-sim's own app registration; it signs in to the dev database
  # as its own identity.
  assert {
    condition = (
      output.accounts_sim_auth.client_id == "30000000-0000-0000-0000-0000000000b1" &&
      output.accounts_sim_auth.allowed_audiences == ["api://30000000-0000-0000-0000-0000000000b1"] &&
      output.accounts_sim_auth.allowed_principal_ids == [local.foundation.identities["pipeline"].principal_id] &&
      output.accounts_sim_auth.site_id == output.function_apps["accounts_sim"].resource_id &&
      output.accounts_sim_auth.site_id == "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/Microsoft.Web/sites/babaloo-sea-lng-func-04" &&
      output.accounts_sim_auth.unauthenticated_client_action == "Return401" &&
      module.app.accounts_sim_app_settings.POSTGRES_USER == local.foundation.identities["accounts_sim"].name &&
      module.app.accounts_sim_app_settings.PIPELINE_PRINCIPAL_ID == local.foundation.identities["pipeline"].principal_id
    )
    error_message = "dev accounts-sim must accept only the dev pipeline identity's token for its own app registration (AD-10), and sign in to the database as its own identity."
  }
}
