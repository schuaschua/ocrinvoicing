output "names" {
  description = "Resource names for this environment, keyed by resource kind (P-16)."
  value       = local.names
}

output "identity_names" {
  description = "Runtime user-assigned identity names keyed by app: supplier_api, staff_api, pipeline, accounts_sim. Empty for shared, whose id-21..23 are the deploy identities."
  value       = local.identities
}

output "app_names" {
  description = "Per Flex app (supplier_api, staff_api, pipeline, accounts_sim): plan, function app and deployment container names. Empty for shared."
  value       = local.apps
}

output "metric_alert_names" {
  description = "Per AD-17 pipeline alert, keyed by the metric it stands for (poison_message, stuck_invoices, di_pages_used_pct): the log alert rule's name. Empty for shared."
  value       = local.metric_alerts
}

output "private_key_vault_name" {
  description = "Name of this environment's private-key vault in rg-22 (kv-22 dev, kv-23 prod; OCR-129), created by infra/bootstrap/state-backend.sh, not Terraform. Null for shared."
  value       = local.private_key_vault
}

output "tags" {
  description = "The five P-17 tags, to pass unchanged to every taggable resource."
  value       = local.tags
}
