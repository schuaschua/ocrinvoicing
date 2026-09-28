# AD-17 step 4: one environment's foundation. Four app identities, storage,
# Key Vault with the HMAC key and its audit log, Log Analytics, Application Insights
# with alerting on custom metric dimensions, the action group and the resource-group
# budget. Runtime role assignments belong to
# <env>/app (step 7); the PGP key pair is an operator step (4b).

locals {
  containers = ["images", "corrections"]
  # The Functions host's own containers (AzureWebJobsStorage: keys, leases, timer
  # state). A platform requirement beyond the AD-17 table (overnight decision, spine
  # update pending); created here so <env>/app can scope roles to exactly these two.
  host_containers = ["azure-webjobs-hosts", "azure-webjobs-secrets"]
  queues          = ["q-quality", "q-extract", "q-validate", "q-post"]
  tables          = ["supplierlinks", "uploadkeys", "supplierreminders"]

  # 7-day soft delete for blobs and containers (AD-15).
  blob_properties = {
    delete_retention_policy = {
      enabled = true
      days    = var.blob_soft_delete_days
    }
    container_delete_retention_policy = {
      enabled = true
      days    = var.blob_soft_delete_days
    }
  }

  # Key Vault audit events (every secret read and change) to this environment's
  # workspace (azure.md rule 15, Story 1.5). Only the category needed: no metrics.
  key_vault_diagnostic_settings = {
    audit = {
      name                           = "diag-${var.names.key_vault}"
      workspace_resource_id          = module.log_analytics.resource_id
      log_categories                 = ["AuditEvent"]
      log_groups                     = []
      metric_categories              = []
      log_analytics_destination_type = "Dedicated"
    }
  }

  # AD-17: Storage queue metrics have no per-queue breakdown, so the queue and pipeline
  # alerts use custom metrics, whose dimensions Application Insights drops unless this
  # is on ("alerting on custom metric dimensions").
  custom_metrics_opted_in_type = "WithDimensions"

  # No ingestion sampling: the apps already sample in OpenTelemetry (TELEMETRY_SAMPLING_RATIO,
  # infra/modules/env-app), and sampling twice would compound (0.5 x 0.5 = 25%).
  app_insights_ingestion_sampling_percentage = 100

  # Delete images and corrections 30 days after creation (AD-15, P-11).

  lifecycle_rules = {
    retention = {
      enabled = true
      name    = "delete-images-and-corrections"
      actions = {
        base_blob = {
          delete_after_days_since_creation_greater_than = var.blob_lifecycle_delete_days
        }
      }
      filters = {
        blob_types   = ["blockBlob"]
        prefix_match = [for name in local.containers : "${name}/"]
      }
    }
  }
}

# --- Identities ---------------------------------------------------------------

module "identities" {
  source   = "Azure/avm-res-managedidentity-userassignedidentity/azurerm"
  version  = "0.5.2"
  for_each = var.identity_names

  name                = each.value
  location            = var.location
  resource_group_name = var.resource_group_name
  enable_telemetry    = true
  tags                = var.tags
}

# --- Storage (AD-2, AD-6, AD-15) ------------------------------------------------

module "storage" {
  source  = "Azure/avm-res-storage-storageaccount/azurerm"
  version = "0.10.0"

  name                            = var.names.storage_account
  location                        = var.location
  parent_id                       = var.resource_group_id
  account_kind                    = "StorageV2"
  account_sku_name                = "Standard_LRS"
  access_tier                     = "Hot"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  # Flex apps reach storage over public endpoints (no VNet in the PoC); Entra auth only.
  public_network_access_enabled = true
  network_rules = {
    default_action = "Allow"
    bypass         = ["AzureServices"]
  }

  blob_properties                = local.blob_properties
  storage_management_policy_rule = local.lifecycle_rules

  containers = { for name in concat(local.containers, local.host_containers) : name => { name = name } }
  queues     = { for name in local.queues : name => { name = name } }
  tables     = { for name in local.tables : name => { name = name } }

  enable_telemetry = true
  tags             = var.tags
}

# --- Key Vault and the HMAC key (AD-11) -------------------------------------------

resource "random_password" "hmac_key" {
  length  = 64
  special = false
}

module "key_vault" {
  source  = "Azure/avm-res-keyvault-vault/azurerm"
  version = "0.11.0"

  name                           = var.names.key_vault
  location                       = var.location
  resource_group_name            = var.resource_group_name
  tenant_id                      = var.tenant_id
  sku_name                       = "standard"
  legacy_access_policies_enabled = false
  public_network_access_enabled  = true
  network_acls = {
    default_action = "Allow"
    bypass         = "AzureServices"
  }
  soft_delete_retention_days = 7
  purge_protection_enabled   = true

