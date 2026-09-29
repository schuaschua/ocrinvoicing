# Single source of P-16 names and P-17 tags. The bootstrap scripts
# (infra/bootstrap/lib.sh) mirror these rules; keep the two in step.
#
# P-16: babaloo-sea-lng-<type>-<nn>. Numbers count up from the environment's base
# within each type (Dev 01-09, Prod 11-19, shared 21-29). Storage accounts drop
# the hyphens. Type abbreviations follow CAF.

locals {
  prefix         = "babaloo-sea-lng"
  storage_prefix = replace(local.prefix, "-", "")

  # name(type, offset) = "<prefix>-<type>-<base + offset, two digits>"
  first = { for type in local.types : type => format("%s-%s-%02d", local.prefix, type, var.number_base) }
  types = ["rg", "psql", "di", "acs", "ecs", "kv", "log", "appi", "ag", "budget"]

  # Runtime identities, numbered in this order from the base (plan Design Notes).
  app_identity_order = ["supplier_api", "staff_api", "pipeline", "accounts_sim"]

  names = {
    resource_group         = local.first["rg"]
    postgres_server        = local.first["psql"]
    document_intelligence  = local.first["di"]
    communication_service  = local.first["acs"]
    email_service          = local.first["ecs"]
    key_vault              = local.first["kv"]
    log_analytics          = local.first["log"]
    application_insights   = local.first["appi"]
    action_group           = local.first["ag"]
    budget                 = local.first["budget"]
    storage_account        = format("%sst%02d", local.storage_prefix, var.number_base)
    action_group_shortname = format("lng-ag-%02d", var.number_base)
  }

  # None for shared: its id-21..23 are the bootstrap's deploy identities.
  identities = {
    for index, app in local.app_identity_order :
    app => format("%s-id-%02d", local.prefix, var.number_base + index)
    if var.environment != "shared"
  }

  # The four Flex apps (AD-1), numbered like their identities: one plan (asp) and one
  # function app (func) each, plus the blob container that holds its deployment
  # package. Container names are per app, not per environment (one account each).
  apps = {
    for index, app in local.app_identity_order :
    app => {
      plan                 = format("%s-asp-%02d", local.prefix, var.number_base + index)
      function_app         = format("%s-func-%02d", local.prefix, var.number_base + index)
      deployment_container = "deploy-${replace(app, "_", "-")}"
    }
    if var.environment != "shared"
  }

  # OCR-129: each environment's private-key vault (kv-22 Dev, kv-23 Prod) lives in the
  # bootstrap-only rg-22 and is created by infra/bootstrap/state-backend.sh, never by
  # Terraform. Named here only so staff-api can be told where pgp-private-key is.
  private_key_vault = lookup({ dev = format("%s-kv-22", local.prefix), prod = format("%s-kv-23", local.prefix) }, var.environment, null)

  # Azure Monitor metric alert rules (azure.md: `ar`), numbered from the base in this
  # order. Story 2.2 adds the first two; Story 2.3's di_pages_used_pct comes next.
  metric_alert_order = ["poison_message", "stuck_invoices"]
  metric_alerts = {
    for index, metric in local.metric_alert_order :
    metric => format("%s-ar-%02d", local.prefix, var.number_base + index)
    if var.environment != "shared"
  }

  tags = {
    owner              = var.owner
    costCentre         = var.cost_centre
    environment        = var.environment
    application        = var.application
    dataClassification = var.data_classification
  }
}
