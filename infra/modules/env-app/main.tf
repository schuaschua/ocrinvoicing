# AD-17 step 7: one environment's four Flex Consumption apps (AD-1), each in its own
# plan with its own user-assigned identity from <env>/foundation, their deployment
# containers, app settings (no secrets) and the AD-17 runtime role assignments.
# The ACS Email Sender assignment (5.2) is added later; Story 1.5 added the telemetry
# settings, Story 2.2 the pipeline's poison_message and stuck_invoices alerts,
# Story 2.3 the pipeline's DI settings, its Cognitive Services User assignment and the
# di_pages_used_pct alert, Story 2.7 staff-api's built-in auth, and Story 3.1
# accounts-sim's built-in auth and database settings, and Story 3.2 the pipeline's
# accounts settings.

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
  # Flex's Python default is 1 HTTP request per instance, so each parallel request of a
  # page load started its own cold instance (Dev walkthrough 2026-09-30). supplier-api
  # uses no PostgreSQL (AD-6), so 8 lets one instance serve a whole page load; staff-api
  # takes as many as its PostgreSQL pool holds (STAFF_POOL_SIZE = 4), so no request
  # waits for a connection (Dj, 2026-09-30).
  http_per_instance_concurrency = {
    supplier_api = 8
    staff_api    = 4
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
    # OCR-129: pgp-private-key is in a separate private-key vault (not a secret: its URI).
    # Story 2.8: staff-api's own database login (its identity's name, Entra token, no
    # password), and the cap and currency the admin queue shows.
    staff_api = {
      STORAGE_ACCOUNT_NAME      = var.storage_account.name
      KEY_VAULT_URI             = var.key_vault.uri
      PGP_PRIVATE_KEY_VAULT_URI = var.private_key_vault_uri
      POSTGRES_HOST             = var.database.fqdn
      POSTGRES_DATABASE         = var.database.name
      POSTGRES_USER             = var.identities["staff_api"].name
      DI_MONTHLY_PAGE_CAP       = tostring(var.di_monthly_page_cap)
      INVOICE_CURRENCY          = var.invoice_currency
    }
    # Story 2.1: the database and the login the pipeline signs in as with an Entra
    # token (its identity's name, AD-11); no password setting exists.
    pipeline = {
      STORAGE_ACCOUNT_NAME = var.storage_account.name
      KEY_VAULT_URI        = var.key_vault.uri
      POSTGRES_HOST        = var.database.fqdn
      POSTGRES_DATABASE    = var.database.name
      POSTGRES_USER        = var.identities["pipeline"].name
      # Story 2.3 (AD-8): the shared DI resource's custom subdomain (managed identity,
      # no key), this environment's monthly page cap and the invoice currency.
      DI_ENDPOINT         = var.document_intelligence_endpoint
      DI_MONTHLY_PAGE_CAP = tostring(var.di_monthly_page_cap)
      INVOICE_CURRENCY    = var.invoice_currency
      # Story 3.2 (AD-10): this environment's accounts-sim, by its default host name
      # (the app's own output would be a cycle), and the audience of the token the
      # pipeline sends it: accounts-sim's own registration. The real system changes
      # only these two.
      ACCOUNTS_BASE_URL = "https://${var.app_names["accounts_sim"].function_app}.azurewebsites.net/api"
      ACCOUNTS_AUDIENCE = "api://${var.accounts_sim_client_id}"
    }
    # Story 3.1 (AD-10, AD-11): accounts-sim's own database login (its identity's
    # name, Entra token, no password), and the one principal it serves, this
    # environment's pipeline identity (checked again in code).
    accounts_sim = {
      POSTGRES_HOST         = var.database.fqdn
      POSTGRES_DATABASE     = var.database.name
      POSTGRES_USER         = var.identities["accounts_sim"].name
      PIPELINE_PRINCIPAL_ID = var.identities["pipeline"].principal_id
    }
  }

  app_settings = { for app in local.apps : app => merge(local.common_settings[app], local.app_specific_settings[app]) }

  # --- Runtime roles (AD-17, azure.md rule 9), each at the narrowest scope --------------

  container_scopes = {
    for name in ["images", "corrections"] : name => "${local.storage_id}/blobServices/default/containers/${name}"
  }
  # Secrets are scoped one by one. hmac-key comes from <env>/foundation, pgp-public-key
  # from operator step 4b. pgp-private-key is not in this vault: step 4b stores it in
  # the environment's private-key vault in rg-22 and gives staff-api, and nobody else,
  # read on it (OCR-129, AD-11). Terraform grants nothing on it.
  secret_scopes = {
    for name in ["hmac-key", "pgp-public-key"] : name => "${var.key_vault.resource_id}/secrets/${name}"
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
    # staff-api encrypts and fingerprints an admin's corrected bank field (AD-3 Correct,
    # AD-11). Its read on pgp-private-key, to decrypt for admins, is granted by
    # operator step 4b in the private-key vault (OCR-129).
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
    # Story 2.3 (AD-8): the one DI caller, on the shared F0 resource in rg-21. The deploy
    # identity may assign only this role there (bootstrap rbac-step3.sh, AD-17 step 3).
    "pipeline/cognitive/di" = {
      app = "pipeline", role = "Cognitive Services User", scope = var.document_intelligence_id
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
  # The HTTP concurrency below is set by azapi_resource_action.http_concurrency (the
  # module has no input for it); the module's own updates must keep it.
  ignore_body_changes = {
    web_sites = ["properties.functionAppConfig.scaleAndConcurrency.triggers"]
  }

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

# azapi, not the AVM module: avm-res-web-site 0.23.0 (the latest) has no input for
# scaleAndConcurrency.triggers. A PATCH on the site the module owns (terraform.md rule
# 2), which ignores the triggers path (ignore_body_changes above); a full PUT would
# re-send siteConfig fields Flex rejects (ARM 51021). Flex replaces functionAppConfig
# as a whole ("Runtime name and version must be provided", Dev build #20), so the
# PATCH carries all of it, with the same values the module is given, as
# `az functionapp scale config set` does.
resource "azapi_resource_action" "http_concurrency" {
  for_each = local.http_per_instance_concurrency

  type        = "Microsoft.Web/sites@2025-03-01"
  resource_id = module.function_apps[each.key].resource_id
  method      = "PATCH"
  body = {
    properties = {
      functionAppConfig = {
        deployment = {
          storage = {
            type  = "blobcontainer"
            value = "${local.blob_endpoint}/${azurerm_storage_container.deployment[each.key].name}"
            authentication = {
              type                           = "userassignedidentity"
              userAssignedIdentityResourceId = var.identities[each.key].resource_id
            }
          }
        }
        runtime = {
          name    = local.runtime_name
          version = local.runtime_version
        }
        # The platform's value on these sites (read 2026-09-30); sent so the PATCH
        # can't reset it.
        siteUpdateStrategy = { type = "Recreate" }
        scaleAndConcurrency = {
          maximumInstanceCount = local.maximum_instance_counts[each.key]
          instanceMemoryMB     = local.instance_memory_mb
          triggers             = { http = { perInstanceConcurrency = each.value } }
        }
      }
    }
  }
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

# --- Built-in auth on staff-api (AD-14, Story 2.7) ---------------------------------------
#
# Entra sign-in, single tenant, through the bootstrap's `staff-api` app registration
# (assignment required, app roles, ID tokens on; infra/bootstrap/app-registrations.sh).
# ID tokens only, so there is no client secret. The redirect URI is operator step 8
# (infra/bootstrap/README.md). accounts-sim's auth is below (AD-10, Story 3.1).

data "azapi_client_config" "current" {}

locals {
  staff_api_auth = {
    platform = {
      enabled        = true
      runtimeVersion = "~1"
    }
    globalValidation = {
      requireAuthentication = true
      # A browser page is redirected to Entra; a call carrying
      # `X-Requested-With: XMLHttpRequest` (the staff app sends it on every call) gets
      # 401 instead, which the app shows as its session-ended dialog (AD-14). That
      # split is the platform's own behaviour for this action. [ASSUMPTION] To confirm
      # on the first Dev deploy (spine Open Questions; bootstrap README step 8 check).
      unauthenticatedClientAction = "RedirectToLoginPage"
      redirectToProvider          = "azureactivedirectory"
      # The only anonymous route: liveness (Story 1.3).
      excludedPaths = ["/api/health"]
    }
    identityProviders = {
      azureActiveDirectory = {
        enabled = true
        registration = {
          clientId = var.staff_api_client_id
          # Single tenant: only this tenant's issuer is accepted.
          openIdIssuer = "https://login.microsoftonline.com/${data.azapi_client_config.current.tenant_id}/v2.0"
        }
      }
    }
    login = {
      # The API reads only the platform's X-MS-CLIENT-PRINCIPAL header, never stored
      # tokens, so no token is kept server side. The session cookie's SameSite
      # (AD-14: Lax) is the platform's; authsettingsV2 has no setting for it.
      tokenStore = { enabled = false }
      # A working day: the session ends 8 hours after sign-in, whatever the activity,
      # and the staff app then shows its session-ended dialog.
      cookieExpiration = {
        convention       = "FixedTime"
        timeToExpiration = "08:00:00"
      }
      # A deep link (e.g. an alert email's) keeps its #fragment through the sign-in.
      preserveUrlFragmentsForLogins = true
    }
    httpSettings = {
      requireHttps = true
      routes       = { apiPrefix = "/.auth" }
      forwardProxy = { convention = "NoProxy" }
    }
  }
}

# azapi, not azurerm: the sites are AVM azapi resources on Flex Consumption, and azurerm
# has no standalone auth-settings resource for them (auth_settings_v2 exists only
# inside its own site resources). authsettingsV2 is a site config child that always
# exists and can't be deleted, so it is updated in place, like the AVM's own submodule.
resource "azapi_update_resource" "staff_api_auth" {
  type      = "Microsoft.Web/sites/config@2025-03-01"
  name      = "authsettingsV2"
  parent_id = module.function_apps["staff_api"].resource_id
  body      = { properties = local.staff_api_auth }
}

# --- Built-in auth on accounts-sim (AD-10, Story 3.1) -----------------------------------
#
# Only this environment's pipeline identity may call it: a managed-identity token for
# the bootstrap's `accounts-sim` app registration (audience api://<client id>), from the
# pipeline's principal (allowedPrincipals.identities). Human users and every other
# identity, the other environment's pipeline included, are refused with 403; a call
# without a token gets 401. The app checks the principal again (apps/accounts_sim).

locals {
  accounts_sim_auth = {
    platform = {
      enabled        = true
      runtimeVersion = "~1"
    }
    globalValidation = {
      requireAuthentication = true
      # An API with no pages: signed-out calls get 401, never a redirect. No route is
      # anonymous (accounts-sim has no health route).
      unauthenticatedClientAction = "Return401"
    }
    identityProviders = {
      azureActiveDirectory = {
        enabled = true
        registration = {
          clientId = var.accounts_sim_client_id
          # Single tenant. [ASSUMPTION] Managed-identity tokens are v1 (issuer
          # sts.windows.net); built-in auth accepts v1 and v2 tokens for this issuer.
          # To confirm on the first Dev deploy (plan 3.1 Design Notes).
          openIdIssuer = "https://sts.windows.net/${data.azapi_client_config.current.tenant_id}/v2.0"
        }
        validation = {
          allowedAudiences = ["api://${var.accounts_sim_client_id}"]
          defaultAuthorizationPolicy = {
            allowedPrincipals = {
              identities = [var.identities["pipeline"].principal_id]
            }
          }
        }
      }
    }
    login = {
      # Bearer tokens only; nothing is kept server side.
      tokenStore = { enabled = false }
    }
    httpSettings = {
      requireHttps = true
      routes       = { apiPrefix = "/.auth" }
      forwardProxy = { convention = "NoProxy" }
    }
  }
}

# azapi, not azurerm, for the same reason as staff_api_auth above.
resource "azapi_update_resource" "accounts_sim_auth" {
  type      = "Microsoft.Web/sites/config@2025-03-01"
  name      = "authsettingsV2"
  parent_id = module.function_apps["accounts_sim"].resource_id
  body      = { properties = local.accounts_sim_auth }
}

# --- Log alerts (AD-17): the pipeline's log events, sent to Dj ----------------------------
#
# Storage queue metrics have no per-queue breakdown, and the pipeline's OpenTelemetry
# custom metrics never reached Application Insights in Dev (plan fix-log-based-alerts),
# so these rules search the `traces` table for the log events that do arrive. Each
# query finds its event by the start of `message` and reads the event's fields from
# customDimensions (Dj, 2026-09-30). The pipeline logs these three events outside any
# trace, so sampling never drops them. The rules run as Azure Monitor in this
# subscription, so they need no managed identity. The custom metrics are still
# emitted; nothing alerts on them.

locals {
  resource_group_name = element(split("/", var.resource_group_id), 4)
}

# poison.done{queue}: any in the last hour, one alert per poison queue (AD-2).
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "poison_message" {
  name                    = var.metric_alert_names["poison_message"]
  resource_group_name     = local.resource_group_name
  location                = var.location
  scopes                  = [var.application_insights_id]
  description             = "A pipeline message failed 5 times and reached a poison queue (AD-2). Its invoice is in the admin queue as PROCESSING_FAILED, or the trigger logged a code (poison.done)."
  severity                = 2
  evaluation_frequency    = "PT15M"
  window_duration         = "PT1H"
  auto_mitigation_enabled = true

  criteria {
    query                   = <<-KQL
      traces
      | where message startswith "poison.done "
      | extend queue = tostring(customDimensions.queue)
      | project timestamp, queue
    KQL
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0

    # Split by queue: each poison queue fires on its own.
    dimension {
      name     = "queue"
      operator = "Include"
      values   = ["*"]
    }
  }

  action {
    action_groups = [var.action_group_id]
  }

  tags = var.tags
}

# sweeper.done with requeued + orphans above 0: the sweeper re-enqueued at least one
# stranded invoice (AD-2). It runs every 15 minutes and logs 0 on a clean sweep, so
# the alert resolves by itself.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "stuck_invoices" {
  name                    = var.metric_alert_names["stuck_invoices"]
  resource_group_name     = local.resource_group_name
  location                = var.location
  scopes                  = [var.application_insights_id]
  description             = "The sweeper found invoices stranded for over an hour and queued them again (AD-2). See the requeued and orphans fields of sweeper.done in the pipeline's logs."
  severity                = 2
  evaluation_frequency    = "PT15M"
  window_duration         = "PT30M"
  auto_mitigation_enabled = true

  criteria {
    query                   = <<-KQL
      traces
      | where message startswith "sweeper.done "
      | extend stuck = coalesce(toint(customDimensions.requeued), 0) + coalesce(toint(customDimensions.orphans), 0)
      | project timestamp, stuck
    KQL
    time_aggregation_method = "Maximum"
    metric_measure_column   = "stuck"
    operator                = "GreaterThan"
    threshold               = 0
  }

  action {
    action_groups = [var.action_group_id]
  }

  tags = var.tags
}

# extract.di_usage pages_used_pct: this environment's DI pages this month as a
# percentage of its cap (AD-8). The extract stage logs it after each analysis; the
# alert fires at 80 %.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "di_pages_used_pct" {
  name                    = var.metric_alert_names["di_pages_used_pct"]
  resource_group_name     = local.resource_group_name
  location                = var.location
  scopes                  = [var.application_insights_id]
  description             = "Document Intelligence pages used this month reached 80% of this environment's cap of ${var.di_monthly_page_cap} (AD-8). At 100% new invoices go to the admin queue as EXTRACTION_QUOTA until the month ends."
  severity                = 2
  evaluation_frequency    = "PT1H"
  window_duration         = "PT6H"
  auto_mitigation_enabled = true

  criteria {
    query                   = <<-KQL
      traces
      | where message startswith "extract.di_usage "
      | extend pages_used_pct = coalesce(todouble(customDimensions.pages_used_pct), 0.0)
      | project timestamp, pages_used_pct
    KQL
    time_aggregation_method = "Maximum"
    metric_measure_column   = "pages_used_pct"
    operator                = "GreaterThanOrEqual"
    threshold               = 80
  }

  action {
    action_groups = [var.action_group_id]
  }

  tags = var.tags
}
