variable "environment" {
  description = "dev or prod; also the APP_ENVIRONMENT app setting."
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod."
  }
}

variable "location" {
  description = "Azure region for every resource."
  type        = string
}

variable "resource_group_id" {
  description = "Resource id of the environment's resource group (from <env>/foundation)."
  type        = string
}

variable "app_names" {
  description = "Per app: plan, function app and deployment container names, from the naming module (app_names output)."
  type = map(object({
    plan                 = string
    function_app         = string
    deployment_container = string
  }))

  validation {
    condition     = toset(keys(var.app_names)) == toset(["supplier_api", "staff_api", "pipeline", "accounts_sim"])
    error_message = "app_names must have exactly the keys supplier_api, staff_api, pipeline and accounts_sim."
  }
}

variable "identities" {
  description = "The four runtime identities from <env>/foundation, keyed by app (name, resource id, principal id, client id). The name is also the identity's PostgreSQL login (AD-11)."
  type = map(object({
    name         = string
    resource_id  = string
    principal_id = string
    client_id    = string
  }))

  validation {
    condition     = toset(keys(var.identities)) == toset(["supplier_api", "staff_api", "pipeline", "accounts_sim"])
    error_message = "identities must have exactly the keys supplier_api, staff_api, pipeline and accounts_sim."
  }
}

variable "storage_account" {
  description = "The environment's storage account from <env>/foundation (name and resource id)."
  type = object({
    name        = string
    resource_id = string
  })
}

variable "database" {
  description = "This environment's database on the shared PostgreSQL server, from <env>/foundation (name and server FQDN)."
  type = object({
    name = string
    fqdn = string
  })
}

variable "key_vault" {
  description = "The environment's Key Vault from <env>/foundation (resource id and URI)."
  type = object({
    resource_id = string
    uri         = string
  })
}

variable "application_insights_id" {
  description = "Resource id of the environment's Application Insights (Monitoring Metrics Publisher scope)."
  type        = string
}

variable "action_group_id" {
  description = "Resource id of the environment's action group from <env>/foundation; every metric alert notifies it (AD-17: all alerts go to Dj)."
  type        = string
}

variable "metric_alert_names" {
  description = "Metric alert rule names from the naming module (metric_alert_names output), keyed by metric: poison_message and stuck_invoices (P-16)."
  type        = map(string)

  validation {
    condition     = toset(keys(var.metric_alert_names)) == toset(["poison_message", "stuck_invoices"])
    error_message = "metric_alert_names must have exactly the keys poison_message and stuck_invoices."
  }
}

variable "application_insights_connection_string" {
  description = "Application Insights connection string. Not a credential (local auth is off, AD-17), but kept out of logs."
  type        = string
  sensitive   = true
}

variable "telemetry_sampling_ratio" {
  description = "Fraction of traces each app keeps (TELEMETRY_SAMPLING_RATIO); below 1 so sampling is on (AD-17, azure.md rule 16)."
  type        = number
  # [ASSUMPTION] Half the traces until calibrated against the 0.08 GB/day cap (AD-17).
  default = 0.5

  validation {
    condition     = var.telemetry_sampling_ratio > 0 && var.telemetry_sampling_ratio < 1
    error_message = "telemetry_sampling_ratio must be between 0 and 1 (exclusive) so sampling is on."
  }
}

variable "tags" {
  description = "The five P-17 tags, from the naming module."
  type        = map(string)

  validation {
    condition = alltrue([
      for key in ["owner", "costCentre", "environment", "application", "dataClassification"] :
      length(trimspace(lookup(var.tags, key, ""))) > 0
    ])
    error_message = "tags must carry non-empty owner, costCentre, environment, application and dataClassification."
  }
}
