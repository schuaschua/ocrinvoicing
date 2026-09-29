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

variable "staff_api_client_id" {
  description = "Client (application) id of this environment's staff-api app registration, babaloo-sea-lng-staff-api-<env>, as infra/bootstrap/app-registrations.sh prints it (AD-14, AD-17 step 1). Not a secret."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.staff_api_client_id))
    error_message = "staff_api_client_id must be the app registration's client id: a lowercase UUID."
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

variable "private_key_vault_uri" {
  description = "URI of this environment's private-key vault in rg-22 (kv-22 dev, kv-23 prod), which holds only pgp-private-key (OCR-129). Built from the naming convention; not a secret. staff-api's PGP_PRIVATE_KEY_VAULT_URI setting."
  type        = string

  validation {
    condition     = can(regex("^https://[a-z0-9-]{3,24}\\.vault\\.azure\\.net/$", var.private_key_vault_uri))
    error_message = "private_key_vault_uri must be a Key Vault URI: https://<vault name>.vault.azure.net/."
  }
  validation {
    condition     = lower(var.private_key_vault_uri) != lower(var.key_vault.uri)
    error_message = "private_key_vault_uri must name the private-key vault, not the environment's vault (OCR-129)."
  }
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
  description = "Metric alert rule names from the naming module (metric_alert_names output), keyed by metric: poison_message, stuck_invoices and di_pages_used_pct (P-16)."
  type        = map(string)

  validation {
    condition     = toset(keys(var.metric_alert_names)) == toset(["poison_message", "stuck_invoices", "di_pages_used_pct"])
    error_message = "metric_alert_names must have exactly the keys poison_message, stuck_invoices and di_pages_used_pct."
  }
}

variable "document_intelligence_id" {
  description = "Resource id of the shared Document Intelligence F0 resource (shared/foundation, through <env>/foundation). The pipeline identity gets Cognitive Services User on it (AD-8)."
  type        = string

  validation {
    condition     = can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\\.CognitiveServices/accounts/[^/]+$", var.document_intelligence_id))
    error_message = "document_intelligence_id must be a Cognitive Services account's resource id."
  }
}

variable "document_intelligence_endpoint" {
  description = "Custom-subdomain endpoint of the shared Document Intelligence resource (managed identity only, AD-8); the pipeline's DI_ENDPOINT setting."
  type        = string

  validation {
    condition     = can(regex("^https://[a-z0-9-]+\\.cognitiveservices\\.azure\\.com/?$", var.document_intelligence_endpoint))
    error_message = "document_intelligence_endpoint must be the resource's custom subdomain: https://<name>.cognitiveservices.azure.com/."
  }
}

variable "di_monthly_page_cap" {
  description = "Pages this environment may analyse per calendar month on the shared F0 resource (AD-8: Dev 100, Prod 400); DI_MONTHLY_PAGE_CAP, and the di_pages_used_pct alert fires at 80 % of it."
  type        = number

  validation {
    condition     = var.di_monthly_page_cap > 0 && var.di_monthly_page_cap <= 500 && floor(var.di_monthly_page_cap) == var.di_monthly_page_cap
    error_message = "di_monthly_page_cap must be a whole number from 1 to 500 (F0's monthly pages)."
  }
}

variable "invoice_currency" {
  description = "ISO 4217 currency of every invoice (INVOICE_CURRENCY); DI does not report SGD (AD-8)."
  type        = string
  default     = "SGD"

  validation {
    condition     = can(regex("^[A-Z]{3}$", var.invoice_currency))
    error_message = "invoice_currency must be a three-letter ISO 4217 code."
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
