variable "environment" {
  description = "Environment or stack owner: dev, prod or shared. Also the value of the environment tag."
  type        = string

  validation {
    condition     = contains(["dev", "prod", "shared"], var.environment)
    error_message = "environment must be dev, prod or shared."
  }
}

variable "number_base" {
  description = "First two-digit number of this environment's range (P-16): 1 for dev (01-09), 11 for prod (11-19), 21 for shared (21-29)."
  type        = number

  validation {
    condition = (
      (var.environment == "dev" && var.number_base == 1) ||
      (var.environment == "prod" && var.number_base == 11) ||
      (var.environment == "shared" && var.number_base == 21)
    )
    error_message = "number_base must be 1 for dev, 11 for prod and 21 for shared."
  }
}

variable "owner" {
  description = "Value of the P-17 owner tag."
  type        = string

  validation {
    condition     = length(trimspace(var.owner)) > 0 && length(var.owner) <= 256
    error_message = "owner must be a non-empty tag value of at most 256 characters."
  }
}

variable "cost_centre" {
  description = "Value of the P-17 costCentre tag."
  type        = string

  validation {
    condition     = length(trimspace(var.cost_centre)) > 0 && length(var.cost_centre) <= 256
    error_message = "cost_centre must be a non-empty tag value of at most 256 characters."
  }
}

variable "application" {
  description = "Value of the P-17 application tag."
  type        = string

  validation {
    condition     = length(trimspace(var.application)) > 0 && length(var.application) <= 256
    error_message = "application must be a non-empty tag value of at most 256 characters."
  }
}

variable "data_classification" {
  description = "Value of the P-17 dataClassification tag."
  type        = string

  validation {
    condition     = length(trimspace(var.data_classification)) > 0 && length(var.data_classification) <= 256
    error_message = "data_classification must be a non-empty tag value of at most 256 characters."
  }
}
