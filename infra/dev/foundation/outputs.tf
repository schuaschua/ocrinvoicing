output "resource_group_name" {
  description = "The environment's resource group."
  value       = azurerm_resource_group.this.name
}

output "resource_group_id" {
  description = "Resource id of the environment's resource group (parent of the <env>/app resources)."
  value       = azurerm_resource_group.this.id
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

output "document_intelligence_id" {
  description = "Resource id of the shared Document Intelligence F0 resource (from shared/foundation), for the pipeline's Cognitive Services User role in <env>/app (AD-8)."
  value       = data.terraform_remote_state.shared.outputs.document_intelligence_id
}

output "document_intelligence_endpoint" {
  description = "Custom-subdomain endpoint of the shared Document Intelligence resource (from shared/foundation), the pipeline's DI_ENDPOINT in <env>/app (AD-8)."
  value       = data.terraform_remote_state.shared.outputs.document_intelligence_endpoint
}

output "email" {
  description = "Story 5.2 (AD-16), from shared/foundation: the Communication Services resource id (the pipeline's ACS Email Sender scope), its endpoint and the alerts' sender address. Each is null while shared has no ACS Email (or an older shared state has no such output)."
  value = {
    communication_service_id = try(data.terraform_remote_state.shared.outputs.communication_service_id, null)
    acs_endpoint             = try(data.terraform_remote_state.shared.outputs.email_acs_endpoint, null)
    sender_address           = try(data.terraform_remote_state.shared.outputs.email_sender_address, null)
  }
}
