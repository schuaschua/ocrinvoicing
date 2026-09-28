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
      application_insights_connection_string = "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://southeastasia-0.in.applicationinsights.azure.com/"
    }
  }
}

variables {
  owner               = "test-owner"
  cost_centre         = "test-cc"
  application         = "test-app"
  data_classification = "test-class"
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
      "Monitoring Metrics Publisher",
    ]) && length(output.role_assignments) == 31
    error_message = "only the AD-17 runtime roles, plus Blob Data Owner on the two Functions host containers (platform requirement), may be assigned (DI and ACS come with Stories 2.3 and 5.2)."
  }
  assert {
    condition = alltrue([
      for key, ra in output.role_assignments : ra.principal_id == local.foundation.identities[split("/", key)[0]].principal_id
    ])
    error_message = "each role must go to the identity of the app it is for."
  }
  assert {
    condition     = alltrue([for ra in output.role_assignments : startswith(ra.scope, "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01/providers/")])
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

  # Story 1.5: the apps sample at their own ratio (default 0.5).
  assert {
    condition     = module.app.telemetry_sampling_ratio == 0.5
    error_message = "dev apps must sample at telemetry_sampling_ratio (default 0.5)."
  }
}
