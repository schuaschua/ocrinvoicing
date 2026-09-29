output "function_apps" {
  description = "Per app: name, resource id, default host name (defaultHostName), and the plan id, identity ids, maximum instance count, instance memory and tags configured on the site."
  value       = module.app.function_apps
}

output "role_assignments" {
  description = "The runtime role assignments (AD-17 plus the Functions host containers), keyed by <app>/<service>/<target>: role, scope and principal id."
  value       = module.app.role_assignments
}

output "metric_alerts" {
  description = "The AD-17 metric alert rules (poison_message, stuck_invoices, di_pages_used_pct): name, resource id, scopes, action group ids, tags and criterion."
  value       = module.app.metric_alerts
}

output "staff_api_auth" {
  description = "staff-api's built-in auth (AD-14): client id, issuer, sign-in required, signed-out action, excluded paths, token store."
  value       = module.app.staff_api_auth
}