  role_assignments = {
    deploy_secrets_officer = {
      role_definition_id_or_name = "Key Vault Secrets Officer"
      principal_id               = var.deploy_principal_id
      principal_type             = "ServicePrincipal"
    }
  }
  wait_for_rbac_before_secret_operations = {
    create = "60s"
  }

  secrets = {
    hmac_key = {
      name         = "hmac-key"
      content_type = "text/plain"
      tags         = var.tags
    }
  }
  secrets_value = {
    hmac_key = random_password.hmac_key.result
  }

  diagnostic_settings = local.key_vault_diagnostic_settings

  enable_telemetry = true
  tags             = var.tags
}

# --- Monitoring (AD-17) -------------------------------------------------------------

module "log_analytics" {
  source  = "Azure/avm-res-operationalinsights-workspace/azurerm"
  version = "0.5.1"

  name                                                 = var.names.log_analytics
  location                                             = var.location
  resource_group_name                                  = var.resource_group_name
  log_analytics_workspace_sku                          = "PerGB2018"
  log_analytics_workspace_retention_in_days            = var.log_retention_days
  log_analytics_workspace_daily_quota_gb               = var.log_analytics_daily_quota_gb
  log_analytics_workspace_local_authentication_enabled = false
  log_analytics_workspace_internet_ingestion_enabled   = true
  log_analytics_workspace_internet_query_enabled       = true
  enable_telemetry                                     = true
  tags                                                 = var.tags
}

module "application_insights" {
  source  = "Azure/avm-res-insights-component/azurerm"
  version = "0.4.0"

  name                          = var.names.application_insights
  location                      = var.location
  resource_group_name           = var.resource_group_name
  workspace_id                  = module.log_analytics.resource_id
  application_type              = "web"
  sampling_percentage           = local.app_insights_ingestion_sampling_percentage
  retention_in_days             = var.log_retention_days
  local_authentication_disabled = true
  enable_telemetry              = true
  tags                          = var.tags
}

# azapi: neither azurerm_application_insights nor the AVM module has an argument for
# CustomMetricsOptedInType (azurerm issue 6901), so it is patched onto the component
# the module owns. The property is missing from the published API schema;
# azapi_update_resource does not validate its body against that schema.
resource "azapi_update_resource" "application_insights_custom_metric_dimensions" {
  type        = "Microsoft.Insights/components@2020-02-02"
  resource_id = module.application_insights.resource_id
  body = {
    properties = {
      CustomMetricsOptedInType = local.custom_metrics_opted_in_type
    }
  }

  # An azurerm update of the component PUTs it without this property and can reset it,
  # so the patch runs again whenever the component's managed settings change.
  lifecycle {
    replace_triggered_by = [terraform_data.application_insights_settings]
  }
}

# What the AVM module sets on the component; a change means azurerm updated it.
resource "terraform_data" "application_insights_settings" {
  input = {
    resource_id         = module.application_insights.resource_id
    tags                = var.tags
    workspace_id        = module.log_analytics.resource_id
    sampling_percentage = local.app_insights_ingestion_sampling_percentage
    retention_in_days   = var.log_retention_days
  }
}

resource "azurerm_monitor_action_group" "this" {
  name                = var.names.action_group
  resource_group_name = var.resource_group_name
  short_name          = var.names.action_group_shortname

  email_receiver {
    name                    = "owner"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }

  tags = var.tags
}

# --- Cost (azure.md rule 17) ---------------------------------------------------------

# Budgets start on the first day of the month they are created in; Azure rejects
# a start date in the past on create, so it is not a fixed value.
resource "time_static" "budget_start" {}

locals {
  budget_start_date = "${formatdate("YYYY-MM", time_static.budget_start.rfc3339)}-01T00:00:00Z"
}

resource "azurerm_consumption_budget_resource_group" "this" {
  name              = var.names.budget
  resource_group_id = var.resource_group_id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = local.budget_start_date
  }

  dynamic "notification" {
    for_each = var.budget_thresholds

    content {
      enabled        = true
      operator       = "GreaterThanOrEqualTo"
      threshold      = notification.value.threshold
      threshold_type = notification.value.threshold_type
      contact_emails = [var.alert_email]
      contact_groups = [azurerm_monitor_action_group.this.id]
    }
  }

  # Azure rejects changing the start of a running budget.
  lifecycle {
    ignore_changes = [time_period]
  }
}
