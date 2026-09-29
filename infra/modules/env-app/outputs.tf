output "function_apps" {
  description = "Per app: name, resource id, default host name (defaultHostName, e.g. <name>.azurewebsites.net), and the plan id, identity ids, maximum instance count, instance memory and tags configured on the site."
  value = {
    for app in local.apps : app => {
      name                   = var.app_names[app].function_app
      resource_id            = module.function_apps[app].resource_id
      host_name              = nonsensitive(module.function_apps[app].resource.output.properties.defaultHostName)
      plan_id                = nonsensitive(module.function_apps[app].resource.body.properties.serverFarmId)
      identity_ids           = nonsensitive(module.function_apps[app].resource.identity[0].identity_ids)
      maximum_instance_count = nonsensitive(module.function_apps[app].resource.body.properties.functionAppConfig.scaleAndConcurrency.maximumInstanceCount)
      instance_memory_mb     = nonsensitive(module.function_apps[app].resource.body.properties.functionAppConfig.scaleAndConcurrency.instanceMemoryMB)
      tags                   = nonsensitive(module.function_apps[app].resource.tags)
    }
  }
}

output "plan_ids" {
  description = "Resource id of each app's Flex Consumption plan, keyed by app."
  value       = { for app in local.apps : app => module.plans[app].resource_id }
}

output "role_assignments" {
  description = "The runtime role assignments, keyed by <app>/<service>/<target>: role, scope and principal id."
  value = {
    for key, assignment in azurerm_role_assignment.runtime : key => {
      role         = assignment.role_definition_name
      scope        = assignment.scope
      principal_id = assignment.principal_id
    }
  }
}

output "telemetry_sampling_ratio" {
  description = "Fraction of traces each app keeps (the TELEMETRY_SAMPLING_RATIO app setting)."
  value       = var.telemetry_sampling_ratio
}

output "metric_alerts" {
  description = "The AD-17 metric alert rules, keyed by metric: name, resource id, scopes, action group ids and tags."
  value = {
    for metric, alert in {
      poison_message    = azurerm_monitor_metric_alert.poison_message
      stuck_invoices    = azurerm_monitor_metric_alert.stuck_invoices
      di_pages_used_pct = azurerm_monitor_metric_alert.di_pages_used_pct
      } : metric => {
      name             = alert.name
      resource_id      = alert.id
      scopes           = alert.scopes
      action_group_ids = [for action in alert.action : action.action_group_id]
      tags             = alert.tags
      # The one criterion's metric, operator and threshold.
      criteria = {
        metric_name = one(alert.criteria).metric_name
        operator    = one(alert.criteria).operator
        threshold   = one(alert.criteria).threshold
      }
    }
  }
}

output "staff_api_auth" {
  description = "staff-api's built-in auth (AD-14): Entra client id, OpenID issuer, whether sign-in is required, the action for signed-out requests, the excluded paths and whether the token store is on."
  value = {
    client_id                     = local.staff_api_auth.identityProviders.azureActiveDirectory.registration.clientId
    open_id_issuer                = local.staff_api_auth.identityProviders.azureActiveDirectory.registration.openIdIssuer
    require_authentication        = local.staff_api_auth.globalValidation.requireAuthentication
    unauthenticated_client_action = local.staff_api_auth.globalValidation.unauthenticatedClientAction
    excluded_paths                = local.staff_api_auth.globalValidation.excludedPaths
    token_store_enabled           = local.staff_api_auth.login.tokenStore.enabled
    site_id                       = azapi_update_resource.staff_api_auth.parent_id
  }
}

output "staff_api_app_settings" {
  description = "staff-api's app settings as this module sets them (no secrets: the Application Insights connection string is passed to the AVM module separately)."
  value       = local.app_settings["staff_api"]
}

output "pipeline_app_settings" {
  description = "The pipeline's app settings as this module sets them (no secrets)."
  value       = local.app_settings["pipeline"]
}
