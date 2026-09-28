output "function_apps" {
  description = "Per app: name, resource id, default host name (defaultHostName), and the plan id, identity ids, maximum instance count, instance memory and tags configured on the site."
  value       = module.app.function_apps
}

output "role_assignments" {
  description = "The runtime role assignments (AD-17 plus the Functions host containers), keyed by <app>/<service>/<target>: role, scope and principal id."
  value       = module.app.role_assignments
}

output "metric_alerts" {
  description = "The AD-17 metric alert rules (poison_message, stuck_invoices): name, resource id, scopes, action group ids and tags."
  value       = module.app.metric_alerts
}
