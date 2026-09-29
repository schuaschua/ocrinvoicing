variable "location" {
  description = "Azure region for every regional resource (P-16 region code sea)."
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
  description = "Email address that receives the shared resource-group budget alerts (Dj)."
  type        = string
}

variable "email_custom_domain" {
  description = "Dj's own domain for ACS Email (AD-16), e.g. mail.example.com. Its DNS records are added by hand."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$", var.email_custom_domain))
    error_message = "email_custom_domain must be a lower-case DNS name."
  }
}

variable "email_domain_link_enabled" {
  description = "Link the custom domain to ACS. Leave false until the domain's DNS records are verified; Azure refuses to link an unverified domain."
  type        = bool
  default     = false
}

variable "postgres_entra_admin_object_id" {
  description = "Object id of the PostgreSQL Entra admin: the pg-admins group (babaloo-sea-lng-grp-21), whose members run AD-17 step 5."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.postgres_entra_admin_object_id))
    error_message = "postgres_entra_admin_object_id must be a GUID."
  }
}

variable "postgres_entra_admin_principal_name" {
  description = "Principal name of the PostgreSQL Entra admin (a user's UPN or a group's display name)."
  type        = string
}

variable "postgres_entra_admin_principal_type" {
  description = "Type of the PostgreSQL Entra admin: User, Group or ServicePrincipal."
  type        = string
  default     = "User"

  validation {
    condition     = contains(["User", "Group", "ServicePrincipal"], var.postgres_entra_admin_principal_type)
    error_message = "postgres_entra_admin_principal_type must be User, Group or ServicePrincipal."
  }
}

variable "budget_amount" {
  description = "Monthly budget for the shared resource group in the billing currency."
  type        = number

  validation {
    condition     = var.budget_amount > 0
    error_message = "budget_amount must be positive."
  }
}
