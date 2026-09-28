output "identities" {
  description = "Runtime identities keyed by app: resource id, principal id and client id (for <env>/app and the database step)."
  value = {
    for app, identity in module.identities : app => {
      name         = var.identity_names[app]
      resource_id  = identity.resource_id
      principal_id = identity.principal_id
      client_id    = identity.client_id
    }
  }
}

output "storage_account" {
  description = "Storage account name, id, containers, queues and tables."
  value = {
    name        = var.names.storage_account
    resource_id = module.storage.resource_id
    containers  = local.containers
    # Functions host containers (platform requirement beyond AD-17).
    host_containers = local.host_containers
    queues          = local.queues
    tables          = local.tables
  }
}

output "key_vault" {
  description = "Key Vault name, id, URI and the workspace its AuditEvent log goes to."
  value = {
    name                   = var.names.key_vault
    resource_id            = module.key_vault.resource_id
    uri                    = module.key_vault.uri
    audit_log_workspace_id = local.key_vault_diagnostic_settings.audit.workspace_resource_id
  }
}

output "log_analytics_workspace_id" {
  description = "Resource id of the Log Analytics workspace."
  value       = module.log_analytics.resource_id
}

output "application_insights" {
  description = "Application Insights name, id, ingestion sampling percentage (100: the apps sample) and custom-metric dimension setting."
  value = {
    name                         = var.names.application_insights
    resource_id                  = module.application_insights.resource_id
    sampling_percentage          = local.app_insights_ingestion_sampling_percentage
    custom_metrics_opted_in_type = azapi_update_resource.application_insights_custom_metric_dimensions.body.properties.CustomMetricsOptedInType
  }
}

output "application_insights_connection_string" {
  description = "Application Insights connection string (not a secret with local auth off, but kept out of logs)."
  value       = module.application_insights.connection_string
  sensitive   = true
}

output "budget_contact_groups" {
  description = "Action groups the resource-group budget notifies (every notification)."
  value       = tolist(distinct(flatten([for n in azurerm_consumption_budget_resource_group.this.notification : n.contact_groups])))
}

output "action_group_id" {
  description = "Resource id of the action group that emails Dj."
  value       = azurerm_monitor_action_group.this.id
}
