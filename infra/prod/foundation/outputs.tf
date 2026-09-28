output "resource_group_name" {
  description = "The environment's resource group."
  value       = azurerm_resource_group.this.name
}

output "identities" {
  description = "Runtime identities keyed by app (name, resource id, principal id, client id)."
  value       = module.foundation.identities
}

output "storage_account" {
  description = "Storage account name, id, containers, queues and tables."
  value       = module.foundation.storage_account
}

output "key_vault" {
  description = "Key Vault name, id and URI."
  value       = module.foundation.key_vault
}

output "log_analytics_workspace_id" {
  description = "Resource id of the Log Analytics workspace."
  value       = module.foundation.log_analytics_workspace_id
}

output "application_insights" {
  description = "Application Insights resource id and name."
  value       = module.foundation.application_insights
}

output "application_insights_connection_string" {
  description = "Application Insights connection string."
  value       = module.foundation.application_insights_connection_string
  sensitive   = true
}

output "action_group_id" {
  description = "Resource id of the action group that emails Dj."
  value       = module.foundation.action_group_id
}

output "database" {
  description = "This environment's database on the shared PostgreSQL server (from shared/foundation)."
  value = {
    name = data.terraform_remote_state.shared.outputs.database_names[local.environment]
    fqdn = data.terraform_remote_state.shared.outputs.postgres_fqdn
  }
}
