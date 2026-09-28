# AD-17 step 7: one environment's four Flex Consumption apps (AD-1), each in its own
# plan with its own user-assigned identity from <env>/foundation, their deployment
# containers, app settings (no secrets) and the AD-17 runtime role assignments.
# Built-in auth (Story 2.7), the DI Cognitive Services User assignment (2.3), the
# ACS Email Sender assignment (5.2) and the metric alert rules (2.2, 2.3) are added
# later; Story 1.5 added the telemetry settings.

locals {
  apps = toset(keys(var.app_names))

  # AD-1: Python 3.13 on Flex Consumption (FC1), on-demand instances only.
  plan_sku        = "FC1"
  runtime_name    = "python"
  runtime_version = "3.13"

  # AD-17 compute ceilings (azure.md rule 20); raising one is an architecture change.
  # pipeline runs one instance per function, so each stage handles one message at a time (AD-2).
  instance_memory_mb = 2048
  maximum_instance_counts = {
    supplier_api = 10
    staff_api    = 10
    pipeline     = 1
    accounts_sim = 10
  }

  storage_id    = var.storage_account.resource_id
  blob_endpoint = "https://${var.storage_account.name}.blob.core.windows.net"

  # --- App settings: identities and endpoints only, never secrets -----------------

  common_settings = {
    for app in local.apps : app => {
      APP_ENVIRONMENT = var.environment
      # The one identity every Azure SDK call in the app signs in as.
      AZURE_CLIENT_ID = var.identities[app].client_id
      # Application Insights has local auth off, so telemetry uses Entra (Monitoring Metrics Publisher).
      APPLICATIONINSIGHTS_AUTHENTICATION_STRING = "ClientId=${var.identities[app].client_id};Authorization=AAD"
      # OpenTelemetry sampling in the app (azure.md rule 16), the only sampling: the
      # Application Insights resource samples nothing at ingestion. The connection
      # string (APPLICATIONINSIGHTS_CONNECTION_STRING) is set by the AVM module.
      TELEMETRY_SAMPLING_RATIO = tostring(var.telemetry_sampling_ratio)
      # Host storage (AzureWebJobsStorage) through the same identity, never a key.
      AzureWebJobsStorage__accountName = var.storage_account.name
      AzureWebJobsStorage__credential  = "managedidentity"
      AzureWebJobsStorage__clientId    = var.identities[app].client_id
    }
  }

  # Each app's pydantic-settings class (backend/src/invoicing/apps/<app>/settings.py).
  app_specific_settings = {
    supplier_api = { STORAGE_ACCOUNT_NAME = var.storage_account.name }
    staff_api    = { STORAGE_ACCOUNT_NAME = var.storage_account.name, KEY_VAULT_URI = var.key_vault.uri }
    # Story 2.1: the database and the login the pipeline signs in as with an Entra
    # token (its identity's name, AD-11); no password setting exists.
    pipeline = {
      STORAGE_ACCOUNT_NAME = var.storage_account.name
      KEY_VAULT_URI        = var.key_vault.uri
      POSTGRES_HOST        = var.database.fqdn
      POSTGRES_DATABASE    = var.database.name
      POSTGRES_USER        = var.identities["pipeline"].name
    }
    accounts_sim = {}
  }

  app_settings = { for app in local.apps : app => merge(local.common_settings[app], local.app_specific_settings[app]) }

  # --- Runtime roles (AD-17, azure.md rule 9), each at the narrowest scope --------------

  container_scopes = {
    for name in ["images", "corrections"] : name => "${local.storage_id}/blobServices/default/containers/${name}"
  }
  # Secrets are scoped one by one so the pipeline never reads the PGP private key
  # (AD-11: only staff-api can decrypt). hmac-key comes from <env>/foundation, the
  # PGP pair from operator step 4b.
  secret_scopes = {
    for name in ["hmac-key", "pgp-public-key", "pgp-private-key"] : name => "${var.key_vault.resource_id}/secrets/${name}"
  }

  # Where AD-17 names no container, queue or table, the role covers the account's
  # blobs, queues or tables (each role is limited to its own service).
  listed_role_assignments = {
    "supplier_api/blob/images" = {
      app = "supplier_api", role = "Storage Blob Data Contributor", scope = local.container_scopes["images"]
    }
    "supplier_api/queue/q-quality" = {
      app = "supplier_api", role = "Storage Queue Data Message Sender", scope = "${local.storage_id}/queueServices/default/queues/q-quality"
    }
    "supplier_api/table/account" = {
      app = "supplier_api", role = "Storage Table Data Contributor", scope = local.storage_id
    }
    "staff_api/blob/images" = {
      app = "staff_api", role = "Storage Blob Data Contributor", scope = local.container_scopes["images"]
    }
    "staff_api/blob/corrections" = {
      app = "staff_api", role = "Storage Blob Data Contributor", scope = local.container_scopes["corrections"]
    }
    "staff_api/queue/account" = {
      app = "staff_api", role = "Storage Queue Data Message Sender", scope = local.storage_id
    }
    "staff_api/table/account" = {
      app = "staff_api", role = "Storage Table Data Contributor", scope = local.storage_id
    }
    # staff-api decrypts bank details for admins, and encrypts and fingerprints an
    # admin's corrected bank field (AD-3 Correct, AD-11), so it reads all three.
    "staff_api/secret/pgp-private-key" = {
      app = "staff_api", role = "Key Vault Secrets User", scope = local.secret_scopes["pgp-private-key"]
    }
    "staff_api/secret/pgp-public-key" = {
      app = "staff_api", role = "Key Vault Secrets User", scope = local.secret_scopes["pgp-public-key"]
    }
    "staff_api/secret/hmac-key" = {
      app = "staff_api", role = "Key Vault Secrets User", scope = local.secret_scopes["hmac-key"]
    }
    "pipeline/blob/account" = {
      app = "pipeline", role = "Storage Blob Data Contributor", scope = local.storage_id
    }
    "pipeline/queue/account" = {
      app = "pipeline", role = "Storage Queue Data Contributor", scope = local.storage_id
    }
    "pipeline/table/account" = {
      app = "pipeline", role = "Storage Table Data Contributor", scope = local.storage_id
    }
    "pipeline/secret/pgp-public-key" = {
      app = "pipeline", role = "Key Vault Secrets User", scope = local.secret_scopes["pgp-public-key"]
    }
    "pipeline/secret/hmac-key" = {
      app = "pipeline", role = "Key Vault Secrets User", scope = local.secret_scopes["hmac-key"]
    }
  }

  # Every app: its own deployment container and its Application Insights.
  per_app_role_assignments = merge(
    {
      for app in local.apps : "${app}/blob/deployment" => {
        app   = app
        role  = "Storage Blob Data Owner"
        scope = "${local.storage_id}/blobServices/default/containers/${var.app_names[app].deployment_container}"
      }
    },
    {
      for app in local.apps : "${app}/monitoring/appi" => {
        app   = app
        role  = "Monitoring Metrics Publisher"
        scope = var.application_insights_id
      }
    },
  )

  # Platform requirement beyond the AD-17 table (overnight decision, spine update
  # pending): the Functions host signs in to AzureWebJobsStorage as the app identity and
  # needs Blob Data Owner on its own containers to start. Scoped to exactly the two host
  # containers (created by <env>/foundation), never the account.
  host_role_assignments = {
    for pair in setproduct(sort(tolist(local.apps)), ["azure-webjobs-hosts", "azure-webjobs-secrets"]) :
    "${pair[0]}/blob/${pair[1]}" => {
      app   = pair[0]
      role  = "Storage Blob Data Owner"
      scope = "${local.storage_id}/blobServices/default/containers/${pair[1]}"
    }
  }

  role_assignments = merge(local.listed_role_assignments, local.per_app_role_assignments, local.host_role_assignments)
}

