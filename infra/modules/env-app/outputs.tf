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
