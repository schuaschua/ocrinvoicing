variable "location" {
  description = "Azure region for every resource."
  type        = string
}

variable "resource_group_name" {
  description = "Name of the environment's resource group (created by the bootstrap, adopted by the root)."
  type        = string
}

variable "resource_group_id" {
  description = "Resource id of the environment's resource group."
  type        = string
}

variable "names" {
  description = "Resource names from the naming module (names output)."
  type = object({
    storage_account        = string
    key_vault              = string
    log_analytics          = string
    application_insights   = string
    action_group           = string
    action_group_shortname = string
    budget                 = string
  })
}

variable "identity_names" {
  description = "Runtime identity names keyed by app, from the naming module (identity_names output)."
  type        = map(string)

  validation {
    condition     = toset(keys(var.identity_names)) == toset(["supplier_api", "staff_api", "pipeline", "accounts_sim"])
    error_message = "identity_names must have exactly the keys supplier_api, staff_api, pipeline and accounts_sim."
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

variable "tenant_id" {
  description = "Entra tenant id for the Key Vault."
  type        = string
}

variable "deploy_principal_id" {
  description = "Object id of the environment's deploy identity; it gets Key Vault Secrets Officer on this vault only (AD-17 step 4)."
  type        = string
}

variable "alert_email" {
  description = "Email address that receives budget and monitoring alerts (Dj)."
  type        = string
}

variable "budget_amount" {
  description = "Monthly resource-group budget in the billing currency."
  type        = number

  validation {
    condition     = var.budget_amount > 0
    error_message = "budget_amount must be positive."
  }
}

variable "blob_soft_delete_days" {
  description = "Blob and container soft-delete retention in days (AD-15)."
  type        = number
  default     = 7
}

variable "blob_lifecycle_delete_days" {
  description = "Delete images and corrections this many days after creation (AD-15)."
  type        = number
  default     = 30
}

variable "log_analytics_daily_quota_gb" {
  description = "Log Analytics daily ingestion cap in GB (AD-17)."
  type        = number
  default     = 0.08
}

variable "log_retention_days" {
  description = "Log Analytics and Application Insights retention in days (AD-17)."
  type        = number
  default     = 30
}

variable "budget_thresholds" {
  description = "Resource-group budget notifications (azure.md rule 17): actual 90/100/110 and forecast 110."
  type = list(object({
    threshold      = number
    threshold_type = string
  }))
  default = [
    { threshold = 90, threshold_type = "Actual" },
    { threshold = 100, threshold_type = "Actual" },
    { threshold = 110, threshold_type = "Actual" },
    { threshold = 110, threshold_type = "Forecasted" },
  ]
}
