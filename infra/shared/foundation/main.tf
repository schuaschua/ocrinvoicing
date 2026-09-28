# AD-17 step 2: resources shared by Dev and Prod (AD-8, AD-12, AD-16).

module "naming" {
  source = "../../modules/naming"

  environment         = local.environment
  number_base         = local.number_base
  owner               = var.owner
  cost_centre         = var.cost_centre
  application         = var.application
  data_classification = var.data_classification
}

# Created by infra/bootstrap/state-backend.sh (AD-17 step 1) and adopted here
# (azure.md rule 31). It holds only this stack's resources; the state account and
# the deploy identities live in the bootstrap-only group babaloo-sea-lng-rg-22.
import {
  to = azurerm_resource_group.this
  id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${local.names.resource_group}"
}

resource "azurerm_resource_group" "this" {
  name     = local.names.resource_group
  location = var.location
  tags     = local.tags
}

# --- PostgreSQL (AD-11, AD-12) ------------------------------------------------------

module "postgres" {
  source  = "Azure/avm-res-dbforpostgresql-flexibleserver/azurerm"
  version = "0.2.3"

  name                          = local.names.postgres_server
  location                      = var.location
  resource_group_name           = azurerm_resource_group.this.name
  sku_name                      = local.postgres.sku_name
  server_version                = local.postgres.server_version
  storage_mb                    = local.postgres.storage_mb
  backup_retention_days         = local.postgres.backup_retention_days
  geo_redundant_backup_enabled  = local.postgres.geo_redundant_backup_enabled
  auto_grow_enabled             = local.postgres.auto_grow_enabled
  high_availability             = null
  zone                          = null
  public_network_access_enabled = true

  authentication   = local.postgres_authentication
  ad_administrator = local.postgres_ad_administrator

  databases = {
    for env, name in local.databases : env => {
      name      = name
      charset   = "UTF8"
      collation = "en_US.utf8"
    }
  }
  firewall_rules = local.postgres_firewall_rules
  server_configuration = {
    extensions = {
      name   = "azure.extensions"
      config = local.postgres_extensions
    }
  }

  enable_telemetry = true
  tags             = local.tags
}

# Separate from the module's configuration so the two server parameter updates run
# one after the other (Flexible Server rejects concurrent parameter changes).
resource "azurerm_postgresql_flexible_server_configuration" "require_secure_transport" {
  name      = "require_secure_transport"
  server_id = module.postgres.resource_id
  value     = "ON"

  depends_on = [module.postgres]
}

# --- Document Intelligence F0 (AD-8) -----------------------------------------------------

module "document_intelligence" {
  source  = "Azure/avm-res-cognitiveservices-account/azurerm"
  version = "0.11.1"

  name                          = local.names.document_intelligence
  location                      = var.location
  parent_id                     = azurerm_resource_group.this.id
  kind                          = "FormRecognizer"
  sku_name                      = "F0"
  custom_subdomain_name         = local.names.document_intelligence
  local_auth_enabled            = false
  public_network_access_enabled = true
  enable_telemetry              = true
  tags                          = local.tags
}

# --- ACS Email (AD-16) ---------------------------------------------------------------------

module "email" {
  source  = "Azure/avm-res-communication-emailservice/azurerm"
  version = "0.3.0"

  name          = local.names.email_service
  location      = "global"
  parent_id     = azurerm_resource_group.this.id
  data_location = local.communication_data_location

  email_communication_service_domains = {
    custom = {
      name                             = var.email_custom_domain
      domain_management                = "CustomerManaged"
      user_engagement_tracking_enabled = false
    }
  }

  enable_telemetry = true
  tags             = local.tags
}

resource "azurerm_communication_service" "this" {
  name                = local.names.communication_service
  resource_group_name = azurerm_resource_group.this.name
  data_location       = local.communication_data_location
  tags                = local.tags
}

# azapi: azurerm_communication_service has no argument for disableLocalAuth, so the
# access keys are switched off with a patch on the resource azurerm owns.
resource "azapi_update_resource" "communication_service_local_auth" {
  type        = "Microsoft.Communication/communicationServices@2025-09-01"
  resource_id = azurerm_communication_service.this.id
  body = {
    properties = {
      disableLocalAuth = true
    }
  }

  depends_on = [azurerm_communication_service_email_domain_association.custom]
}

# Azure refuses to link a domain before its DNS records are verified, so the link
# waits for email_domain_link_enabled (bootstrap README, shared/foundation).
resource "azurerm_communication_service_email_domain_association" "custom" {
  count = var.email_domain_link_enabled ? 1 : 0

  communication_service_id = azurerm_communication_service.this.id
  email_service_domain_id  = module.email.domain_resource_ids["custom"]
}

# --- Alerts (AD-17, Story 1.5) ----------------------------------------------------------------

# ag-21: emails Dj. The shared resource-group budget below and the $8 subscription
# budget (infra/bootstrap/budget-and-roles.sh, given this group's id) notify through it.
resource "azurerm_monitor_action_group" "this" {
  name                = local.names.action_group
  resource_group_name = azurerm_resource_group.this.name
  short_name          = local.names.action_group_shortname

  email_receiver {
    name                    = "owner"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }

  tags = local.tags
}

# --- Cost (azure.md rule 17) ------------------------------------------------------------------

# Budgets start on the first day of the month they are created in; Azure rejects
# a start date in the past on create, so it is not a fixed value.
resource "time_static" "budget_start" {}

locals {
  budget_start_date = "${formatdate("YYYY-MM", time_static.budget_start.rfc3339)}-01T00:00:00Z"
}

resource "azurerm_consumption_budget_resource_group" "this" {
  name              = local.names.budget
  resource_group_id = azurerm_resource_group.this.id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = local.budget_start_date
  }

  dynamic "notification" {
    for_each = local.budget_thresholds

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
