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

output "communication_service_id" {
  description = "Story 5.2: resource id of the shared Communication Services resource, where each environment's pipeline gets ACS Email Sender (null while email_custom_domain is empty)."
  value       = local.email_enabled ? azapi_resource.communication_service[0].id : null
}

output "email_acs_endpoint" {
  description = "Story 5.2: the Communication Services endpoint the pipelines send through, managed identity only (null while email_custom_domain is empty)."
  value       = local.email_enabled ? "https://${azapi_resource.communication_service[0].output.properties.hostName}" : null
}

output "email_domain_verification_records" {
  description = "Story 5.2: the DNS records (domain, SPF, DKIM, DKIM2, DMARC) Dj adds by hand at the registrar to verify email_custom_domain (null while it is empty)."
  value       = local.email_enabled ? module.email_service[0].domain_verification_records[local.email.domain_key] : null
}

output "email_sender_address" {
  description = "Story 5.2: the alerts' sender address, alerts@<email_custom_domain>; null until the domain is linked (email_domain_link_enabled), so no app sends from an unverified domain."
  value       = local.email_link_enabled ? "${local.email.sender_username}@${var.email_custom_domain}" : null
}
