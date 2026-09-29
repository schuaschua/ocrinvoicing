output "resource_group_name" {
  description = "The shared resource group."
  value       = azurerm_resource_group.this.name
}

output "postgres_server_id" {
  description = "Resource id of the shared PostgreSQL server."
  value       = module.postgres.resource_id
}

output "postgres_server_name" {
  description = "Name of the shared PostgreSQL server."
  value       = module.postgres.name
}

output "postgres_fqdn" {
  description = "FQDN of the shared PostgreSQL server."
  value       = module.postgres.fqdn
}

output "database_names" {
  description = "Database name per environment (dev, prod)."
  value       = local.databases
}

output "document_intelligence_id" {
  description = "Resource id of the shared Document Intelligence F0 resource."
  value       = module.document_intelligence.resource_id
}

output "document_intelligence_endpoint" {
  description = "Custom-subdomain endpoint of Document Intelligence (managed identity only)."
  value       = module.document_intelligence.endpoint
}

output "action_group_id" {
  description = "Resource id of the shared action group (ag-21) that emails Dj; pass it to infra/bootstrap/budget-and-roles.sh as SHARED_ACTION_GROUP_ID."
  value       = azurerm_monitor_action_group.this.id
}
