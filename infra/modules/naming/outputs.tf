output "names" {
  description = "Resource names for this environment, keyed by resource kind (P-16)."
  value       = local.names
}

output "identity_names" {
  description = "Runtime user-assigned identity names keyed by app: supplier_api, staff_api, pipeline, accounts_sim. Empty for shared, whose id-21..23 are the deploy identities."
  value       = local.identities
}

output "tags" {
  description = "The five P-17 tags, to pass unchanged to every taggable resource."
  value       = local.tags
}
