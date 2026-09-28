module "naming" {
  source = "../../modules/naming"

  environment         = local.environment
  number_base         = local.number_base
  owner               = var.owner
  cost_centre         = var.cost_centre
  application         = var.application
  data_classification = var.data_classification
}

# AD-17 step 7: the four Flex apps, their settings and runtime roles.
module "app" {
  source = "../../modules/env-app"

  environment       = local.environment
  location          = var.location
  resource_group_id = local.foundation.resource_group_id
  app_names         = local.app_names
  identities = {
    for app, identity in local.foundation.identities : app => {
      name         = identity.name
      resource_id  = identity.resource_id
      principal_id = identity.principal_id
      client_id    = identity.client_id
    }
  }
  storage_account = {
    name        = local.foundation.storage_account.name
    resource_id = local.foundation.storage_account.resource_id
  }
  database = {
    name = local.foundation.database.name
    fqdn = local.foundation.database.fqdn
  }
  key_vault = {
    resource_id = local.foundation.key_vault.resource_id
    uri         = local.foundation.key_vault.uri
  }
  application_insights_id                = local.foundation.application_insights.resource_id
  application_insights_connection_string = local.foundation.application_insights_connection_string
  # The only sampling (Application Insights samples nothing at ingestion).
  telemetry_sampling_ratio = var.telemetry_sampling_ratio
  tags                     = local.tags
}