# --- Deployment containers: where each app's package is published (AD-17 step 9) -----

resource "azurerm_storage_container" "deployment" {
  for_each = local.apps

  name                  = var.app_names[each.key].deployment_container
  storage_account_id    = local.storage_id
  container_access_type = "private"
}

# --- Plans and apps (AD-1) -----------------------------------------------------------

module "plans" {
  source   = "Azure/avm-res-web-serverfarm/azurerm"
  version  = "2.0.8"
  for_each = local.apps

  name      = var.app_names[each.key].plan
  location  = var.location
  parent_id = var.resource_group_id
  os_type   = "Linux"
  sku_name  = local.plan_sku
  # One on-demand plan per app; no zone redundancy (P-15).
  zone_balancing_enabled = false
  enable_telemetry       = true
  tags                   = var.tags
}

module "function_apps" {
  source   = "Azure/avm-res-web-site/azurerm"
  version  = "0.23.0"
  for_each = local.apps

  name                     = var.app_names[each.key].function_app
  location                 = var.location
  parent_id                = var.resource_group_id
  service_plan_resource_id = module.plans[each.key].resource_id
  kind                     = "functionapp"
  os_type                  = "Linux"

  function_app_uses_fc1  = true
  fc1_runtime_name       = local.runtime_name
  fc1_runtime_version    = local.runtime_version
  instance_memory_in_mb  = local.instance_memory_mb
  maximum_instance_count = local.maximum_instance_counts[each.key]

  managed_identities = {
    user_assigned_resource_ids = [var.identities[each.key].resource_id]
  }
  # The platform reads the package from the app's own container as the app's identity.
  storage_container_type            = "blobContainer"
  storage_container_endpoint        = "${local.blob_endpoint}/${azurerm_storage_container.deployment[each.key].name}"
  storage_authentication_type       = "UserAssignedIdentity"
  storage_user_assigned_identity_id = var.identities[each.key].resource_id

  app_settings                           = local.app_settings[each.key]
  application_insights_connection_string = var.application_insights_connection_string

  # No VNet in the PoC; HTTPS only, and code deploys sign in with Entra, never basic auth.
  public_network_access_enabled            = true
  https_only                               = true
  ftp_publish_basic_authentication_enabled = false
  scm_publish_basic_authentication_enabled = false

  enable_telemetry = true
  tags             = var.tags

  # The platform reads the package from the deployment container and the host starts
  # against its host containers as the app identity, so those roles must exist first.
  depends_on = [azurerm_role_assignment.runtime]
}

# --- Runtime role assignments (AD-17) -------------------------------------------------

resource "azurerm_role_assignment" "runtime" {
  for_each = local.role_assignments

  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = var.identities[each.value.app].principal_id
  principal_type       = "ServicePrincipal"

  depends_on = [azurerm_storage_container.deployment]
}
