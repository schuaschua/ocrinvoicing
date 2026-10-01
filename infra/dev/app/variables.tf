variable "location" {
  description = "Azure region for every resource (P-16 region code sea)."
  type        = string
  default     = "southeastasia"
}

variable "owner" {
  description = "P-17 owner tag value."
  type        = string
}

variable "cost_centre" {
  description = "P-17 costCentre tag value."
  type        = string
}

variable "application" {
  description = "P-17 application tag value."
  type        = string
}

variable "data_classification" {
  description = "P-17 dataClassification tag value."
  type        = string
}

variable "telemetry_sampling_ratio" {
  description = "Fraction of traces each app keeps (AD-17, azure.md rule 16)."
  type        = number
  # [ASSUMPTION] Half the traces until calibrated against the 0.08 GB/day cap.
  default = 0.5
}

variable "accounts_sim_client_id" {
  description = "Client id of babaloo-sea-lng-accounts-sim-<env>, printed by infra/bootstrap/app-registrations.sh (AD-10, Story 3.1). Not a secret."
  type        = string
}

variable "staff_api_client_id" {
  description = "Client id of babaloo-sea-lng-staff-api-<env>, printed by infra/bootstrap/app-registrations.sh (AD-14). Not a secret."
  type        = string
}

variable "alert_recipients_finance" {
  description = "Story 5.2 (AD-16): finance's email addresses for price-rise alert emails (ALERT_RECIPIENTS_FINANCE). Empty by default: nobody."
  type        = list(string)
  default     = []
}

variable "alert_recipients_procurement" {
  description = "Story 5.2 (AD-16): procurement's email addresses for price-rise and watchlist alert emails (ALERT_RECIPIENTS_PROCUREMENT). Empty by default: nobody."
  type        = list(string)
  default     = []
}

variable "alert_recipients_management" {
  description = "Story 5.2 (AD-16): management's email addresses for watchlist alert emails (ALERT_RECIPIENTS_MANAGEMENT). Empty by default: nobody."
  type        = list(string)
  default     = []
}
