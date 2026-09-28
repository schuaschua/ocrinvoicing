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

variable "alert_email" {
  description = "Email address that receives budget and monitoring alerts (Dj)."
  type        = string
}

variable "budget_amount" {
  description = "Monthly resource-group budget in the billing currency."
  type        = number
}

variable "app_insights_sampling_percentage" {
  description = "Application Insights ingestion sampling percentage (below 100 = sampling on)."
  type        = number
}
