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
