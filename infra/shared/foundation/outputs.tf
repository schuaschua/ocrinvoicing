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

output "communication_service_id" {
  description = "Resource id of the ACS resource."
  value       = azurerm_communication_service.this.id
}

output "communication_service_endpoint" {
  description = "ACS endpoint used by the email adapter with managed identity."
  value       = "https://${azurerm_communication_service.this.hostname}"
}

output "email_domain" {
  description = "The custom email domain, its resource id and the DNS records to add by hand."
  value = {
    name                 = var.email_custom_domain
    resource_id          = module.email.domain_resource_ids["custom"]
    verification_records = module.email.domain_verification_records["custom"]
    linked               = var.email_domain_link_enabled
  }
}

output "action_group_id" {
  description = "Resource id of the shared action group (ag-21) that emails Dj; pass it to infra/bootstrap/budget-and-roles.sh as SHARED_ACTION_GROUP_ID."
  value       = azurerm_monitor_action_group.this.id
}
